"""Lesson lifecycle: planning, state machine, notes, closure, and the lesson-focused context blocks.

Subject-agnostic. Objectives, prerequisites and resources come from the program's activated,
approved curriculum snapshot (or, for programs without a curriculum pipeline, from its competencies).

Durable files (all under programs/<id>/):
  sessions/NNN.yaml            mutable lifecycle record of lesson NNN (schema lesson-session)
  lessons/NNN-slug.md          immutable human-readable record, written once at close (schema lesson-record)
  logs/assessments.jsonl       the ONLY evidence of mastery; this module never writes it

Completing a lesson is instructional completion. It never creates assessment events and never changes
mastery; `assessment` on the closure only *points at* events that already exist in the log.
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from . import design, miniyaml, model, onboarding

OPEN = ("planned", "active", "paused", "awaiting_assessment")
TERMINAL = ("completed", "abandoned")
TRANSITIONS = {
    "planned": {"active", "abandoned"},
    "active": {"paused", "awaiting_assessment", "completed", "abandoned"},
    "paused": {"active", "abandoned"},
    "awaiting_assessment": {"active", "completed", "abandoned"},
    "completed": set(),
    "abandoned": set(),
}
DEMONSTRATED = ("proficient", "mastered")
DEFAULT_MAX_CHARS = 16000
MISCONCEPTION_CAP = 3
SESSION_RE = re.compile(r"^(\d{3})\.yaml$")


class Conflict(ValueError):
    """A request that would clash with another conversation's lesson."""


# --------------------------------------------------------------------------
# paths and IO
# --------------------------------------------------------------------------

def sessions_dir(root: Path, pid: str) -> Path:
    return model.program_dir(root, pid) / "sessions"


def session_path(root: Path, pid: str, number: int) -> Path:
    return sessions_dir(root, pid) / f"{number:03d}.yaml"


def _now(ts: str | None) -> str:
    return ts or model.now_ts()


def load_session(root: Path, pid: str, number: int) -> dict:
    path = session_path(root, pid, number)
    if not path.is_file():
        raise ValueError(f"no lesson session {number} for {pid}")
    return _read(path)


def _read(path: Path) -> dict:
    try:
        doc = miniyaml.loads(path.read_text("utf-8"))
    except (miniyaml.YamlError, UnicodeDecodeError) as exc:
        raise ValueError(f"{path.name}: cannot parse YAML: {exc}")
    rep = model.Report()
    if not model.check_schema(rep, path.name, doc, "lesson-session"):
        raise ValueError("; ".join(rep.errors))
    return doc


def all_sessions(root: Path, pid: str) -> list[dict]:
    d = sessions_dir(root, pid)
    if not d.is_dir():
        return []
    return [_read(p) for p in sorted(d.iterdir()) if SESSION_RE.match(p.name)]


def open_session(root: Path, pid: str) -> dict | None:
    opens = [s for s in all_sessions(root, pid) if s["status"] in OPEN]
    if len(opens) > 1:
        raise ValueError(f"{len(opens)} open lesson sessions found ({', '.join(s['id'] for s in opens)}); "
                         "resolve by pausing/abandoning all but one (state is inconsistent)")
    return opens[0] if opens else None


def _save(root: Path, doc: dict) -> None:
    rep = model.Report()
    if not model.check_schema(rep, doc["id"], doc, "lesson-session"):
        raise ValueError("refusing to write an invalid lesson session: " + "; ".join(rep.errors))
    onboarding._atomic_write(session_path(root, doc["program"], doc["lesson"]), miniyaml.dumps(doc))


