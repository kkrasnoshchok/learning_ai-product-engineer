"""Spaced-repetition queue, review sessions, review/lesson context blocks and the progress report.

The schedule itself is derived in evidence.derive_reviews (a pure function of the assessment log). This module only
asks "what is due on <today>?", applies the daily workload limit, and manages review sessions
(programs/<id>/reviews/NNN.yaml), which are separate from lesson sessions and never consume a lesson number.

The scheduler is a simple, explainable interval ladder. It is not claimed to be optimal.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import assessment, evidence, miniyaml, model

TIERS = ("failed", "prerequisite-critical", "overdue", "due")
RS_RE = re.compile(r"^(\d{3})\.yaml$")
DEMONSTRATED = ("proficient", "mastered")


class Conflict(ValueError):
    pass


# --------------------------------------------------------------------------
# paths and IO
# --------------------------------------------------------------------------

def rdir(root: Path, pid: str) -> Path:
    return model.program_dir(root, pid) / "reviews"


def _read(path: Path) -> dict:
    try:
        doc = miniyaml.loads(path.read_text("utf-8"))
    except (miniyaml.YamlError, UnicodeDecodeError) as exc:
        raise ValueError(f"{path.name}: cannot parse YAML: {exc}")
    rep = model.Report()
    if not model.check_schema(rep, path.name, doc, "review-session"):
        raise ValueError("; ".join(rep.errors))
    return doc


def load(root: Path, pid: str, rid: str) -> dict:
    m = re.fullmatch(r"review-(\d{3})", rid)
    path = rdir(root, pid) / f"{m.group(1)}.yaml" if m else None
    if path is None or not path.is_file():
        raise ValueError(f"no review session {rid} in {pid}")
    return _read(path)


def all_sessions(root: Path, pid: str) -> list[dict]:
    d = rdir(root, pid)
    return [_read(p) for p in sorted(d.iterdir()) if RS_RE.match(p.name)] if d.is_dir() else []


def open_session(root: Path, pid: str) -> dict | None:
    opens = [s for s in all_sessions(root, pid) if s["status"] == "open"]
    if len(opens) > 1:
        raise ValueError(f"{len(opens)} open review sessions found; abandon all but one (state is inconsistent)")
    return opens[0] if opens else None


def _save(root: Path, doc: dict) -> None:
    rep = model.Report()
    if not model.check_schema(rep, doc["id"], doc, "review-session"):
        raise ValueError("refusing to write an invalid review session: " + "; ".join(rep.errors))
    model.atomic_write(rdir(root, doc["program"]) / f"{doc['number']:03d}.yaml", miniyaml.dumps(doc))


def _now(ts: str | None) -> str:
    return ts or model.now_ts()


# --------------------------------------------------------------------------
# the queue
# --------------------------------------------------------------------------

def _load(root: Path, pid: str) -> tuple[dict, list[dict], dict, dict]:
    program = model._load_valid_program(root, pid)
    pdir = model.program_dir(root, pid)
    events, errs = model.read_events(pdir / "logs" / "assessments.jsonl")
    if errs:
        raise ValueError("assessment log is invalid: " + "; ".join(errs))
    return program, events, evidence.derive_evidence(program, events, model._lesson_records(pdir)), evidence.derive_mastery(program, events)


def _objective_for(root: Path, pid: str, program: dict, events: list[dict], cid: str) -> str:
    refs = [r for r in sorted(assessment.objective_refs(root, pid, program)) if r.split(":")[0] == cid]
    if not refs:
        return f"{cid}:overall"
    last = {r: "" for r in refs}
    for e in events:
        if e.get("objective") in last and evidence.counts(e):
            last[e["objective"]] = e["ts"]
    return min(refs, key=lambda r: (last[r], r))  # the objective evidenced least recently


def budget(program: dict) -> int:
    rp = evidence.review_policy(program)
    return max(1, min(rp["max_per_day"], program["lesson_policy"]["target_minutes"] // rp["minutes_per_item"]))


def queue(root: Path, pid: str, today: date | None = None) -> dict:
    """Prioritized due reviews. Writes nothing. Returns {entries, shown, deferred, assigned, scheduled, cap, remaining}."""
    today = today or date.today()
    program, events, ev_state, mastery = _load(root, pid)
    order = [c["id"] for c in program["competencies"]]
    comps = {c["id"]: c for c in program["competencies"]}
    blocked_by: dict[str, list[str]] = {}
    for cid in order:
        if mastery["competencies"][cid]["status"] not in DEMONSTRATED:
            for p in comps[cid]["prerequisites"]:
                blocked_by.setdefault(p, []).append(cid)
    sessions = all_sessions(root, pid)
    assigned = {i["competency"] for s in sessions if s["status"] == "open" for i in s["items"] if "skipped" not in i}
    entries = []
    for cid in order:
        s = ev_state["reviews"].get(cid)
        if not s or date.fromisoformat(s["due"]) > today:
            continue
        over = (today - date.fromisoformat(s["due"])).days
        if s["last_result"] == "failed":
            tier, why = "failed", "the last independent retrieval failed"
        elif blocked_by.get(cid):
            tier, why = "prerequisite-critical", "it is a prerequisite of " + ", ".join(blocked_by[cid][:3]) + " (not yet demonstrated)"
        elif over > 0:
            tier, why = "overdue", f"overdue by {over} day(s)"
        else:
            tier, why = "due", "due today"
        extra = f"; MISSED: a full {s['interval_days']}-day interval passed without a review" if over >= s["interval_days"] else ""
        entries.append({"competency": cid, "tier": tier, "due": s["due"], "overdue_days": over, "assigned": cid in assigned,
                        "reason": f"{why}. Schedule: {s['reason']}{extra}"[:500], "stage": s["stage"]})
    entries.sort(key=lambda e: (TIERS.index(e["tier"]), -e["overdue_days"], order.index(e["competency"])))
    cap = budget(program)
    todays = [s for s in sessions if s["status"] != "abandoned" and s["today"] == today.isoformat()]
    used = sum(len(s["items"]) for s in todays)  # assigned work counts against the day, even if later skipped
    skipped_today = {i["competency"] for s in todays for i in s["items"] if "skipped" in i}
    remaining = max(0, cap - used)
    free = [e for e in entries if not e["assigned"] and e["competency"] not in skipped_today]
    for e in free[:remaining]:
        e["objective"] = _objective_for(root, pid, program, events, e["competency"])
    return {"entries": entries, "shown": free[:remaining], "deferred": free[remaining:], "assigned": sorted(assigned),
            "scheduled": len(ev_state["reviews"]), "cap": cap, "remaining": remaining}


def format_queue(q: dict, today: date) -> str:
    L = [f"# Reviews due on {today.isoformat()}", "",
         f"{len(q['entries'])} due or overdue of {q['scheduled']} scheduled; daily limit {q['cap']} ({q['remaining']} left today)."]
    if q["assigned"]:
        L.append(f"Already in an open review session: {', '.join(q['assigned'])}.")
    if not q["shown"]:
        L += ["", "Nothing to assign now." + (f" {len(q['deferred'])} deferred by the daily limit." if q["deferred"] else "")]
    for i, e in enumerate(q["shown"], 1):
        L.append(f"{i}. `{e['competency']}` [{e['tier']}] {e['reason']}")
    if q["deferred"]:
        L += ["", f"Deferred by the daily limit: {', '.join(e['competency'] for e in q['deferred'])}"]
    return "\n".join(L)


# --------------------------------------------------------------------------
# review session lifecycle
# --------------------------------------------------------------------------

def start(root: Path, pid: str, *, today: date | None = None, provider: str | None = None, thread: str | None = None,
          ts: str | None = None) -> tuple[dict, str]:
    today = today or date.today()
    with model.program_lock(root, pid):
        cur = open_session(root, pid)
        if cur is not None:
            return cur, f"{cur['id']} is already open; resuming it (no new review assigned)"
        q = queue(root, pid, today)
        if not q["shown"]:
            raise ValueError("no reviews to assign today" + (f" ({len(q['deferred'])} deferred by the daily limit)" if q["deferred"] else "")
                             + "; use `lesson next` or `assess` instead")
        nums = [int(RS_RE.match(p.name).group(1)) for p in rdir(root, pid).glob("*.yaml") if RS_RE.match(p.name)] if rdir(root, pid).is_dir() else []
        n, now = max(nums, default=0) + 1, _now(ts)
        doc: dict[str, Any] = {
            "schema_version": 1, "id": f"review-{n:03d}", "program": pid, "number": n, "status": "open", "created": now,
            "updated": now, "today": today.isoformat(),
            "items": [{"competency": e["competency"], "objective": e["objective"], "tier": e["tier"], "reason": e["reason"], "due": e["due"]}
                      for e in q["shown"]],
            "history": [{"ts": now, "to": "open"}]}
        if provider:
            doc["provider"] = {"name": provider, **({"thread_ref": thread} if thread else {})}
        _save(root, doc)
    return doc, f"{doc['id']} started with {len(doc['items'])} review item(s)"


def link(root: Path, pid: str, rid: str, competency: str, aid: str, ts: str | None = None) -> None:
    with model.program_lock(root, pid):
        rs = load(root, pid, rid)
        item = next((i for i in rs["items"] if i["competency"] == competency), None)
        if item is None:
            raise ValueError(f"{rid} has no review item for {competency!r}")
        cur = item.get("assessment_id")
        if cur and cur != aid:
            try:
                state = assessment.load_task(root, pid, cur)["status"]
            except ValueError:
                state = "void"
            if state != "void":
                raise Conflict(f"{competency} in {rid} is already assigned to {cur} ({state}); no duplicate review assignment")
        item["assessment_id"] = aid
        item.pop("skipped", None)
        rs["updated"] = _now(ts)
        _save(root, rs)


def item_state(root: Path, pid: str, item: dict) -> str:
    if "skipped" in item:
        return "skipped"
    if "assessment_id" not in item:
        return "needs-task"
    try:
        st = assessment.load_task(root, pid, item["assessment_id"])["status"]
    except ValueError:
        return "needs-task"
    return "needs-task" if st == "void" else st


def skip(root: Path, pid: str, competency: str, reason: str, ts: str | None = None) -> dict:
    if not reason:
        raise ValueError("skipping a review needs --reason")
    with model.program_lock(root, pid):
        rs = open_session(root, pid)
        if rs is None:
            raise ValueError("no open review session")
        item = next((i for i in rs["items"] if i["competency"] == competency), None)
        if item is None:
            raise ValueError(f"no review item for {competency!r}")
        if item_state(root, pid, item) == "committed":
            raise ValueError("that review is already committed")
        item["skipped"] = reason[:300]
        rs["updated"] = _now(ts)
        _save(root, rs)
    return rs


def _events_by_aid(root: Path, pid: str) -> dict[str, dict]:
    evs, _ = model.read_events(model.program_dir(root, pid) / "logs" / "assessments.jsonl")
    return {e["assessment_id"]: e for e in evs if "assessment_id" in e}


def summarize(root: Path, pid: str, rs: dict) -> str:
    program, _, ev_state, _ = _load(root, pid)
    by = _events_by_aid(root, pid)
    pass_t = program["mastery_policy"]["proficient_threshold"]
    L, ok, bad, assisted, skipped = [], 0, 0, 0, 0
    for i in rs["items"]:
        c = i["competency"]
        if "skipped" in i:
            skipped += 1
            L.append(f"{c}: skipped ({i['skipped']})")
            continue
        e = by.get(i.get("assessment_id", ""))
        if e is None:
            L.append(f"{c}: not assessed")
            continue
        if e.get("independence") == "assisted":
            assisted += 1
            L.append(f"{c}: assisted attempt, score {e['score']} (not independent; stays due)")
        elif e["score"] >= pass_t:
            ok += 1
            nxt = ev_state["reviews"].get(c, {}).get("due")
            L.append(f"{c}: passed independently, score {e['score']}; next review {nxt}")
        else:
            bad += 1
            nxt = ev_state["reviews"].get(c, {}).get("due")
            L.append(f"{c}: failed, score {e['score']}; retry {nxt}")
    head = f"{len(rs['items'])} item(s): {ok} passed independently, {bad} failed, {assisted} assisted, {skipped} skipped."
    return (head + " " + " | ".join(L))[:2000]


def complete(root: Path, pid: str, ts: str | None = None) -> tuple[dict, str]:
    with model.program_lock(root, pid):
        rs = open_session(root, pid)
        if rs is None:
            done = [s for s in all_sessions(root, pid) if s["status"] == "completed"]
            if done:
                return done[-1], f"{done[-1]['id']} already completed (no change)"
            raise ValueError("no open review session")
        pending = [i["competency"] for i in rs["items"] if item_state(root, pid, i) not in ("committed", "skipped")]
        if pending:
            raise ValueError("review items not finished (commit their assessments or `review skip`): " + ", ".join(pending))
        now = _now(ts)
        rs["summary"] = summarize(root, pid, rs)
        rs["status"], rs["updated"] = "completed", now
        rs["history"].append({"ts": now, "to": "completed"})
        _save(root, rs)
    return rs, f"{rs['id']} completed"


def abandon(root: Path, pid: str, *, reason: str | None, confirm: bool, ts: str | None = None) -> tuple[dict, str]:
    if not confirm or not reason:
        raise ValueError("abandoning a review session needs --reason and --confirm (after the learner agreed)")
    with model.program_lock(root, pid):
        rs = open_session(root, pid)
        if rs is None:
            raise ValueError("no open review session")
        for i in rs["items"]:
            if item_state(root, pid, i) in ("issued", "submitted", "graded", "needs_review"):
                raise ValueError(f"{i['assessment_id']} is mid-flight; commit or void it first")
        now = _now(ts)
        rs["status"], rs["updated"], rs["abandon_reason"] = "abandoned", now, reason[:300]
        rs["history"].append({"ts": now, "to": "abandoned", "note": reason[:300]})
        _save(root, rs)
    return rs, f"{rs['id']} abandoned"


def status_text(root: Path, pid: str) -> str:
    rs = open_session(root, pid)
    if rs is None:
        done = all_sessions(root, pid)
        return f"No open review session. {len(done)} earlier session(s)." + (f"\nLast: {done[-1]['id']} {done[-1]['status']}: {done[-1].get('summary', '')}" if done else "")
    L = [f"# {rs['id']} (open, queue for {rs['today']})", ""]
    for i in rs["items"]:
        st = item_state(root, pid, i)
        nxt = {"needs-task": "Examiner writes a task, then `assess create`", "issued": "learner answers independently", "submitted": "grade it",
               "graded": "`assess commit`", "needs_review": "human review", "committed": "done", "skipped": "skipped"}[st]
        L.append(f"- `{i['competency']}` [{i['tier']}] {st}" + (f" ({i.get('assessment_id')})" if i.get("assessment_id") else "") + f": {nxt}")
    return "\n".join(L)


# --------------------------------------------------------------------------
# review briefing (the whole context of a fresh review conversation)
# --------------------------------------------------------------------------

def brief(root: Path, pid: str, max_chars: int | None = None) -> str:
    from . import lifecycle
    rs = open_session(root, pid)
    if rs is None:
        raise ValueError("no open review session; use `review start`")
    rep = model.validate_program(root, pid)
    if not rep.ok:
        raise ValueError("program does not validate; fix first:\n  " + "\n  ".join(rep.errors))
    program, events, ev_state, mastery = _load(root, pid)
    view = None
    try:
        view = lifecycle.curriculum_view(root, pid, program)
    except ValueError:
        pass
    obj_info = {o["ref"]: o for o in view["objectives"]} if view else {}
    tasks = assessment.all_tasks(root, pid)
    limit = max_chars or program["lesson_policy"].get("context_max_chars") or lifecycle.DEFAULT_MAX_CHARS
    head = [f"# Review context pack: {program['title']} (`program:{pid}`, `{rs['id']}`)", "",
            f"Generated from program files only for the queue of {rs['today']}. It contains no earlier conversation and no private answer keys.", "",
            "## Rules for this conversation", "",
            "- This is a RETRIEVAL session, not a lesson: do not teach new material and do not start a lesson.",
            "- Roles: the Examiner writes each task and rubric (a subagent that has not seen tutoring); you, the Tutor, persist and present.",
            "  Do NOT show the rubric or any answer before the learner submits. Prefer objective checks (`exact`/`regex`/`number`).",
            "- Each attempt is independent: no hints, no notes. If help is given, record it with `assess hint`; it then does not count.",
            "- Never invent mastery. Only `assess commit` creates evidence. Follow `engine/protocol/09-assessment-and-review.md`.", "",
            "## Items", ""]
    blocks = []
    for i in rs["items"]:
        c = i["competency"]
        cd = next(x for x in program["competencies"] if x["id"] == c)
        st = item_state(root, pid, i)
        L = [f"### `{c}` [{i['tier']}] state: {st}" + (f" ({i['assessment_id']})" if i.get("assessment_id") else ""),
             f"- Why now: {i['reason']}", f"- Definition: {cd['description']}",
             f"- Objective to test: `{i['objective']}`" + (f": {obj_info[i['objective']]['text']}" if i["objective"] in obj_info else "")]
        for crit in obj_info.get(i["objective"], {}).get("criteria", [])[:3]:
            L.append(f"  - success criterion: {crit}")
        m = mastery["competencies"][c]
        e = ev_state["competencies"][c]
        L.append(f"- Status {m['status']}, score {m['score']}; evidence level {e['level']} (valid {e['valid']}, unverified {e['unverified']}, assisted {e['assisted']})")
        recent = [x for x in events if x["competency"] == c][-2:]
        for x in recent:
            L.append(f"- Previous: {x['ts'][:10]} {x.get('type', x['kind'])} score {x['score']} "
                     f"({x.get('independence', 'unclassified legacy')})")
        for mid, mc in ev_state["misconceptions"].items():
            if mc["competency"] == c and mc["status"] != "resolved":
                rec = f", recurred {mc['recurrences']}x" if mc["recurrences"] else ""
                L.append(f"- Probe misconception [{mc['status']}{rec}]: {mc['text']}")
        used = [t for t in tasks if t["competency"] == c and t["status"] != "void"]
        if used:
            L.append("- Items already used (do not reuse): " + "; ".join(f"{t['title']} ({t['type']})" for t in used[-4:]))
        L.append("")
        blocks.append(lifecycle.Block(f"item-{c}", "\n".join(L) + "\n", "\n".join(L[:2] + L[-3:]) + "\n"))
    steps = ["## Steps", "", "1. Per pending item ask the Examiner (subagent `examiner`) for ONE task with a private rubric (Mode A in `engine/roles/examiner.md`).",
             f"2. Save its draft as YAML and run `python3 scripts/los.py assess create {pid} --file <draft> --review {rs['id']}`; show the learner ONLY `assess show`.",
             "3. After the learner answers: `assess submit`, then `assess brief` for the Examiner, then `assess grade --file <grading>`.",
             "   Low confidence or an ambiguous result goes to `assess review --confirm` before `assess commit`.",
             f"4. Skip an item only with the learner's reason: `review skip {pid} --competency <id> --reason ...`.",
             f"5. When every item is committed or skipped: `review complete {pid}`, give the learner its concise summary, and end the session.", ""]
    pack = lifecycle.assemble([lifecycle.Block("head", "\n".join(head), required=True), *blocks,
                               lifecycle.Block("steps", "\n".join(steps), required=True)], limit)
    return pack + "\n"


# --------------------------------------------------------------------------
# context blocks for lesson packs
# --------------------------------------------------------------------------

def context_blocks(root: Path, pid: str, program: dict, today: date, focus: list[str]) -> list:
    from . import lifecycle
    B = lifecycle.Block
    try:
        _, events, ev_state, mastery = _load(root, pid)
        q = queue(root, pid, today)
    except ValueError:
        return []
    out = []
    if q["entries"]:
        full = ["## Reviews due (spaced repetition; derived from the assessment log)", "",
                f"{len(q['entries'])} due/overdue; daily limit {q['cap']}. A separate review session handles them (`review start`); "
                "in a lesson, prefer interleaving at most one as retrieval practice.", ""]
        full += [f"- `{e['competency']}` [{e['tier']}] {e['reason']}" for e in q["entries"][:3]]
        if len(q["entries"]) > 3:
            full.append(f"({len(q['entries']) - 3} more omitted)")
        small = full[:3] + [f"(details omitted for size; top: `{q['entries'][0]['competency']}` [{q['entries'][0]['tier']}])"]
        out.append(B("reviews", "\n".join(full) + "\n", "\n".join(small) + "\n"))
    scope = set(focus) or set(ev_state["competencies"])
    weak = [(c, m) for c, m in mastery["competencies"].items()
            if c in scope and m["evidence_count"] and m["status"] == "learning"]
    mcs = [(mid, m) for mid, m in ev_state["misconceptions"].items() if m["competency"] in scope and m["status"] != "resolved"]
    mcs.sort(key=lambda x: (-(x[1]["recurrences"] + (x[1]["demonstrated"] > 1)), x[1]["status"] != "demonstrated", x[0]))
    if weak or mcs:
        def block(k: int) -> str:
            L = ["## Weak competencies and evidence-backed misconceptions", ""]
            L += [f"- weak: `{c}` score {m['score']} on {m['evidence_count']} counted event(s)" for c, m in weak[:k]]
            for mid, m in mcs[:k]:
                rec = f", recurring ({m['recurrences']} return(s))" if m["recurrences"] else (", repeated" if m["demonstrated"] > 1 else "")
                L.append(f"- [{m['competency']}] {m['status']}{rec}: {m['text']} (`{m['evidence'][-1] if m['evidence'] else '-'}`)")
            if len(weak) > k or len(mcs) > k:
                L.append("(more omitted)")
            return "\n".join(L) + "\n"
        out.append(B("gaps", block(4), block(1), "## Weak competencies and evidence-backed misconceptions\n(omitted for size)\n"))
    cur = lifecycle.open_session(root, pid)
    mine = [t for t in assessment.open_tasks(root, pid) if cur and t.get("lesson") == cur["lesson"]]
    L = ["## Assessment requirements", "",
         "Mastery needs independent, rubric-backed assessments (`assess create`/`submit`/`grade`/`commit`, protocol 09); "
         "free-form `log` events are \"unverified\" and cannot earn `mastered` in a strict program."]
    L += [f"- open: `{t['id']}` {t['type']} on `{t['competency']}` is {t['status']}" for t in mine]
    out.append(B("assessment", "\n".join(L) + "\n", required=True))
    return out
# --------------------------------------------------------------------------
# progress report
# --------------------------------------------------------------------------

def progress_text(root: Path, pid: str, today: date | None = None) -> str:
    from . import lifecycle
    today = today or date.today()
    program, events, ev_state, mastery = _load(root, pid)
    comps = ev_state["competencies"]
    n = len(comps)
    pass_t = program["mastery_policy"]["proficient_threshold"]
    by_level = {k: sum(1 for c in comps.values() if c["level"] == k) for k in ("unseen", "exposure", "assisted", "independent", "retained")}
    by_status = {k: sum(1 for c in mastery["competencies"].values() if c["status"] == k) for k in ("unseen", "learning", "proficient", "mastered")}
    indep = [e for e in events if evidence.counts(e)]
    structured = [e for e in events if "independence" in e]
    q = queue(root, pid, today)
    sched = ev_state["reviews"]
    delayed = [e for e in events if e.get("type") == "delayed_review" and evidence.counts(e)]
    mode = evidence.evidence_policy(program)["mode"]
    L = [f"# Learning progress: {program['title']} (`{pid}`, {today.isoformat()})", "", "## Measured facts (from logs/assessments.jsonl and lesson records)", ""]
    L.append(f"- Coverage: {n} competencies. Evidence level: {by_level['retained']} retained, {by_level['independent']} independent, "
             f"{by_level['assisted']} assisted only, {by_level['exposure']} exposure only, {by_level['unseen']} unseen.")
    L.append(f"- Status: {by_status['mastered']} mastered, {by_status['proficient']} proficient, {by_status['learning']} learning, "
             f"{by_status['unseen']} unseen (evidence policy: {mode}).")
    valid = sum(c["valid"] for c in comps.values())
    unver = sum(c["unverified"] for c in comps.values())
    L.append(f"- Independent assessments: {len(indep)} counted ({valid} rubric-backed, {unver} unverified/legacy). "
             + ("Too few for a trend." if len(indep) < 3 else f"Last 5 scores: {[e['score'] for e in indep[-5:]]}."))
    if mode == "legacy" and unver:
        L.append("- Note: legacy mode counts unverified events toward `mastered`; add `evidence_policy: {mode: strict}` to program.yaml "
                 "to require structured evidence (see docs/assessment.md, migration).")
    L.append("- Delayed retention: " + (f"{sum(1 for e in delayed if e['score'] >= pass_t)} passed, "
                                         f"{sum(1 for e in delayed if e['score'] < pass_t)} failed of {len(delayed)} delayed review(s)." if delayed
                                         else "no delayed review yet (retention is unmeasured)."))
    L.append(f"- Reviews: {sched and len(sched) or 0} scheduled, {len(q['entries'])} due/overdue today "
             f"({sum(1 for e in q['entries'] if e['tier'] == 'failed')} after a failed review, "
             f"{sum(1 for e in q['entries'] if e['overdue_days'] >= sched[e['competency']]['interval_days'])} missed), "
             f"{sum(s['lapses'] for s in sched.values())} lapse(s) total; daily limit {q['cap']}.")
    ass = sum(1 for e in structured if e["independence"] == "assisted")
    L.append(f"- Assistance: {ass} of {len(structured)} structured attempt(s) were assisted"
             + (f" ({round(100 * ass / len(structured))}%)." if len(structured) >= 5 else " (too few attempts for a percentage)."))
    weak = [c for c, m in mastery["competencies"].items() if m["evidence_count"] and m["status"] == "learning"]
    lapsed = [c for c, s in sched.items() if s["last_result"] == "failed"]
    L.append("- Weak: " + (", ".join(f"`{c}`" for c in sorted(set(weak) | set(lapsed))) or "none measured") + ".")
    openm = [m for m in ev_state["misconceptions"].values() if m["status"] != "resolved"]
    L.append(f"- Misconceptions: {sum(1 for m in openm if m['status'] == 'demonstrated')} demonstrated, "
             f"{sum(1 for m in openm if m['status'] == 'suspected')} suspected, "
             f"{sum(1 for m in ev_state['misconceptions'].values() if m['status'] == 'resolved')} resolved, "
             f"{sum(1 for m in ev_state['misconceptions'].values() if m['recurrences'])} recurred.")
    L += ["", "| competency | status | level | independent n | last | next review |", "|---|---|---|---|---|---|"]
    for cid, c in comps.items():
        m = mastery["competencies"][cid]
        L.append(f"| {cid} | {m['status']} | {c['level']} | {m['evidence_count']} | {(c['last_independent'] or '-')[:10]} | {sched.get(cid, {}).get('due', '-')} |")
    L += ["", "## Interpretation (rule-based suggestion, not a measurement)", ""]
    nxt = None
    if assessment.open_tasks(root, pid):
        t = assessment.open_tasks(root, pid)[0]
        nxt = f"Finish assessment `{t['id']}` (it is {t['status']})."
    elif open_session(root, pid):
        nxt = "Resume the open review session."
    elif q["shown"]:
        e = q["shown"][0]
        nxt = f"Start a review session: {len(q['shown'])} item(s) to assign, most urgent `{e['competency']}` [{e['tier']}]."
    else:
        try:
            rec = lifecycle.recommend(root, pid)
            nxt = (f"Next lesson: `{rec['pick']['ref']}` ({rec['pick']['kind']})." if rec["pick"] else "No lesson is eligible: " + "; ".join(rec["blockers"][:2]))
        except ValueError as exc:
            nxt = f"No lesson can be planned: {exc}"
    L.append(f"- Recommended next action: {nxt}")
    if n and by_level["unseen"] + by_level["exposure"] == n:
        L.append("- No independent evidence exists yet, so no mastery claim is supported.")
    return "\n".join(L)


# --------------------------------------------------------------------------
# validation hook
# --------------------------------------------------------------------------

def validate_program(root: Path, pid: str, report: model.Report) -> None:
    d = rdir(root, pid)
    if not d.is_dir():
        return
    base = f"programs/{pid}/reviews"
    program = miniyaml.loads((model.program_dir(root, pid) / "program.yaml").read_text("utf-8"))
    known = {c["id"] for c in program.get("competencies", [])}
    opens, assigned = [], {}
    for p in sorted(d.iterdir()):
        if p.name.startswith(".tmp-"):
            report.warn(f"{base}/{p.name}", "leftover temporary file from an interrupted write; safe to delete")
            continue
        m = RS_RE.match(p.name)
        if not m:
            report.error(base, f"unexpected file {p.name!r} (review sessions are NNN.yaml)")
            continue
        where = f"{base}/{p.name}"
        try:
            rs = _read(p)
        except ValueError as exc:
            report.error(where, str(exc))
            continue
        if rs["program"] != pid or rs["number"] != int(m.group(1)) or rs["id"] != f"review-{rs['number']:03d}":
            report.error(where, "id/program/number do not match the file name or directory")
        if rs["status"] == "open":
            opens.append(rs["id"])
        seen = set()
        for i in rs["items"]:
            if i["competency"] not in known:
                report.error(where, f"item references unknown competency {i['competency']!r}")
            if i["competency"] in seen:
                report.error(where, f"duplicate review item for {i['competency']!r}")
            seen.add(i["competency"])
            aid = i.get("assessment_id")
            if aid:
                if aid in assigned:
                    report.error(where, f"{aid} is assigned to two review items ({assigned[aid]})")
                assigned[aid] = rs["id"]
                try:
                    t = assessment.load_task(root, pid, aid)
                    if t["competency"] != i["competency"] or t.get("review_session") != rs["id"]:
                        report.error(where, f"{aid} does not belong to this review item")
                except ValueError as exc:
                    report.error(where, str(exc))
            if rs["status"] == "completed" and item_state(root, pid, i) not in ("committed", "skipped"):
                report.error(where, f"completed but item {i['competency']!r} is not committed or skipped")
    if len(opens) > 1:
        report.error(base, f"more than one open review session: {', '.join(opens)}")
    known_sessions = {f"review-{int(RS_RE.match(p.name).group(1)):03d}" for p in d.iterdir() if RS_RE.match(p.name)}
    events, _ = model.read_events(model.program_dir(root, pid) / "logs" / "assessments.jsonl")
    for e in events:
        if e.get("review_session") and e["review_session"] not in known_sessions:
            report.error(f"programs/{pid}/logs/assessments.jsonl:{e['_line']}", f"references missing {e['review_session']}")
