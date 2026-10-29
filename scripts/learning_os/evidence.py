"""Pure, deterministic derivations from the assessment log: mastery, evidence levels, review schedule, misconceptions.

No IO and no wall-clock time here, so a rebuild from the same log always gives the same state.
Nothing knows any subject matter.

Event classes (see engine/protocol/09-assessment-and-review.md):
  assisted    independence == "assisted": never counts toward score, status, scheduling or misconception resolution
  valid       independent + assessment_id + rubric_sha256 + confidence != low: can support strict `mastered`
  unverified  everything else (legacy lines without `independence`, or independent but not rubric-backed):
              counts toward score and proficient exactly as before Phase 6, never toward strict `mastered`
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_EVIDENCE = {"mode": "legacy", "min_task_types": 2, "min_retention_days": 3, "require_transfer": False}
DEFAULT_REVIEW = {"intervals": [1, 3, 7, 14, 30], "max_per_day": 5, "minutes_per_item": 5}
TYPE_TO_KIND = {"recall": "quiz", "application": "practice", "transfer": "project", "delayed_review": "review"}
ASSIST_CAP = {"none": 1.0, "hint-1": 0.8, "hint-2": 0.7, "hint-3": 0.6, "hint-4": 0.5, "worked-example": 0.3, "explained": 0.3}
ASSIST_ORDER = ["none", "hint-1", "hint-2", "hint-3", "hint-4", "worked-example", "explained"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def evidence_policy(program: dict) -> dict:
    return {**DEFAULT_EVIDENCE, **program.get("evidence_policy", {})}


def review_policy(program: dict) -> dict:
    return {**DEFAULT_REVIEW, **program.get("review_policy", {})}


def ts_date(ts: str) -> date:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).date()


def norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold())


def misconception_id(competency: str, text: str) -> str:
    return "mc-" + hashlib.sha1(f"{competency}\n{norm_text(text)}".encode("utf-8")).hexdigest()[:8]


def classify(ev: dict) -> str:
    ind = ev.get("independence")
    if ind == "assisted":
        return "assisted"
    if ind == "independent" and ev.get("assessment_id") and ev.get("rubric_sha256") and ev.get("confidence") != "low":
        return "valid"
    return "unverified"


def counts(ev: dict) -> bool:
    return classify(ev) != "assisted"


def _is_pass(program: dict, ev: dict) -> bool:
    return ev["score"] >= program["mastery_policy"]["proficient_threshold"]


# --------------------------------------------------------------------------
# per-event rules (shared by `log`, `assess commit` and `validate`)
# --------------------------------------------------------------------------

def check_event(ev: dict, program: dict) -> list[str]:
    """Semantic checks the JSON-Schema subset cannot express. Returns problems."""
    out: list[str] = []
    if ("lesson" in ev) == ("review_session" in ev):
        out.append("exactly one of `lesson` / `review_session` is required")
    if "objective" in ev and ev["objective"].split(":")[0] != ev["competency"]:
        out.append(f"objective {ev['objective']!r} does not belong to competency {ev['competency']!r}")
    ind = ev.get("independence")
    if ind == "independent" and (ev.get("assistance", "none") != "none" or ev.get("hints", 0)):
        out.append("an independent attempt cannot carry assistance or hints")
    if ind == "assisted":
        if ev.get("assistance", "none") == "none" and not ev.get("hints"):
            out.append("an assisted attempt must name the assistance level (or hints)")
        if ev["score"] >= 0.9:
            out.append("assisted work scores below 0.9 (the top band means independent)")
    if "independence" not in ev:
        for k in ("assessment_id", "rubric_sha256", "type", "difficulty", "confidence", "grading_method"):
            if k in ev:
                out.append(f"`{k}` needs `independence` to be recorded")
    if ev.get("resolves") and ev.get("independence") != "independent":
        out.append("resolving a misconception needs an independent attempt")
    if ev.get("type") == "delayed_review" and "review_session" not in ev and "lesson" not in ev:
        out.append("delayed_review needs a lesson or review session")
    return out


def resolution_ok(program: dict, ev: dict) -> bool:
    """A misconception is resolved only by a valid, passing, non-trivial independent assessment."""
    return classify(ev) == "valid" and _is_pass(program, ev) and ev.get("difficulty", "easy") != "easy"


# --------------------------------------------------------------------------
# mastery (mastery.yaml)
# --------------------------------------------------------------------------

def _valid_passes(program: dict, evs: list[dict]) -> list[dict]:
    return [e for e in evs if classify(e) == "valid" and _is_pass(program, e)]


def mastered_blockers(program: dict, evs: list[dict]) -> list[str]:
    """Why strict `mastered` is not (yet) supported by structured evidence. Empty list = supported."""
    pol, mp = evidence_policy(program), program["mastery_policy"]
    valid = [e for e in evs if classify(e) == "valid"]
    passes = _valid_passes(program, evs)
    out: list[str] = []
    if len(valid) < mp["min_evidence"]:
        out.append(f"needs {mp['min_evidence']} valid independent assessments (has {len(valid)})")
    types = sorted({e.get("type") for e in passes if e.get("type")})
    if len(types) < pol["min_task_types"]:
        out.append(f"needs passes on {pol['min_task_types']} different assessment types (has {len(types)})")
    if not any(e.get("difficulty", "easy") != "easy" for e in passes):
        out.append("needs a pass on a medium or hard task (easy tasks alone are not enough)")
    first = min((ts_date(e["ts"]) for e in passes), default=None)
    delayed = [e for e in passes if e.get("type") == "delayed_review"
               and first is not None and ts_date(e["ts"]) >= first + timedelta(days=pol["min_retention_days"])]
    if not delayed:
        out.append(f"needs a passing delayed review at least {pol['min_retention_days']} days after the first valid pass")
    if pol["require_transfer"] and not any(e.get("type") == "transfer" for e in passes):
        out.append("needs a passing transfer assessment")
    return out


def derive_mastery(program: dict, events: list[dict]) -> dict:
    pol = program["mastery_policy"]
    strict = evidence_policy(program)["mode"] == "strict"
    alpha = pol["ewma_alpha"]
    acc: dict[str, dict] = {c["id"]: {"score": None, "n": 0, "last": None, "evs": []} for c in program["competencies"]}
    as_of = None
    for ev in events:
        s = acc.get(ev["competency"])
        if s is None or not counts(ev):
            continue
        s["score"] = ev["score"] if s["score"] is None else alpha * ev["score"] + (1 - alpha) * s["score"]
        s["n"] += 1
        s["last"] = ev["ts"]
        s["evs"].append(ev)
        as_of = ev["ts"]
    comps = {}
    for cid, s in acc.items():
        n = s["n"]
        score = round(s["score"], 4) if n else 0.0
        if n == 0:
            status = "unseen"
        elif n >= pol["min_evidence"] and score >= pol["mastered_threshold"]:
            status = "mastered"
            if strict and mastered_blockers(program, s["evs"]):
                status = "proficient"
        elif n >= pol["min_evidence"] and score >= pol["proficient_threshold"]:
            status = "proficient"
        else:
            status = "learning"
        comps[cid] = {"score": score, "evidence_count": n, "status": status, "last_assessed": s["last"]}
    return {"schema_version": SCHEMA_VERSION, "program": program["id"], "as_of": as_of, "competencies": comps}


# --------------------------------------------------------------------------
# evidence levels, reviews, misconceptions (evidence.yaml)
# --------------------------------------------------------------------------

def _competency_evidence(program: dict, cid: str, evs: list[dict], exposed: bool) -> dict:
    valid = [e for e in evs if classify(e) == "valid"]
    unver = [e for e in evs if classify(e) == "unverified"]
    assisted = [e for e in evs if classify(e) == "assisted"]
    indep_passes = [e for e in evs if counts(e) and _is_pass(program, e)]
    vp = _valid_passes(program, evs)
    first = min((ts_date(e["ts"]) for e in vp), default=None)
    retained = bool(first is not None and any(
        e.get("type") == "delayed_review" and ts_date(e["ts"]) >= first + timedelta(days=evidence_policy(program)["min_retention_days"])
        for e in vp))
    if retained:
        level = "retained"
    elif indep_passes:
        level = "independent"
    elif any(_is_pass(program, e) for e in assisted):
        level = "assisted"
    elif exposed or evs:
        level = "exposure"
    else:
        level = "unseen"
    counted = [e for e in evs if counts(e)]
    return {
        "level": level, "exposure": exposed, "valid": len(valid), "unverified": len(unver), "assisted": len(assisted),
        "task_types": sorted({e["type"] for e in vp if e.get("type")}),
        "retained": retained, "transfer": any(e.get("type") == "transfer" for e in vp),
        "last_independent": counted[-1]["ts"] if counted else None,
        "mastered_blockers": mastered_blockers(program, evs),
    }


def derive_reviews(program: dict, events: list[dict]) -> dict:
    """Per-competency schedule. Walks independent events in order; assisted events never advance or reset it."""
    rp = review_policy(program)
    iv = rp["intervals"]
    mp = program["mastery_policy"]
    sched: dict[str, dict] = {}
    for ev in events:
        if not counts(ev) or ev["competency"] not in {c["id"] for c in program["competencies"]}:
            continue
        cid, d = ev["competency"], ts_date(ev["ts"])
        passed, strong = ev["score"] >= mp["proficient_threshold"], ev["score"] >= mp["mastered_threshold"]
        s = sched.get(cid)
        if s is None:
            if passed:
                sched[cid] = {"stage": 0, "interval_days": iv[0], "due": (d + timedelta(days=iv[0])).isoformat(),
                              "last_event": ev["ts"], "last_result": "entered", "lapses": 0, "holds": 0,
                              "reason": f"first independent pass (score {ev['score']}) on {d}; first review after {iv[0]} day(s)"}
            continue
        s["last_event"] = ev["ts"]
        if not passed:
            s["stage"] = max(0, s["stage"] - 2)
            s.update(interval_days=iv[s["stage"]], due=(d + timedelta(days=iv[s["stage"]])).isoformat(),
                     last_result="failed", lapses=s["lapses"] + 1, holds=0)
            s["reason"] = (f"failed independent retrieval (score {ev['score']}) on {d}; "
                           f"back to stage {s['stage']}, retry after {s['interval_days']} day(s)")
        elif d < date.fromisoformat(s["due"]):
            continue  # early success: retrieval before the due date does not lengthen the interval
        elif strong or s["holds"] >= 1:
            s["stage"] = min(s["stage"] + 1, len(iv) - 1)
            s.update(interval_days=iv[s["stage"]], due=(d + timedelta(days=iv[s["stage"]])).isoformat(),
                     last_result="advanced", holds=0)
            s["reason"] = f"{'strong' if strong else 'second consecutive'} pass (score {ev['score']}) on {d}; stage {s['stage']}, next after {s['interval_days']} day(s)"
        else:
            s.update(due=(d + timedelta(days=s["interval_days"])).isoformat(), last_result="held", holds=s["holds"] + 1)
            s["reason"] = (f"borderline pass (score {ev['score']} below mastered threshold) on {d}; "
                           f"same interval ({s['interval_days']} day(s)) repeated once")
    return sched


def derive_misconceptions(program: dict, events: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for ev in events:
        assisted = not counts(ev)  # assisted attempts can only raise a suspicion; they never demonstrate or resolve
        ref = f"logs/assessments.jsonl:{ev['_line']}" if "_line" in ev else ev["ts"]
        cid = ev["competency"]
        shown: set[str] = set()
        for m in ev.get("misconceptions", []):
            mid = misconception_id(cid, m["text"])
            shown.add(mid)
            cur = out.get(mid)
            if cur is None:
                cur = out[mid] = {"competency": cid, "text": m["text"], "status": "suspected", "demonstrated": 0,
                                  "recurrences": 0, "first_seen": ev["ts"], "last_seen": ev["ts"], "evidence": [],
                                  "unsupported_resolutions": 0}
            if m["status"] == "demonstrated" and not assisted:
                if cur["status"] == "resolved":
                    cur["recurrences"] += 1
                    cur.pop("resolved_by", None)
                cur["status"] = "demonstrated"
                cur["demonstrated"] += 1
            cur["last_seen"] = ev["ts"]
            cur["evidence"] = (cur["evidence"] + [ref])[-5:]
        for text in ([] if assisted else ev.get("resolves", [])):
            mid = misconception_id(cid, text)
            cur = out.get(mid)
            if cur is None or mid in shown or cur["status"] == "resolved":
                continue
            if resolution_ok(program, ev):
                cur["status"], cur["resolved_by"] = "resolved", ref
            else:
                cur["unsupported_resolutions"] += 1
    return out


def derive_evidence(program: dict, events: list[dict], lessons: list[dict]) -> dict:
    exposed: set[str] = set()
    for rec in lessons:
        meta = rec.get("meta", {})
        if isinstance(meta, dict) and meta.get("outcome") == "completed":
            exposed.update(c for c in meta.get("competencies_covered", []) if isinstance(c, str))
    by: dict[str, list[dict]] = {c["id"]: [] for c in program["competencies"]}
    for ev in events:
        if ev["competency"] in by:
            by[ev["competency"]].append(ev)
    return {
        "schema_version": SCHEMA_VERSION, "program": program["id"],
        "as_of": events[-1]["ts"] if events else None,
        "competencies": {cid: _competency_evidence(program, cid, evs, cid in exposed) for cid, evs in by.items()},
        "reviews": derive_reviews(program, events),
        "misconceptions": derive_misconceptions(program, events),
    }