def _create(root: Path, doc: dict) -> None:
    """Exclusive create: never overwrites an existing session file (atomic via hard link)."""
    rep = model.Report()
    if not model.check_schema(rep, doc["id"], doc, "lesson-session"):
        raise ValueError("refusing to write an invalid lesson session: " + "; ".join(rep.errors))
    path = session_path(root, doc["program"], doc["lesson"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(miniyaml.dumps(doc))
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise Conflict(f"{path.name} already exists; another conversation planned this lesson first")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# --------------------------------------------------------------------------
# curriculum view (pinned to an approved snapshot) and evidence state
# --------------------------------------------------------------------------

def _program(root: Path, pid: str) -> dict:
    return model._load_valid_program(root, pid)


def curriculum_view(root: Path, pid: str, program: dict) -> dict:
    """Ordered objectives for planning. Refuses anything that is not an activated, approved curriculum."""
    comps = {c["id"]: c for c in program["competencies"]}
    pointer = program.get("curriculum")
    if pointer:
        snap = design.load_snapshot(root, pid, pointer["revision"])  # verifies the approval hash
        cmap = design._load_map_for(root, pid, snap)
        cdef = {c["id"]: c for c in cmap["competencies"]}
        decisions = {d["competency"]: d for d in snap["personalization"]["decisions"]}
        objectives, seen = [], set()
        for mod in snap["modules"]:
            for ref in mod["objectives"]:
                cid, oid = ref.split(":")
                if ref in seen or cid not in comps:
                    continue
                seen.add(ref)
                obj = next(o for o in cdef[cid]["objectives"] if o["id"] == oid)
                crit = [c["criterion"] for c in cdef[cid]["assessment_criteria"] if c["objective"] == oid]
                objectives.append({"ref": ref, "competency": cid, "id": oid, "text": obj["text"], "module": mod["id"],
                                   "module_title": mod["title"], "criteria": crit,
                                   "exercises": [e["title"] for e in mod["exercises"] if ref in e["objectives"]],
                                   "resources": mod["resources"]})
        return {"mode": "pinned", "revision": pointer["revision"], "sha256": design.content_hash(snap),
                "snapshot": pointer["snapshot"], "objectives": objectives, "comps": comps, "decisions": decisions,
                "modules": {m["id"]: m for m in snap["modules"]}}
    if "spec" in program or design.ddir(root, pid).is_dir():
        try:
            stage, nxt = design.stage(root, pid)
        except Exception:
            stage, nxt = "unknown", "run `curriculum status`"
        raise ValueError("no approved, activated curriculum: lessons are never planned from drafts or placeholders "
                         f"(stage: {stage}; next: {nxt})")
    objectives = [{"ref": f"{c['id']}:overall", "competency": c["id"], "id": "overall", "text": c["description"],
                   "module": None, "module_title": None, "criteria": [], "exercises": [], "resources": []}
                  for c in program["competencies"]]
    return {"mode": "legacy", "revision": None, "sha256": None, "snapshot": None, "objectives": objectives,
            "comps": comps, "decisions": {}, "modules": {}}


def _mastery(root: Path, pid: str) -> dict:
    return miniyaml.loads((model.program_dir(root, pid) / "state" / "mastery.yaml").read_text("utf-8"))["competencies"]


def covered_objectives(view: dict, lessons: list[dict]) -> set[str]:
    """Instructionally covered objectives: from completed lesson records only (NOT demonstrated mastery)."""
    out: set[str] = set()
    for rec in lessons:
        meta = rec["meta"]
        if meta["outcome"] != "completed":
            continue
        out.update(meta.get("objectives", []))
        if view["mode"] == "legacy":
            out.update(f"{c}:overall" for c in meta["competencies_covered"])
    return out


def evaluate(view: dict, mastery: dict, covered: set[str]) -> list[dict]:
    """Per-objective planning state, in curriculum order."""
    by_comp: dict[str, list[str]] = {}
    for o in view["objectives"]:
        by_comp.setdefault(o["competency"], []).append(o["ref"])
    out = []
    for o in view["objectives"]:
        cid = o["competency"]
        unmet = [p for p in view["comps"][cid]["prerequisites"] if mastery[p]["status"] not in DEMONSTRATED]
        done = o["ref"] in covered
        if not done and mastery[cid]["status"] in DEMONSTRATED:
            kind = None  # independent evidence already demonstrates the competency; nothing new to teach
        elif not done:
            kind = "new"
        elif mastery[cid]["status"] not in DEMONSTRATED and all(r in covered for r in by_comp[cid]):
            kind = "consolidate"
        else:
            kind = None
        out.append({**o, "covered": done, "unmet": unmet, "kind": kind, "status": mastery[cid]["status"]})
    return out


def _prev_next_focus(lessons: list[dict]) -> list[str]:
    return list(lessons[-1]["meta"]["next_focus"]) if lessons else []


def recommend(root: Path, pid: str) -> dict:
    """Deterministic recommendation. Returns {view, pick, reason, alternatives, blockers, states}."""
    program = _program(root, pid)
    view = curriculum_view(root, pid, program)
    mastery = _mastery(root, pid)
    lessons = sorted(model.read_lessons(model.program_dir(root, pid))[0], key=lambda r: r["file_number"])
    states = evaluate(view, mastery, covered_objectives(view, lessons))
    todo = [s for s in states if s["kind"]]
    eligible = [s for s in todo if not s["unmet"]]
    hint = _prev_next_focus(lessons)
    ordered = [s for s in eligible if s["competency"] in hint] + [s for s in eligible if s["competency"] not in hint]
    blockers = []
    for s in todo:
        if s["unmet"]:
            blockers.append(f"{s['ref']} is blocked: prerequisite(s) not yet demonstrated by logged assessment: "
                            + ", ".join(f"{p} ({mastery[p]['status']})" for p in s["unmet"]))
    if not todo:
        blockers.append("every objective in the curriculum is instructionally covered and its competency is demonstrated; "
                        "nothing further to teach from this curriculum (extend it via the curriculum workflow)")
    elif not eligible:
        blockers.insert(0, "no objective is currently eligible; resolve the prerequisites below")
    if not view["objectives"]:
        blockers = ["the curriculum has no objectives attached to its modules"]
    pick = ordered[0] if ordered else None
    reason = _why(pick, view, mastery, hint) if pick else None
    return {"program": program, "view": view, "mastery": mastery, "pick": pick, "reason": reason,
            "alternatives": ordered[1:3], "blockers": blockers, "states": states, "lessons": lessons}


def _why(s: dict, view: dict, mastery: dict, hint: list[str]) -> str:
    parts = []
    if s["kind"] == "consolidate":
        parts.append(f"taught earlier but competency `{s['competency']}` is {s['status']} (no demonstrated mastery); "
                     "needs an independent challenge")
    else:
        parts.append("next uncovered objective in curriculum order"
                     + (f" (module `{s['module']}`)" if s["module"] else ""))
    if s["competency"] in hint:
        parts.append("the previous lesson recommended this competency")
    prereqs = view["comps"][s["competency"]]["prerequisites"]
    parts.append("prerequisites: " + (", ".join(f"{p} {mastery[p]['status']}" for p in prereqs) if prereqs else "none"))
    dec = view["decisions"].get(s["competency"])
    if dec and any(e["kind"] == "self_reported" for e in dec["evidence"]):
        parts.append("learner reports prior experience here: self-reported, NOT demonstrated; verify before skipping")
    return "; ".join(parts)


def format_recommendation(rec: dict) -> str:
    L = ["# Next lesson recommendation", "",
         f"Curriculum: {'pinned r%s (%s)' % (rec['view']['revision'], rec['view']['sha256'][:8]) if rec['view']['mode'] == 'pinned' else 'legacy (competency-level objectives; no curriculum pipeline)'}"]
    if rec["pick"]:
        p = rec["pick"]
        L += ["", f"Recommended: `{p['ref']}` ({p['kind']}): {p['text']}", f"Why: {rec['reason']}"]
        if rec["alternatives"]:
            L += ["", "Alternatives (eligible):"] + [f"- `{a['ref']}` ({a['kind']}): {a['text']}" for a in rec["alternatives"]]
    if rec["blockers"]:
        L += ["", "Blockers:"] + [f"- {b}" for b in rec["blockers"]]
    return "\n".join(L)


# --------------------------------------------------------------------------
# planning and transitions
# --------------------------------------------------------------------------

def _registry_status(root: Path, pid: str) -> dict[str, str]:
    try:
        return {s["id"]: s["status"] for s in design.load_registry(root, pid)["sources"]}
    except Exception:
        return {}


def _next_number(root: Path, pid: str) -> int:
    pdir = model.program_dir(root, pid)
    lessons, errs = model.read_lessons(pdir)
    if errs:
        raise ValueError("lesson records are invalid: " + "; ".join(errs))
    return max((r["file_number"] for r in lessons), default=0) + 1


def _require_healthy(root: Path, pid: str) -> None:
    rep = model.validate_root(root, pid)
    if not rep.ok:
        raise ValueError("program does not validate; fix first:\n  " + "\n  ".join(rep.errors))


def _transition(doc: dict, to: str, ts: str, note: str | None = None) -> None:
    frm = doc["status"]
    if to not in TRANSITIONS[frm]:
        raise ValueError(f"invalid transition {frm} -> {to} for {doc['id']}")
    entry = {"ts": ts, "from": frm, "to": to}
    if note:
        entry["note"] = note
    doc["history"].append(entry)
    doc["status"] = to
    doc["updated"] = ts
    if to == "active" and "started" not in doc:
        doc["started"] = ts
    if to in TERMINAL:
        doc["finished"] = ts


def plan_lesson(root: Path, pid: str, *, objective: str | None = None, override_rationale: str | None = None,
                statement: str | None = None, confirm: bool = False, provider: str | None = None,
                thread: str | None = None, ts: str | None = None) -> tuple[dict, bool]:
    """Create a `planned` lesson, or return the existing open one. Returns (session, created)."""
    root = Path(root)
    existing = open_session(root, pid)
    if existing:
        if objective and objective not in existing["objectives"]:
            raise Conflict(f"{existing['id']} is already open ({existing['status']}) on {existing['objectives'][0]}; "
                           "pause, complete or abandon it before planning another objective")
        return existing, False
    _require_healthy(root, pid)
    rec = recommend(root, pid)
    program = rec["program"]
    if program["status"] != "active":
        raise ValueError(f"program status is {program['status']!r}; only active programs can have lessons")
    view, mastery = rec["view"], rec["mastery"]
    by_ref = {s["ref"]: s for s in rec["states"]}
    if objective:
        if objective not in by_ref:
            raise ValueError(f"unknown objective {objective!r}; known: " + ", ".join(by_ref) )
        s = by_ref[objective]
        selection: dict[str, Any] = {"mode": "manual", "reason": f"selected by the learner; {_why(s, view, mastery, [])}"}
        selection["kind"] = s["kind"] or "repeat"
        if s["unmet"]:
            if not (override_rationale and statement and confirm):
                raise ValueError(f"{objective} has prerequisites without demonstrated mastery: "
                                 + ", ".join(f"{p} ({mastery[p]['status']})" for p in s["unmet"])
                                 + ". Choose a different objective"
                                 + (f" (recommended: {rec['pick']['ref']})" if rec["pick"] else "")
                                 + ", or record a learner-approved override with --override-rationale, --statement and --confirm.")
            selection.update(mode="override", unmet_prerequisites=list(s["unmet"]),
                             override={"rationale": override_rationale, "statement": statement})
    else:
        if not rec["pick"]:
            raise ValueError("no suitable next objective:\n  " + "\n  ".join(rec["blockers"]))
        s = rec["pick"]
        selection = {"mode": "auto", "reason": rec["reason"], "kind": s["kind"]}
    ts = _now(ts)
    reg = _registry_status(root, pid)
    materials = [{"source": r["source"], "use": r["use"], "status_at_plan": reg.get(r["source"], "unknown")}
                 for r in s["resources"]]
    number = _next_number(root, pid)
    doc: dict[str, Any] = {
        "schema_version": 1, "id": f"lesson-{number:03d}", "program": pid, "lesson": number, "status": "planned",
        "created": ts, "updated": ts,
        "curriculum": {"mode": view["mode"]},
        "selection": selection, "objectives": [s["ref"]], "competencies": [s["competency"]],
        "outcomes": [s["text"]] + s["criteria"], "materials": materials,
        "history": [{"ts": ts, "to": "planned", "note": "planned"}],
    }
    if view["mode"] == "pinned":
        doc["curriculum"].update(revision=view["revision"], sha256=view["sha256"], snapshot=view["snapshot"])
    if provider or thread:
        doc["provider"] = _provider(provider, thread)
    _create(root, doc)
    return doc, True


def _provider(provider: str | None, thread: str | None) -> dict:
    p: dict[str, Any] = {}
    if provider:
        p["name"] = provider
    if thread:
        p["thread_ref"] = thread
    return p


def _attach_provider(doc: dict, provider: str | None, thread: str | None, *, takeover: bool) -> None:
    """Record the GUI thread. Two *known and different* thread refs on a live lesson are a conflict."""
    if not (provider or thread):
        return
    old = doc.get("provider", {})
    if (doc["status"] in ("active", "awaiting_assessment") and not takeover and thread
            and old.get("thread_ref") and old["thread_ref"] != thread):
        raise Conflict(f"{doc['id']} is active in another conversation ({old.get('name', '?')}:{old['thread_ref']}); "
                       "pause it there, or resume with --takeover if that conversation is gone")
    doc["provider"] = {**old, **_provider(provider, thread)}


def start_lesson(root: Path, pid: str, *, provider: str | None = None, thread: str | None = None,
                 ts: str | None = None, **plan_kwargs) -> tuple[dict, str]:
    """Plan (if nothing is open) and activate. Idempotent. Returns (session, what_happened)."""
    doc, created = plan_lesson(root, pid, provider=provider, thread=thread, ts=ts, **plan_kwargs)
    if doc["status"] == "planned":
        _attach_provider(doc, provider, thread, takeover=False)
        _transition(doc, "active", _now(ts), "started")
        _save(root, doc)
        return doc, "started"
    if doc["status"] in ("active", "awaiting_assessment"):
        _attach_provider(doc, provider, thread, takeover=False)
        _save(root, doc) if (provider or thread) else None
        return doc, "already active (no change)"
    raise ValueError(f"{doc['id']} is {doc['status']}; use `lesson resume` to continue it")


def resume_lesson(root: Path, pid: str, *, provider: str | None = None, thread: str | None = None,
                  takeover: bool = False, ts: str | None = None) -> tuple[dict, str]:
    doc = open_session(root, pid)
    if doc is None:
        raise ValueError("no open lesson to resume; use `lesson start`")
    _check_not_finalizing(doc)
    ts = _now(ts)
    if doc["status"] in ("active", "awaiting_assessment"):
        _attach_provider(doc, provider, thread, takeover=takeover)
        if takeover:
            doc["history"].append({"ts": ts, "from": doc["status"], "to": doc["status"], "note": "takeover by a new conversation"})
            doc["updated"] = ts
        _save(root, doc)
        return doc, "already active" + (" (took over)" if takeover else " (no change)")
    _attach_provider(doc, provider, thread, takeover=True)
    _transition(doc, "active", ts, "resumed")
    _save(root, doc)
    return doc, "resumed"


def _check_not_finalizing(doc: dict) -> None:
    if "closure" in doc and doc["status"] in OPEN:
        raise ValueError(f"{doc['id']} is mid-close; re-run `lesson complete` (or `lesson abandon`) to finish it")


def pause_lesson(root: Path, pid: str, *, note: str | None = None, ts: str | None = None) -> tuple[dict, str]:
    doc = open_session(root, pid)
    if doc is None:
        raise ValueError("no open lesson to pause")
    if doc["status"] == "paused":
        return doc, "already paused (no change)"
    _check_not_finalizing(doc)
    _transition(doc, "paused", _now(ts), note or "paused")
    _save(root, doc)
    return doc, "paused"


def await_assessment(root: Path, pid: str, *, ts: str | None = None) -> tuple[dict, str]:
    doc = open_session(root, pid)
    if doc is None:
        raise ValueError("no open lesson")
    if doc["status"] == "awaiting_assessment":
        return doc, "already awaiting assessment (no change)"
    _check_not_finalizing(doc)
    _transition(doc, "awaiting_assessment", _now(ts), "instruction done; independent assessment pending")
    _save(root, doc)
    return doc, "awaiting assessment"


# --------------------------------------------------------------------------
# notes captured during the lesson
# --------------------------------------------------------------------------

CLOSURE_KEYS = {"outcome", "summary", "handoff", "next_action", "competencies_covered", "next_focus"}
NOTE_KEYS = ("concepts_explained", "attempts", "misconceptions", "unresolved_questions")


def _merge_notes(doc: dict, patch: Any, program: dict) -> None:
    if not isinstance(patch, dict) or not patch or set(patch) - set(NOTE_KEYS):
        raise ValueError("notes file must be a mapping with keys from: " + ", ".join(NOTE_KEYS))
    comps = {c["id"] for c in program["competencies"]}
    notes = doc.setdefault("notes", {})
    for k in ("concepts_explained", "unresolved_questions"):
        for item in patch.get(k, []):
            if item not in notes.setdefault(k, []):
                notes[k].append(item)
    for att in patch.get("attempts", []):
        if att.get("objective") not in doc["objectives"]:
            raise ValueError(f"attempt objective {att.get('objective')!r} is not this lesson's objective {doc['objectives']}")
        if att not in notes.setdefault("attempts", []):
            notes["attempts"].append(att)
    for mc in patch.get("misconceptions", []):
        if mc.get("competency") not in comps:
            raise ValueError(f"misconception references unknown competency {mc.get('competency')!r}")
        cur = notes.setdefault("misconceptions", [])
        match = next((m for m in cur if m["text"] == mc.get("text") and m["competency"] == mc["competency"]), None)
        if mc.get("status") == "resolved":
            proof = any(a["assistance"] == "none" and a["result"] == "correct"
                        and a["objective"].split(":")[0] == mc["competency"] for a in notes.get("attempts", []))
            if not proof:
                raise ValueError("a misconception is resolved only after an independent (assistance: none) correct attempt "
                                 "on that competency; record the attempt first")
        if match:
            match["status"] = mc["status"]
        else:
            cur.append(dict(mc))
    if len(miniyaml.dumps(notes)) > 40000:
        raise ValueError("lesson notes are too large; summarise instead of transcribing")


def add_notes(root: Path, pid: str, patch: Any, ts: str | None = None) -> dict:
    doc = open_session(root, pid)
    if doc is None or doc["status"] == "planned":
        raise ValueError("notes can only be added to a started lesson (active, paused or awaiting_assessment)")
    _check_not_finalizing(doc)
    _merge_notes(doc, patch, _program(root, pid))
    doc["updated"] = _now(ts)
    _save(root, doc)
    return doc


# --------------------------------------------------------------------------
# closure
# --------------------------------------------------------------------------

def _assessment_refs(root: Path, pid: str, lesson: int) -> list[str]:
    events, _ = model.read_events(model.program_dir(root, pid) / "logs" / "assessments.jsonl")
    return [f"logs/assessments.jsonl:{e['_line']}" for e in events if e.get("lesson") == lesson]


def _slug(doc: dict) -> str:
    base = doc["objectives"][0].replace(":", "-")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", base.lower())).strip("-")[:40]


def _record_text(root: Path, doc: dict, today: str, objective_text: str) -> str:
    c, n = doc["closure"], doc.get("notes", {})
    meta: dict[str, Any] = {
        "schema_version": 1, "program": doc["program"], "lesson": doc["lesson"], "date": today,
        "title": f"Lesson {doc['lesson']}: {objective_text}"[:120], "outcome": c["outcome"],
        "competencies_covered": c.get("competencies_covered", []), "next_focus": c.get("next_focus", []),
        "session": doc["id"], "objectives": doc["objectives"], "assessment_status": c["assessment"]["status"],
    }
    if doc["curriculum"]["mode"] == "pinned":
        meta["curriculum_revision"] = doc["curriculum"]["revision"]
    hand = [c["handoff"], "", f"- Next action: {c['next_action']}"]
    open_mc = [m for m in n.get("misconceptions", []) if m["status"] == "open"]
    hand += [f"- Open misconception ({m['competency']}): {m['text']}" for m in open_mc]
    hand += [f"- Open question: {q}" for q in n.get("unresolved_questions", [])]
    if c["assessment"]["status"] == "not_assessed":
        hand.append("- Assessment: NOT assessed. Instruction is not evidence; no mastery is implied. Assess independently next.")
    else:
        hand.append("- Assessment events for this lesson: " + ", ".join(c["assessment"]["refs"]))
    body = [f"# Lesson {doc['lesson']}", "", "## Summary", "", c["summary"], "",
            f"Objective: `{doc['objectives'][0]}` ({doc['curriculum']['mode']} curriculum"
            + (f" r{doc['curriculum']['revision']}" if doc['curriculum']['mode'] == 'pinned' else "") + f"), selection: {doc['selection']['mode']}.", ""]
    if n.get("concepts_explained"):
        body += ["Concepts explained: " + "; ".join(n["concepts_explained"]), ""]
    if n.get("attempts"):
        body += ["Learner attempts (assistance recorded; assisted is not independent):", ""]
        body += [f"- {a['task']} -> {a['result']}, assistance {a['assistance']}" + (f" ({a['note']})" if a.get("note") else "")
                 for a in n["attempts"]] + [""]
    body += ["## Handoff", ""] + hand + [""]
    return "---\n" + miniyaml.dumps(meta) + "---\n\n" + "\n".join(body)


def _closure_from(root: Path, doc: dict, patch: dict | None, outcome_default: str, reason: str | None) -> dict:
    prev = doc.get("closure", {})
    patch = patch or {}
    obj_comp = [r.split(":")[0] for r in doc["objectives"]]
    outcome = patch.get("outcome", prev.get("outcome", outcome_default))
    refs = _assessment_refs(root, doc["program"], doc["lesson"])
    closure: dict[str, Any] = {
        "outcome": outcome,
        "summary": patch.get("summary", prev.get("summary")),
        "handoff": patch.get("handoff", prev.get("handoff")),
        "next_action": patch.get("next_action", prev.get("next_action")),
        "competencies_covered": patch.get("competencies_covered", prev.get("competencies_covered",
                                                                           obj_comp if outcome == "completed" else [])),
        "next_focus": patch.get("next_focus", prev.get("next_focus", [])),
        "assessment": {"status": "logged" if refs else "not_assessed", "refs": refs},
    }
    if reason:
        closure["abandon_reason"] = reason
    return closure


def finish_lesson(root: Path, pid: str, patch: Any = None, *, outcome: str = "completed", abandon_reason: str | None = None,
                  today: str | None = None, ts: str | None = None) -> tuple[dict, str]:
    """Shared by complete (outcome completed|partial) and abandon (outcome abandoned). Crash-safe and idempotent.

    Order: (1) persist closure in the session, (2) create the immutable lesson record exclusively,
    (3) rebuild derived state, (4) mark the session terminal. Re-running resumes from wherever it stopped.
    """
    root = Path(root)
    doc = open_session(root, pid)
    if doc is None:
        done = [s for s in all_sessions(root, pid) if s["status"] in TERMINAL]
        if done:
            last = done[-1]
            if (outcome == "abandoned") == (last["closure"]["outcome"] == "abandoned"):
                return last, f"{last['id']} already {last['status']} (no change)"
        raise ValueError("no open lesson")
    if outcome == "abandoned":
        pass
    elif doc["status"] not in ("active", "awaiting_assessment") and "closure" not in doc:
        raise ValueError(f"invalid transition {doc['status']} -> completed for {doc['id']}; resume the lesson first")
    if patch is not None and not isinstance(patch, dict):
        raise ValueError("closure file must be a mapping")
    patch = dict(patch or {})
    extra = set(patch) - set(NOTE_KEYS) - CLOSURE_KEYS
    if extra:
        raise ValueError(f"unknown closure field(s) {sorted(extra)}; allowed: {sorted(CLOSURE_KEYS | set(NOTE_KEYS))}. "
                         "Mastery is never set here; it is derived from logged assessments.")
    notes_patch = {k: patch.pop(k) for k in NOTE_KEYS if k in patch}
    if "closure" in doc and (doc["closure"]["outcome"] == "abandoned") != (outcome == "abandoned"):
        raise ValueError(f"{doc['id']} is already closing as {doc['closure']['outcome']}; finish that first")
    program = _program(root, pid)
    if outcome == "abandoned":
        patch.setdefault("summary", f"Abandoned: {abandon_reason}")
        patch.setdefault("handoff", "Lesson abandoned before completion; no instructional claims are made.")
        patch.setdefault("next_action", "Re-plan the objective with `lesson next`.")
    closure = _closure_from(root, doc, patch, outcome, abandon_reason if outcome == "abandoned" else None)
    for k in ("summary", "handoff", "next_action"):
        if not closure.get(k):
            raise ValueError(f"closure needs `{k}` (provide it in the closure file)")
    if closure["outcome"] not in ("completed", "partial", "abandoned") or (closure["outcome"] == "abandoned") != (outcome == "abandoned"):
        raise ValueError("outcome must be completed or partial (use `lesson abandon` to abandon)")
    known = {c["id"] for c in program["competencies"]}
    for k in ("competencies_covered", "next_focus"):
        bad = [c for c in closure[k] if c not in known]
        if bad:
            raise ValueError(f"{k} references unknown competencies {bad}")
    ts = _now(ts)
    today = today or ts[:10]
    if notes_patch:
        _merge_notes(doc, notes_patch, program)
    doc["closure"] = closure
    doc["updated"] = ts
    obj_text = next((o["text"] for o in curriculum_view(root, pid, program)["objectives"] if o["ref"] == doc["objectives"][0]),
                    doc["objectives"][0])
    text = _record_text(root, doc, today, obj_text)
    meta, _ = miniyaml.split_frontmatter(text)
    rep = model.Report()
    if not model.check_schema(rep, "lesson record", meta, "lesson-record"):
        raise ValueError("; ".join(rep.errors))
    _save(root, doc)                                                      # (1)
    ldir = model.program_dir(root, pid) / "lessons"
    existing = sorted(ldir.glob(f"{doc['lesson']:03d}-*.md"))
    if existing:                                                          # resumed after a crash
        got, _ = miniyaml.split_frontmatter(existing[0].read_text("utf-8"))
        if got.get("session") != doc["id"]:
            raise ValueError(f"{existing[0].name} exists and does not belong to {doc['id']}; refusing to overwrite")
    else:
        path = ldir / f"{doc['lesson']:03d}-{_slug(doc)}.md"
        with path.open("x", encoding="utf-8") as fh:                      # (2) never overwrites
            fh.write(text)
    rb = model.rebuild(root, pid)                                         # (3)
    if not rb.ok:
        raise ValueError("lesson record written but validation failed (re-run to retry): " + "; ".join(rb.errors))
    _transition(doc, "abandoned" if closure["outcome"] == "abandoned" else "completed", ts, closure["outcome"])  # (4)
    _save(root, doc)
    return doc, ("abandoned" if closure["outcome"] == "abandoned" else f"completed ({closure['outcome']})")


def complete_lesson(root: Path, pid: str, patch: Any = None, **kw) -> tuple[dict, str]:
    return finish_lesson(root, pid, patch, outcome=kw.pop("outcome", "completed"), **kw)


def abandon_lesson(root: Path, pid: str, *, reason: str | None, confirm: bool, ts: str | None = None,
                   today: str | None = None) -> tuple[dict, str]:
    if not confirm:
        raise ValueError("abandoning needs explicit learner confirmation: ask the learner, then pass --confirm")
    if not reason:
        raise ValueError("abandoning needs --reason (the learner's words)")
    return finish_lesson(root, pid, None, outcome="abandoned", abandon_reason=reason, ts=ts, today=today)


# --------------------------------------------------------------------------
# status and context
# --------------------------------------------------------------------------

def status_text(root: Path, pid: str) -> str:
    sessions = all_sessions(root, pid)
    cur = open_session(root, pid)
    L = [f"# Lesson status: {pid}"]
    if cur:
        L += _session_lines(cur)
    else:
        L.append("No open lesson. Run `lesson next` for a recommendation or `lesson start` to begin.")
    done = [s for s in sessions if s["status"] in TERMINAL]
    if done:
        L += ["", "Closed lessons:"] + [f"- {s['id']} {s['status']} ({s['closure']['outcome']}; assessment "
                                        f"{s['closure']['assessment']['status']}): {s['objectives'][0]}" for s in done[-5:]]
    return "\n".join(L)


def _session_lines(s: dict) -> list[str]:
    L = [f"- {s['id']}: **{s['status']}** since {s['updated']} (created {s['created']})",
         f"- Objective: `{s['objectives'][0]}`; selection: {s['selection']['mode']} ({s['selection'].get('kind', '-')})",
         f"- Why: {s['selection']['reason']}"]
    if s["selection"].get("override"):
        o = s["selection"]["override"]
        L.append(f"- OVERRIDE of prerequisites {s['selection'].get('unmet_prerequisites')}: {o['rationale']} (learner: \"{o['statement']}\")")
    c = s["curriculum"]
    L.append("- Curriculum: " + (f"pinned r{c['revision']} sha256:{c['sha256'][:12]}" if c["mode"] == "pinned" else "legacy"))
    if s.get("provider"):
        L.append(f"- Conversation: {s['provider'].get('name', '?')} {s['provider'].get('thread_ref', '(no thread ref)')}")
    L.append("- History: " + " > ".join(f"{h['to']}" for h in s["history"][-6:]))
    return L


def _recent_events(root: Path, pid: str, comps: set[str], n: int) -> list[str]:
    events, _ = model.read_events(model.program_dir(root, pid) / "logs" / "assessments.jsonl")
    sel = [e for e in events if e["competency"] in comps][-n:]
    return [f"- `log:logs/assessments.jsonl:{e['_line']}` {e['ts'][:10]} lesson {e['lesson']} {e['competency']} "
            f"{e['kind']} score {e['score']}" + (f" ({e['notes']})" if e.get("notes") else "") for e in sel]


def open_misconceptions(sessions: list[dict], comps: list[str]) -> list[tuple[str, str, str]]:
    """Latest known status per (competency, text) across sessions; returns open ones, focus competency first."""
    latest: dict[tuple[str, str], tuple[str, str]] = {}
    for s in sessions:
        for m in s.get("notes", {}).get("misconceptions", []):
            latest[(m["competency"], m["text"])] = (m["status"], s["id"])
    out = [(c, t, sid) for (c, t), (st, sid) in latest.items() if st == "open" and c in comps]
    out.sort(key=lambda x: comps.index(x[0]))
    return out


class Block:
    """One section of the context pack with progressively smaller variants (index 0 = fullest)."""

    def __init__(self, key: str, *variants: str, required: bool = False):
        self.key, self.variants, self.required, self.level = key, [v for v in variants], required, 0

    @property
    def text(self) -> str:
        return self.variants[self.level]

    def shrink(self) -> bool:
        if self.required or self.level >= len(self.variants) - 1:
            return False
        self.level += 1
        return True


SHRINK_ORDER = ("suggested", "events", "handoff", "misconceptions", "resources", "snapshot")


def assemble(blocks: list[Block], max_chars: int) -> str:
    """Shrink optional blocks in a fixed order until the pack fits. Never cuts mid-text; says what was dropped."""
    omitted: list[str] = []
    def total() -> int:
        return sum(len(b.text) + 1 for b in blocks if b.text)
    for key in SHRINK_ORDER:
        for b in blocks:
            while total() > max_chars and b.key == key and b.shrink():
                omitted.append(f"{b.key} reduced")
    out = "\n".join(b.text for b in blocks if b.text)
    notes = sorted(set(omitted))
    if notes:
        out += "\n\n> Size limit: " + "; ".join(notes) + f" (limit {max_chars} chars). Raise it with `context --max-chars N`."
    if len(out) > max_chars:
        out += (f"\n\n> WARNING: required content is {len(out)} chars, above the limit {max_chars}. Nothing required was cut; "
                "raise the limit or shorten the lesson notes.")
    return out


def lesson_blocks(root: Path, pid: str, program: dict, today: date, objective: str | None) -> dict:
    """Lesson-specific context. Returns {focus_comps, blocks (key -> Block), lines...}."""
    sessions = all_sessions(root, pid)
    cur = open_session(root, pid)
    try:
        rec = recommend(root, pid)
        view, mastery, states = rec["view"], rec["mastery"], rec["states"]
        err = None
    except ValueError as exc:
        rec, view, mastery, states, err = None, None, _mastery(root, pid), [], str(exc)
    ref = objective or (cur["objectives"][0] if cur else (rec["pick"]["ref"] if rec and rec["pick"] else None))
    focus = next((s for s in states if s["ref"] == ref), None)
    if view and view["mode"] == "legacy" and not cur and not objective:
        focus = None  # competency-level programs keep the full snapshot until a lesson is actually open
    out: dict[str, Any] = {"focus": focus, "view": view, "cur": cur, "rec": rec, "err": err, "blocks": {}}
    B = out["blocks"]
    L = ["## Lesson", ""]
    if cur:
        L += ["Open lesson (resume it; do not start another):"] + _session_lines(cur)
    elif rec and rec["pick"] and not objective:
        L += ["No open lesson. Recommended next objective (not yet started; start it only after the learner agrees):", "",
              f"- `{rec['pick']['ref']}` ({rec['pick']['kind']}): {rec['pick']['text']}", f"- Why: {rec['reason']}"]
        L += [f"- Blocker: {b}" for b in rec["blockers"]]
    elif err:
        L += [f"Cannot plan a lesson: {err}"]
    elif rec:
        L += ["No open lesson."] + [f"- Blocker: {b}" for b in rec["blockers"]]
    if objective and focus:
        L += ["", f"Objective under discussion: `{objective}`" + ("; prerequisites NOT demonstrated: " + ", ".join(focus["unmet"]) if focus["unmet"] else "")]
    B["lesson"] = Block("lesson", "\n".join(L) + "\n", required=True)
    if focus:
        cid = focus["competency"]
        comps = view["comps"]
        rel = [cid] + [p for p in comps[cid]["prerequisites"]]
        rows = ["## Competency snapshot (focus and prerequisites only)", "",
                "| id | title | status | score | evidence | prerequisites |", "|---|---|---|---|---|---|"]
        for c in rel:
            m = mastery[c]
            rows.append(f"| {c} | {comps[c]['title']} | {m['status']} | {m['score']} | {m['evidence_count']} | "
                        f"{', '.join(comps[c]['prerequisites']) or '-'} |")
        rest = len(comps) - len(rel)
        rows.append(f"\n{rest} other competenc{'y' if rest == 1 else 'ies'} omitted as irrelevant to this lesson.")
        B["snapshot"] = Block("snapshot", "\n".join(rows) + "\n", "## Competency snapshot\n(table omitted for size)\n")
        ev = _recent_events(root, pid, set(rel), 6)
        two = _recent_events(root, pid, set(rel), 2)
        hdr = ["## Observed evidence (assessment log; authoritative)", "",
               "Mastery comes only from these events. Self-report and tutoring are not evidence.", ""]
        B["events"] = Block("events", "\n".join(hdr + (ev or ["(no assessment events for these competencies)"])) + "\n",
                            "\n".join(hdr + (two or ["(none)"]) + ["(older events omitted)"]) + "\n")
        mcs = open_misconceptions(sessions, rel)
        def mc_block(k):
            shown = mcs[:k]
            body = [f"- [{c}] {t} (`session:{sid}`)" for c, t, sid in shown] or ["(none recorded)"]
            if len(mcs) > k:
                body.append(f"({len(mcs) - k} more open misconception(s) omitted)")
            return "\n".join(["## Open misconceptions (tutor-observed in dialogue; interpretation, re-test before trusting)", ""] + body) + "\n"
        B["misconceptions"] = Block("misconceptions", mc_block(MISCONCEPTION_CAP), mc_block(1), mc_block(0))
        # self-reported / interpretation
        interp = ["## Self-reported and interpretation (NOT evidence of mastery)", ""]
        dec = view["decisions"].get(cid)
        if dec:
            interp.append(f"- Curriculum decision for `{cid}`: {dec['disposition']}: {dec['rationale']} "
                          f"[evidence kinds: {', '.join(sorted({e['kind'] for e in dec['evidence']}))}]")
        spec = program.get("spec", {}).get("profile", {})
        for x in spec.get("prior_experience", [])[:2]:
            interp.append(f"- Learner-reported experience: {x}")
        if len(interp) == 2:
            interp.append("(none)")
        B["interpretation"] = Block("interpretation", "\n".join(interp) + "\n", required=True)
        # resources
        reg = _registry_status(root, pid)
        res = ["## Learning resources for this objective", ""]
        usable, shaky = [], []
        for r in focus["resources"]:
            st = reg.get(r["source"], "unknown")
            (usable if st in design.INSPECTED else shaky).append((r, st))
        res += [f"- `registry:{r['source']}` ({r['use']}, {st})" for r, st in usable]
        res += [f"- `registry:{r['source']}` ({r['use']}) UNINSPECTED/{st}: do not present its content as established" for r, st in shaky]
        if not usable:
            res.append("No inspected resource is attached: teach from the objective and criteria below, say so to the learner, "
                       "and ask before using anything unverified.")
        B["resources"] = Block("resources", "\n".join(res) + "\n", "\n".join(res[:2] + [f"({len(usable)} inspected, {len(shaky)} uninspected; details omitted)"]) + "\n")
        # objective detail
        det = ["## Current objective", "", f"- `objective:{focus['ref']}`: {focus['text']}", f"- Competency `competency:{cid}`: {comps[cid]['description']}"]
        det += [f"- Success criterion: {c}" for c in focus["criteria"]]
        det += [f"- Planned exercise: {e}" for e in focus["exercises"]]
        if view["mode"] == "pinned":
            det.append(f"- Curriculum `curriculum:{pid}@r{view['revision']}#{view['sha256'][:8]}`, module `{focus['module']}`")
        B["objective"] = Block("objective", "\n".join(det) + "\n", required=True)
    if cur:
        n = cur.get("notes", {})
        prog = ["## Progress so far in this lesson (tutor notes; interpretation)", ""]
        att = n.get("attempts", [])
        prog += [f"- Attempt: {a['task']} -> {a['result']}, assistance {a['assistance']}" for a in att[-5:]]
        if len(att) > 5:
            prog.append(f"({len(att) - 5} earlier attempt(s) omitted)")
        prog += [f"- Explained: {c}" for c in n.get("concepts_explained", [])[-5:]]
        prog += [f"- Open question: {q}" for q in n.get("unresolved_questions", [])]
        if len(prog) == 2:
            prog.append("(nothing recorded yet; start at step 1 of the lesson flow)")
        B["progress"] = Block("progress", "\n".join(prog) + "\n", required=True)
    prev_done = [s for s in sessions if s["status"] in TERMINAL and s.get("closure")]
    if prev_done:
        p = prev_done[-1]
        B["prev_next"] = Block("prev_next", f"Previous lesson (`session:{p['id']}`, {p['closure']['outcome']}, assessment "
                               f"{p['closure']['assessment']['status']}) recommended next: {p['closure']['next_action']}\n")
    return out


# --------------------------------------------------------------------------
# validation hook (called from model.validate_root, per program)
# --------------------------------------------------------------------------

def validate_program(root: Path, pid: str, report: model.Report) -> None:
    sdir = sessions_dir(root, pid)
    if not sdir.is_dir():
        return
    base = f"programs/{pid}/sessions"
    pdir = model.program_dir(root, pid)
    lessons, _ = model.read_lessons(pdir)
    records = {r["file_number"]: r for r in lessons}
    prog = miniyaml.loads((pdir / "program.yaml").read_text("utf-8"))
    known = {c["id"] for c in prog.get("competencies", [])}
    opens = []
    for p in sorted(sdir.iterdir()):
        if p.name.startswith(".tmp-"):
            report.warn(f"{base}/{p.name}", "leftover temporary file from an interrupted write; safe to delete")
            continue
        m = SESSION_RE.match(p.name)
        if not m:
            report.error(base, f"unexpected file {p.name!r} (sessions are NNN.yaml)")
            continue
        where = f"{base}/{p.name}"
        try:
            doc = _read(p)
        except ValueError as exc:
            report.error(where, str(exc))
            continue
        n = int(m.group(1))
        if doc["program"] != pid or doc["lesson"] != n or doc["id"] != f"lesson-{n:03d}":
            report.error(where, "id/program/lesson do not match the file name or directory")
        rec = records.get(n)
        status = doc["status"]
        if status in OPEN:
            opens.append(doc["id"])
            if rec is not None:
                report.error(where, f"is {status} but lessons/{rec['file']} already exists (interrupted close); "
                                    "re-run `lesson complete` or `lesson abandon` to finish it")
            elif n != max(records, default=0) + 1:
                report.error(where, f"open lesson number {n} is not the next lesson number")
            for ref in doc["objectives"]:
                if ref.split(":")[0] not in known:
                    report.error(where, f"objective {ref} references an unknown competency")
        else:
            if "closure" not in doc:
                report.error(where, f"is {status} without a closure")
            elif rec is None:
                report.error(where, f"is {status} but lessons/{n:03d}-*.md is missing")
            else:
                if rec["meta"].get("session") != doc["id"]:
                    report.error(where, "lesson record does not point back at this session")
                if rec["meta"]["outcome"] != doc["closure"]["outcome"]:
                    report.error(where, f"closure outcome {doc['closure']['outcome']!r} differs from the lesson record's")
        if doc["curriculum"]["mode"] == "pinned":
            try:
                snap = design.load_snapshot(root, pid, doc["curriculum"]["revision"])
                if design.content_hash(snap) != doc["curriculum"]["sha256"]:
                    report.error(where, "pinned curriculum snapshot changed since the lesson was planned")
            except ValueError as exc:
                report.error(where, f"pinned curriculum unavailable: {exc}")
    if len(opens) > 1:
        report.error(base, f"more than one open lesson: {', '.join(opens)}")
