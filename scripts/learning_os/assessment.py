"""Independent assessment workflow: create -> (hint) -> submit -> grade -> (review) -> commit.

Files per assessment, under programs/<id>/assessments/asm-NNN/:
  task.yaml     learner-facing task + lifecycle (schema assessment). Never contains the rubric or answer key.
  private.yaml  rubric and answer key (schema assessment-key). Shown only by `assess brief`, and only after a submission.

The only thing here that changes mastery is `commit`, which appends ONE event to logs/assessments.jsonl
(idempotent on assessment_id) through model.append_event. Everything else is workflow bookkeeping.

The private/public split is procedural, not a security boundary: the Tutor persists the files and any agent with
file access can read private.yaml. What the engine guarantees is that no briefing, context pack or learner-facing
command includes it, that the rubric cannot change after the task was issued (sha256), and that objective checks
are graded by code, not by a model.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from . import evidence, miniyaml, model

CREATE_KEYS = {"task_id", "type", "competency", "objective", "difficulty", "title", "prompt", "items", "rubric"}
GRADE_KEYS = {"criteria", "feedback", "confidence", "uncertainty", "misconceptions", "resolves", "needs_review", "review_reason"}
OPEN_STATES = ("issued", "submitted", "graded", "needs_review")
ASM_RE = re.compile(r"^asm-(\d{3,})$")


class Conflict(ValueError):
    """A request that clashes with what is already recorded."""


# --------------------------------------------------------------------------
# paths and IO
# --------------------------------------------------------------------------

def adir(root: Path, pid: str) -> Path:
    return model.program_dir(root, pid) / "assessments"


def _paths(root: Path, pid: str, aid: str) -> tuple[Path, Path]:
    if not ASM_RE.match(aid):
        raise ValueError(f"invalid assessment id {aid!r} (looks like asm-001)")
    d = adir(root, pid) / aid
    return d / "task.yaml", d / "private.yaml"


def _check(doc: Any, name: str, label: str) -> None:
    rep = model.Report()
    if not model.check_schema(rep, label, doc, name):
        raise ValueError("; ".join(rep.errors))


def load_task(root: Path, pid: str, aid: str) -> dict:
    path, _ = _paths(root, pid, aid)
    if not path.is_file():
        raise ValueError(f"no assessment {aid} in {pid}")
    try:
        doc = miniyaml.loads(path.read_text("utf-8"))
    except miniyaml.YamlError as exc:
        raise ValueError(f"{aid}: cannot parse YAML: {exc}")
    _check(doc, "assessment", aid)
    return doc


def _save_task(root: Path, doc: dict) -> None:
    _check(doc, "assessment", doc["id"])
    model.atomic_write(_paths(root, doc["program"], doc["id"])[0], miniyaml.dumps(doc))


def load_key(root: Path, pid: str, aid: str) -> dict:
    _, path = _paths(root, pid, aid)
    if not path.is_file():
        raise ValueError(f"{aid}: private rubric is missing")
    key = miniyaml.loads(path.read_text("utf-8"))
    _check(key, "assessment-key", f"{aid}/private")
    return key


def all_tasks(root: Path, pid: str) -> list[dict]:
    d = adir(root, pid)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir()):
        if ASM_RE.match(p.name) and (p / "task.yaml").is_file():
            out.append(load_task(root, pid, p.name))
    return out


def open_tasks(root: Path, pid: str) -> list[dict]:
    return [t for t in all_tasks(root, pid) if t["status"] in OPEN_STATES]


def key_hash(key: dict) -> str:
    return hashlib.sha256(json.dumps(key, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _now(ts: str | None) -> str:
    return ts or model.now_ts()


def _set_status(doc: dict, to: str, ts: str, note: str | None = None) -> None:
    doc["status"], doc["updated"] = to, ts
    h = {"ts": ts, "to": to}
    if note:
        h["note"] = note[:500]
    doc["history"].append(h)


# --------------------------------------------------------------------------
# rubric validation and objective grading
# --------------------------------------------------------------------------

def validate_key(key: dict, items: list[dict]) -> list[str]:
    """Rubric must be explicit before the learner sees the task. Returns problems."""
    out: list[str] = []
    item_ids = [i["id"] for i in items]
    if len(set(item_ids)) != len(item_ids):
        out.append("task item ids must be unique")
    ids = [c["id"] for c in key["criteria"]]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        out.append(f"duplicate criterion id {dup!r}")
    for c in key["criteria"]:
        cid = c["id"]
        if c["kind"] == "objective":
            chk = c.get("check")
            if not chk:
                out.append(f"objective criterion {cid!r} needs a `check`")
                continue
            if c.get("item") not in item_ids:
                out.append(f"objective criterion {cid!r} needs `item` naming one of the task items {item_ids}")
            if chk["type"] == "exact" and not chk.get("accept"):
                out.append(f"criterion {cid!r}: exact check needs `accept`")
            elif chk["type"] == "regex":
                try:
                    re.compile(chk.get("pattern") or "")
                except re.error as exc:
                    out.append(f"criterion {cid!r}: bad regex ({exc})")
                if not chk.get("pattern"):
                    out.append(f"criterion {cid!r}: regex check needs `pattern`")
            elif chk["type"] == "number" and "value" not in chk:
                out.append(f"criterion {cid!r}: number check needs `value`")
        else:
            for k in ("full", "zero"):
                if not c.get(k):
                    out.append(f"judged criterion {cid!r} needs `{k}` (what that credit level looks like) before the task is issued")
            if c.get("check"):
                out.append(f"judged criterion {cid!r} must not carry a `check`")
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().casefold())


def run_check(check: dict, response: str) -> bool:
    if check["type"] == "exact":
        return _norm(response) in {_norm(a) for a in check["accept"]}
    if check["type"] == "regex":
        return re.fullmatch(check["pattern"], response.strip(), re.I | re.S) is not None
    m = re.search(r"-?\d+(?:\.\d+)?", response.replace(",", ""))
    return bool(m) and abs(float(m.group(0)) - check["value"]) <= check.get("tolerance", 0)


def autograde(key: dict, submission: dict) -> dict[str, float]:
    resp = submission.get("responses", {})
    return {c["id"]: (1.0 if c["item"] in resp and run_check(c["check"], resp[c["item"]]) else 0.0)
            for c in key["criteria"] if c["kind"] == "objective"}


def compute_score(key: dict, credits: dict[str, float]) -> float:
    total = sum(c["weight"] for c in key["criteria"])
    return round(sum(c["weight"] * credits[c["id"]] for c in key["criteria"]) / total, 4)


# --------------------------------------------------------------------------
# create
# --------------------------------------------------------------------------

def objective_refs(root: Path, pid: str, program: dict) -> set[str]:
    from . import lifecycle  # lazy
    try:
        return {o["ref"] for o in lifecycle.curriculum_view(root, pid, program)["objectives"]}
    except ValueError:
        return {f"{c['id']}:overall" for c in program["competencies"]}


def _context_for_new(root: Path, pid: str, competency: str, review_session: str | None) -> dict:
    """Where does this assessment belong: the open lesson, or an open review session?"""
    from . import lifecycle, review
    if review_session:
        rs = review.load(root, pid, review_session)
        if rs["status"] != "open":
            raise ValueError(f"{review_session} is {rs['status']}, not open")
        if not any(i["competency"] == competency for i in rs["items"]):
            raise ValueError(f"{review_session} has no review item for {competency!r}")
        return {"review_session": review_session}
    cur = lifecycle.open_session(root, pid)
    if cur is not None and cur["status"] in ("active", "awaiting_assessment"):
        return {"lesson": cur["lesson"]}
    rs = review.open_session(root, pid)
    if rs is not None and any(i["competency"] == competency for i in rs["items"]):
        return {"review_session": rs["id"]}
    raise ValueError("no active lesson and no open review session covering this competency; "
                     "start one (`lesson start` / `review start`) before creating an assessment")


def create(root: Path, pid: str, draft: Any, *, review_session: str | None = None, ts: str | None = None) -> tuple[dict, str]:
    if not isinstance(draft, dict) or set(draft) - CREATE_KEYS:
        raise ValueError("assessment draft must be a mapping with keys from: " + ", ".join(sorted(CREATE_KEYS)))
    for k in ("task_id", "type", "competency", "difficulty", "title", "prompt", "rubric"):
        if k not in draft:
            raise ValueError(f"assessment draft needs `{k}`")
    program = model._load_valid_program(root, pid)
    comp = draft["competency"]
    if comp not in {c["id"] for c in program["competencies"]}:
        raise ValueError(f"unknown competency {comp!r}")
    objective = draft.get("objective") or f"{comp}:overall"
    if objective not in objective_refs(root, pid, program):
        raise ValueError(f"unknown objective {objective!r} for this program's curriculum")
    if objective.split(":")[0] != comp:
        raise ValueError(f"objective {objective!r} does not belong to competency {comp!r}")
    rubric = draft["rubric"]
    if not isinstance(rubric, dict) or set(rubric) - {"criteria", "answer_key", "misconception_signals"}:
        raise ValueError("`rubric` must be a mapping with criteria, answer_key, misconception_signals")
    items = draft.get("items", [])
    public = {k: draft[k] for k in ("type", "competency", "difficulty", "title", "prompt") if k in draft}
    public.update(task_id=draft["task_id"], objective=objective)
    if items:
        public["items"] = items
    with model.program_lock(root, pid):
        key = {"schema_version": 1, "id": "asm-000", **rubric}
        probe_task = {**public, "schema_version": 1, "id": "asm-000", "program": pid, "rubric_sha256": "0" * 64, "status": "issued",
                      "created": model.now_ts(), "updated": model.now_ts(), "attempt": {"assistance": "none", "hints": []},
                      "history": [{"ts": model.now_ts(), "to": "issued"}]}
        _check(probe_task, "assessment", "assessment draft")
        _check(key, "assessment-key", "rubric")
        problems = validate_key(key, items)
        if problems:
            raise ValueError("rubric is not valid: " + "; ".join(problems))
        digest = key_hash({k: v for k, v in key.items() if k != "id"})
        existing = [t for t in all_tasks(root, pid) if t["status"] != "void"]
        same = next((t for t in existing if t["task_id"] == draft["task_id"]), None)
        if same:
            old = {k: same.get(k) for k in ("type", "competency", "objective", "difficulty", "title", "prompt")}
            if old == {k: public.get(k) for k in old} and same["rubric_sha256"] == digest and same.get("items", []) == items:
                return same, f"{same['id']} already exists for task {same['task_id']} (no change)"
            raise Conflict(f"task_id {draft['task_id']!r} already used by {same['id']} with different content")
        norm = _norm(draft["prompt"])
        clash = next((t for t in existing if _norm(t["prompt"]) == norm), None)
        if clash:
            raise ValueError(f"the same prompt was already issued as {clash['id']}; do not reuse a scored item verbatim")
        if draft["type"] == "delayed_review":
            evs, _ = model.read_events(model.program_dir(root, pid) / "logs" / "assessments.jsonl")
            today = evidence.ts_date(_now(ts))
            if not any(e["competency"] == comp and evidence.counts(e) and evidence._is_pass(program, e)
                       and evidence.ts_date(e["ts"]) < today for e in evs):
                raise ValueError(f"nothing to review: {comp!r} has no independent passing result from an earlier day")
        where = _context_for_new(root, pid, comp, review_session)
        nums = [int(ASM_RE.match(p.name).group(1)) for p in adir(root, pid).glob("asm-*") if ASM_RE.match(p.name)] \
            if adir(root, pid).is_dir() else []
        aid = f"asm-{max(nums, default=0) + 1:03d}"
        key["id"] = aid
        now = _now(ts)
        task: dict[str, Any] = {"schema_version": 1, "id": aid, **public, "program": pid, **where,
                                "rubric_sha256": digest, "status": "issued", "created": now, "updated": now,
                                "attempt": {"assistance": "none", "hints": []}, "history": [{"ts": now, "to": "issued"}]}
        if program.get("curriculum"):
            task["curriculum_revision"] = program["curriculum"]["revision"]
        path, kpath = _paths(root, pid, aid)
        model.atomic_write(kpath, miniyaml.dumps(key))  # key first: a task without a key can never exist
        _save_task(root, task)
        if "review_session" in where:
            from . import review
            review.link(root, pid, where["review_session"], comp, aid, ts)
    return task, f"{aid} created and issued"


# --------------------------------------------------------------------------
# learner-facing
# --------------------------------------------------------------------------

def render_task(task: dict) -> str:
    L = [f"# Assessment {task['id']}: {task['title']}", "",
         f"Type: {task['type']} | difficulty: {task['difficulty']} | competency `{task['competency']}` | objective `{task['objective']}`",
         f"Status: {task['status']}; assistance so far: {task['attempt']['assistance']}", ""]
    if task["attempt"]["assistance"] == "none":
        L += ["This is an INDEPENDENT attempt: no hints, no tutoring, no notes from the lesson. Any help turns it into an "
              "assisted attempt, which is recorded honestly and does not count as mastery.", ""]
    else:
        L += [f"This attempt is ASSISTED ({task['attempt']['assistance']}); it will not count as independent evidence.", ""]
    L += [task["prompt"], ""]
    for it in task.get("items", []):
        L += [f"**{it['id']}**: {it['prompt']}", ""]
    return "\n".join(L).rstrip() + "\n"


def show(root: Path, pid: str, aid: str) -> str:
    return render_task(load_task(root, pid, aid))


def status_text(root: Path, pid: str) -> str:
    tasks = all_tasks(root, pid)
    openl = [t for t in tasks if t["status"] in OPEN_STATES]
    L = [f"# Assessments for {pid}", "", f"{len(tasks)} total; {len(openl)} open."]
    nxt = {"issued": "learner answers independently, then `assess submit`", "submitted": "Examiner grades (`assess brief`), then `assess grade`",
           "graded": "`assess commit`", "needs_review": "human review (`assess review --confirm`), then `assess commit`"}
    for t in openl:
        L.append(f"- `{t['id']}` {t['type']} on `{t['competency']}` ({t['difficulty']}): {t['status']}; next: {nxt[t['status']]}")
    return "\n".join(L)


# --------------------------------------------------------------------------
# hint / submit
# --------------------------------------------------------------------------

def hint(root: Path, pid: str, aid: str, level: str, note: str | None = None, ts: str | None = None) -> dict:
    if level not in evidence.ASSIST_ORDER[1:]:
        raise ValueError(f"level must be one of {evidence.ASSIST_ORDER[1:]}")
    with model.program_lock(root, pid):
        t = load_task(root, pid, aid)
        if t["status"] != "issued":
            raise ValueError(f"{aid} is {t['status']}; help can only be recorded before submission")
        now = _now(ts)
        h = {"ts": now, "level": level}
        if note:
            h["note"] = note[:300]
        t["attempt"]["hints"].append(h)
        if evidence.ASSIST_ORDER.index(level) > evidence.ASSIST_ORDER.index(t["attempt"]["assistance"]):
            t["attempt"]["assistance"] = level
        t["updated"] = now
        _save_task(root, t)
    return t


def submit(root: Path, pid: str, aid: str, answer: str = "", responses: dict | None = None, ts: str | None = None) -> tuple[dict, str]:
    responses = {str(k): str(v) for k, v in (responses or {}).items()}
    if not answer.strip() and not responses:
        raise ValueError("a submission needs an answer or item responses")
    with model.program_lock(root, pid):
        t = load_task(root, pid, aid)
        unknown = set(responses) - {i["id"] for i in t.get("items", [])}
        if unknown:
            raise ValueError(f"responses for unknown item(s) {sorted(unknown)}")
        digest = hashlib.sha256(json.dumps({"a": answer, "r": responses}, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        if t["status"] != "issued":
            if t.get("submission", {}).get("sha256") == digest and t["status"] != "void":
                return t, f"{aid} already submitted with this answer (no change)"
            if t.get("submission"):
                raise Conflict(f"{aid} already has a different submission; a submission is final")
            raise ValueError(f"{aid} is {t['status']}; it cannot take a submission")
        now = _now(ts)
        t["submission"] = {"ts": now, "answer": answer, "sha256": digest, **({"responses": responses} if responses else {})}
        _set_status(t, "submitted", now)
        _save_task(root, t)
    return t, f"{aid} submitted"


# --------------------------------------------------------------------------
# examiner brief (private material: post-submission only)
# --------------------------------------------------------------------------

def _verified_key(root: Path, pid: str, t: dict) -> dict:
    key = load_key(root, pid, t["id"])
    if key_hash({k: v for k, v in key.items() if k != "id"}) != t["rubric_sha256"]:
        raise ValueError(f"{t['id']}: the private rubric changed after the task was issued; void it and create a new one")
    return key


def brief(root: Path, pid: str, aid: str) -> str:
    t = load_task(root, pid, aid)
    if t["status"] == "issued" or "submission" not in t:
        raise ValueError(f"{aid} has no submission yet: the rubric and answer key are not revealed before the learner submits")
    key = _verified_key(root, pid, t)
    auto = autograde(key, t["submission"])
    L = [f"# Examiner brief for {aid} (PRIVATE: do not show the rubric or key to the learner)", "",
         "You are the Examiner. You have NOT seen the tutoring dialogue; grade only the answer below against the rubric. "
         "Return the grading YAML described at the end; do not coach the learner and do not write files.", "",
         render_task(t).rstrip(), "", "## Attempt", f"- assistance: {t['attempt']['assistance']} ({len(t['attempt']['hints'])} hint(s))"
         + ("" if t["attempt"]["assistance"] == "none" else "; the score is capped and the attempt is not independent evidence"), "",
         "## Learner submission", "", t["submission"]["answer"] or "(see item responses)"]
    for iid, r in t["submission"].get("responses", {}).items():
        L.append(f"- {iid}: {r}")
    L += ["", "## Rubric (private)", ""]
    for c in key["criteria"]:
        L.append(f"- `{c['id']}` [{c['kind']}, weight {c['weight']}]: {c['description']}")
        if c["kind"] == "objective":
            L.append(f"  - AUTO-GRADED by the engine: credit {auto[c['id']]} (do not override)")
        else:
            L += [f"  - full: {c['full']}"] + ([f"  - partial: {c['partial']}"] if c.get("partial") else []) + [f"  - zero: {c['zero']}"]
    if key.get("answer_key"):
        L += ["", "## Reference answer (private)", "", key["answer_key"]]
    for m in key.get("misconception_signals", []):
        L.append(f"- misconception signal: {m['text']} (look for: {m['signal']})")
    judged = [c["id"] for c in key["criteria"] if c["kind"] == "judged"]
    L += ["", "## Return exactly this YAML", "", "```yaml", "criteria:"]
    for cid in judged:
        L += [f"  {cid}:", "    credit: 0.0", "    evidence: \"quote or observation that justifies the credit\""]
    if not judged:
        L.append("  {}   # nothing to judge: all criteria are auto-graded")
    L += ["feedback: \"short feedback for the learner\"", "confidence: medium   # low | medium | high; low sends it to human review",
          "uncertainty: \"what could make this grade wrong, or omit\"", "misconceptions: []   # list of mappings: text (short falsifiable claim) + status (suspected|demonstrated)",
          "resolves: []         # texts of earlier misconceptions this answer shows are gone (independent attempts only)",
          "needs_review: false  # true when the answer is ambiguous or subjective", "```", "",
          "Be conservative: when ambiguous, score lower and say why in `uncertainty`; low confidence is a legitimate answer."]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------
# grade / review
# --------------------------------------------------------------------------

def _apply_grading(t: dict, key: dict, credits: dict[str, dict], method: str, confidence: str, feedback: str,
                   patch: dict, now: str) -> None:
    raw = compute_score(key, {cid: v["credit"] for cid, v in credits.items()})
    cap = evidence.ASSIST_CAP[t["attempt"]["assistance"]]
    g: dict[str, Any] = {"ts": now, "method": method, "raw_score": raw, "score": round(min(raw, cap), 4),
                         "confidence": confidence, "criteria": credits, "feedback": feedback[:1500]}
    for k in ("uncertainty", "review_reason"):
        if patch.get(k):
            g[k] = str(patch[k])[:500]
    for k in ("misconceptions", "resolves"):
        if patch.get(k):
            g[k] = patch[k]
    t["grading"] = g


def grade(root: Path, pid: str, aid: str, patch: Any, ts: str | None = None) -> tuple[dict, str]:
    if not isinstance(patch, dict) or set(patch) - GRADE_KEYS:
        raise ValueError("grading must be a mapping with keys from: " + ", ".join(sorted(GRADE_KEYS)))
    with model.program_lock(root, pid):
        t = load_task(root, pid, aid)
        if t["status"] not in ("submitted", "graded", "needs_review"):
            raise ValueError(f"{aid} is {t['status']}; only a submitted assessment can be graded")
        key = _verified_key(root, pid, t)
        auto = autograde(key, t["submission"])
        given = patch.get("criteria") or {}
        judged = {c["id"] for c in key["criteria"] if c["kind"] == "judged"}
        unknown = set(given) - {c["id"] for c in key["criteria"]}
        if unknown:
            raise ValueError(f"grading names unknown criteria {sorted(unknown)}")
        credits: dict[str, dict] = {}
        for c in key["criteria"]:
            cid = c["id"]
            if c["kind"] == "objective":
                if cid in given and float(given[cid].get("credit", -1)) != auto[cid]:
                    raise ValueError(f"criterion {cid!r} is objective and was auto-graded as {auto[cid]}; the Examiner cannot override it")
                credits[cid] = {"credit": auto[cid], "source": "auto"}
            else:
                g = given.get(cid)
                if not isinstance(g, dict) or "credit" not in g:
                    raise ValueError(f"judged criterion {cid!r} needs a credit")
                credit = g["credit"]
                if isinstance(credit, bool) or not isinstance(credit, (int, float)) or not 0 <= credit <= 1:
                    raise ValueError(f"criterion {cid!r}: credit must be between 0 and 1")
                if not str(g.get("evidence", "")).strip():
                    raise ValueError(f"criterion {cid!r}: grading evidence is required (quote or observation)")
                credits[cid] = {"credit": float(credit), "source": "examiner", "evidence": str(g["evidence"])[:500]}
        if not str(patch.get("feedback", "")).strip():
            raise ValueError("grading needs `feedback`")
        method = "examiner" if judged else "auto"
        confidence = patch.get("confidence", "high" if not judged else None)
        if confidence not in ("low", "medium", "high"):
            raise ValueError("judged grading needs `confidence` (low | medium | high)")
        if judged and confidence == "high" and not patch.get("uncertainty"):
            patch = {**patch, "uncertainty": "none stated"}
        for m in patch.get("misconceptions") or []:
            if not isinstance(m, dict) or m.get("status") not in ("suspected", "demonstrated") or len(str(m.get("text", ""))) < 3:
                raise ValueError("each misconception needs `text` and status suspected|demonstrated")
        if patch.get("resolves") and t["attempt"]["assistance"] != "none":
            raise ValueError("an assisted attempt cannot resolve a misconception")
        now = _now(ts)
        _apply_grading(t, key, credits, method, confidence, str(patch["feedback"]), patch, now)
        needs = confidence == "low" or bool(patch.get("needs_review"))
        if needs and not patch.get("review_reason"):
            t["grading"]["review_reason"] = "low confidence" if confidence == "low" else "flagged ambiguous by the Examiner"
        _set_status(t, "needs_review" if needs else "graded", now)
        _save_task(root, t)
    return t, (f"{aid} graded: score {t['grading']['score']} (confidence {confidence})"
               + ("; NEEDS HUMAN REVIEW before commit" if needs else ""))


def review_human(root: Path, pid: str, aid: str, *, confirm: bool, statement: str | None, credits: dict[str, float] | None = None,
                 ts: str | None = None) -> tuple[dict, str]:
    if not confirm or not statement:
        raise ValueError("human review needs the learner's/reviewer's decision in words: pass --statement and --confirm")
    with model.program_lock(root, pid):
        t = load_task(root, pid, aid)
        if t["status"] not in ("graded", "needs_review") or "grading" not in t:
            raise ValueError(f"{aid} is {t['status']}; only a graded assessment can be reviewed")
        key = _verified_key(root, pid, t)
        g = t["grading"]
        cr = {cid: dict(v) for cid, v in g["criteria"].items()}
        kinds = {c["id"]: c["kind"] for c in key["criteria"]}
        for cid, v in (credits or {}).items():
            if kinds.get(cid) != "judged":
                raise ValueError(f"{cid!r} is not a judged criterion; objective checks cannot be adjusted")
            if not 0 <= v <= 1:
                raise ValueError("credit must be between 0 and 1")
            cr[cid] = {"credit": float(v), "source": "human", "evidence": f"human review: {statement}"[:500]}
        now = _now(ts)
        patch = {k: g[k] for k in ("uncertainty", "misconceptions", "resolves") if k in g}
        _apply_grading(t, key, cr, "human_reviewed", "medium" if g["confidence"] == "low" else g["confidence"], g["feedback"], patch, now)
        t["review"] = {"ts": now, "statement": statement[:500]}
        _set_status(t, "graded", now, "human reviewed")
        _save_task(root, t)
    return t, f"{aid} reviewed: score {t['grading']['score']}"


# --------------------------------------------------------------------------
# commit (the only step that creates evidence)
# --------------------------------------------------------------------------

def build_event_fields(t: dict) -> dict:
    g = t["grading"]
    extra: dict[str, Any] = {
        "assessment_id": t["id"], "task_id": t["task_id"], "type": t["type"], "objective": t["objective"],
        "difficulty": t["difficulty"], "independence": "independent" if t["attempt"]["assistance"] == "none" else "assisted",
        "assistance": t["attempt"]["assistance"], "hints": len(t["attempt"]["hints"]), "confidence": g["confidence"],
        "grading_method": g["method"], "rubric_sha256": t["rubric_sha256"], "evidence": [f"assessment:{t['id']}"],
    }
    if "curriculum_revision" in t:
        extra["curriculum_revision"] = t["curriculum_revision"]
    if "review_session" in t:
        extra["review_session"] = t["review_session"]
    if g.get("misconceptions"):
        extra["misconceptions"] = g["misconceptions"]
    if g.get("resolves"):
        extra["resolves"] = g["resolves"]
    return extra


def commit(root: Path, pid: str, aid: str, ts: str | None = None) -> tuple[dict, str]:
    program = model._load_valid_program(root, pid)
    with model.program_lock(root, pid):
        t = load_task(root, pid, aid)
        events, _ = model.read_events(model.program_dir(root, pid) / "logs" / "assessments.jsonl")
        logged = model.find_event(events, aid)
        if t["status"] == "committed" and logged:
            return t, f"{aid} already committed (no change)"
        if t["status"] == "void":
            raise ValueError(f"{aid} is void")
        if t["status"] not in ("graded", "committed") or "grading" not in t:
            hint_ = "; run human review first (`assess review --confirm`)" if t["status"] == "needs_review" else ""
            raise ValueError(f"{aid} is {t['status']}; only a graded assessment can be committed{hint_}")
        _verified_key(root, pid, t)
        g = t["grading"]
        extra = build_event_fields(t)
        if not logged:
            candidate = {"competency": t["competency"], "score": g["score"], **extra}
            for text in extra.get("resolves", []):
                if not evidence.resolution_ok(program, candidate):
                    raise ValueError("this result cannot resolve a misconception: resolution needs a valid, independent, passing, "
                                     "non-easy assessment. Regrade without `resolves`.")
            model.append_event(root, pid, lesson=t.get("lesson"), competency=t["competency"], kind=evidence.TYPE_TO_KIND[t["type"]],
                               score=g["score"], notes=g["feedback"][:500], ts=ts, extra=extra)
            events, _ = model.read_events(model.program_dir(root, pid) / "logs" / "assessments.jsonl")
            logged = model.find_event(events, aid)
        now = _now(ts)
        t["commit"] = {"ts": now, "event": f"logs/assessments.jsonl:{logged['_line']}"}
        _set_status(t, "committed", now)
        _save_task(root, t)
    kind = "independent" if t["attempt"]["assistance"] == "none" else "ASSISTED (not independent evidence)"
    return t, f"{aid} committed as {kind} evidence, score {g['score']} at {t['commit']['event']}"


def void(root: Path, pid: str, aid: str, reason: str, ts: str | None = None) -> tuple[dict, str]:
    if not reason:
        raise ValueError("voiding needs --reason")
    with model.program_lock(root, pid):
        t = load_task(root, pid, aid)
        if t["status"] == "void":
            return t, f"{aid} already void (no change)"
        events, _ = model.read_events(model.program_dir(root, pid) / "logs" / "assessments.jsonl")
        if t["status"] == "committed" or model.find_event(events, aid):
            raise ValueError(f"{aid} is already in the evidence log; correct it with a later, explained event instead")
        t["void_reason"] = reason[:500]
        _set_status(t, "void", _now(ts), reason)
        _save_task(root, t)
    return t, f"{aid} voided"


def unfinished_for_lesson(root: Path, pid: str, lesson: int) -> list[dict]:
    return [t for t in open_tasks(root, pid) if t.get("lesson") == lesson and t["status"] != "issued"]


# --------------------------------------------------------------------------
# validation hook (called from model.validate_root, per program)
# --------------------------------------------------------------------------

def validate_program(root: Path, pid: str, report: model.Report) -> None:
    d = adir(root, pid)
    if not d.is_dir():
        return
    base = f"programs/{pid}/assessments"
    pdir = model.program_dir(root, pid)
    program = miniyaml.loads((pdir / "program.yaml").read_text("utf-8"))
    known = {c["id"] for c in program.get("competencies", [])}
    events, _ = model.read_events(pdir / "logs" / "assessments.jsonl")
    by_aid = {e["assessment_id"]: e for e in events if "assessment_id" in e}
    seen_tasks: dict[str, str] = {}
    present: set[str] = set()
    for p in sorted(d.iterdir()):
        if p.name.startswith(".tmp-"):
            report.warn(f"{base}/{p.name}", "leftover temporary file from an interrupted write; safe to delete")
            continue
        if not ASM_RE.match(p.name) or not p.is_dir():
            report.error(base, f"unexpected entry {p.name!r} (assessments are asm-NNN/ directories)")
            continue
        where = f"{base}/{p.name}"
        for tmp in p.glob(".tmp-*"):
            report.warn(f"{where}/{tmp.name}", "leftover temporary file from an interrupted write; safe to delete")
        if not (p / "task.yaml").is_file():
            report.warn(where, "has no task.yaml (create was interrupted before issuing); safe to delete")
            continue
        try:
            t = load_task(root, pid, p.name)
            key = load_key(root, pid, p.name)
        except ValueError as exc:
            report.error(where, str(exc))
            continue
        present.add(t["id"])
        if t["id"] != p.name or t["program"] != pid or key["id"] != t["id"]:
            report.error(where, "id/program do not match the directory")
        if t["competency"] not in known:
            report.error(where, f"unknown competency {t['competency']!r}")
        if t["objective"].split(":")[0] != t["competency"]:
            report.error(where, "objective does not belong to the task's competency")
        for prob in validate_key(key, t.get("items", [])):
            report.error(where, prob)
        if key_hash({k: v for k, v in key.items() if k != "id"}) != t["rubric_sha256"]:
            report.error(where, "private rubric no longer matches the hash recorded when the task was issued")
        if t["status"] != "void":
            if t["task_id"] in seen_tasks:
                report.error(where, f"task_id {t['task_id']!r} duplicates {seen_tasks[t['task_id']]}")
            seen_tasks[t["task_id"]] = t["id"]
        if ("lesson" in t) == ("review_session" in t):
            report.error(where, "exactly one of `lesson` / `review_session` is required")
        ev = by_aid.get(t["id"])
        if t["status"] == "committed":
            if ev is None:
                report.error(where, "is committed but its event is missing from logs/assessments.jsonl")
            elif ev["competency"] != t["competency"] or ev["score"] != t["grading"]["score"]:
                report.error(where, "committed event does not match the graded result")
        elif ev is not None and t["status"] != "void":
            report.warn(where, f"its event is already logged but the task is {t['status']} (interrupted commit); re-run `assess commit`")
        elif ev is not None:
            report.error(where, "is void but its event is in the evidence log")
        if t["status"] in ("graded", "needs_review", "committed") and "grading" not in t:
            report.error(where, f"is {t['status']} without grading")
        if t["status"] != "issued" and t["status"] != "void" and "submission" not in t:
            report.error(where, f"is {t['status']} without a submission")
    for aid in sorted(set(by_aid) - present):
        report.error(f"{base}", f"event for {aid} exists but the assessment record is missing")
