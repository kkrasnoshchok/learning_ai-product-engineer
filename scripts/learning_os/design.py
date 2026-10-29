"""Research and curriculum engine: approved spec -> research plan -> sources -> competency map
-> personalized curriculum -> approval -> activation.

Subject-agnostic: no domain content lives here. Durable state is files under
programs/<id>/design/ (edited only through this module); briefs and learner views are
computed on demand, so nothing derived is stored.

  design/research/plan.yaml        research plan (draft -> in_review -> approved)
  design/research/registry.yaml    source registry + evidence ledger
  design/competencies.yaml         domain-wide competency map (personalization-free)
  design/curriculum/draft.yaml     personalized curriculum (draft -> in_review -> approved)
  design/*/versions/*              frozen snapshots: approved plans, curricula, replaced maps
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from . import miniyaml, model, onboarding

SCHEMA = {"plan": "research-plan", "curriculum": "curriculum"}
VOLATILE = {"status", "revision", "approval"}
DEFAULT_CRITERIA = [  # generic, domain-free; the learner may revise them during plan review
    ("authority", "Author or publisher is accountable for the subject (standards body, maintainer, institution, practitioner with a track record)."),
    ("primary-over-secondary", "Primary or official material is preferred to summaries of it."),
    ("recency", "Publication or update date is known and recent enough for the subject's rate of change."),
    ("corroboration", "Load-bearing claims are supported by at least two independent sources."),
    ("relevance", "Content bears directly on a stated research question and learner outcome."),
    ("transparency", "Method, evidence and limitations are stated; opinion is labelled as opinion."),
]
INSPECTED = {"inspected", "verified"}


# --------------------------------------------------------------------------
# paths and IO
# --------------------------------------------------------------------------

def ddir(root: Path, pid: str) -> Path:
    return model.program_dir(root, pid) / "design"


def _p(root: Path, pid: str, what: str, rev: int | None = None) -> Path:
    d = ddir(root, pid)
    return {
        "plan": d / "research" / "plan.yaml",
        "registry": d / "research" / "registry.yaml",
        "map": d / "competencies.yaml",
        "curriculum": d / "curriculum" / "draft.yaml",
        "plan-snap": d / "research" / "versions" / f"plan-r{rev or 0:03d}.yaml",
        "curriculum-snap": d / "curriculum" / "versions" / f"r{rev or 0:03d}.yaml",
        "map-snap": d / "versions" / f"competencies-r{rev or 0:03d}.yaml",
        "program-before": d / "curriculum" / "versions" / f"program-before-r{rev or 0:03d}.yaml",
    }[what]


def _load(path: Path, schema: str, label: str) -> dict:
    rep = model.Report()
    doc = model.load_yaml(rep, path, label)
    if doc is None or not model.check_schema(rep, label, doc, schema):
        raise ValueError("; ".join(rep.errors))
    return doc


def _save(path: Path, doc: dict) -> None:
    onboarding._atomic_write(path, onboarding._dump_state(doc))


def content_hash(doc: dict) -> str:
    body = {k: v for k, v in doc.items() if k not in VOLATILE}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _today(today: str | None) -> str:
    return today or date.today().isoformat()


def spec(root: Path, pid: str) -> dict:
    """The approved onboarding state: the gate for everything in this module."""
    if not model.program_dir(root, pid).is_dir():
        raise ValueError(f"programs/{pid} does not exist; finish onboarding first")
    state = onboarding.load_state(root, pid)
    if state["status"] != "approved":
        raise ValueError(f"onboarding is {state['status']!r}; research and curriculum work require an approved spec")
    return state


def load_plan(root, pid) -> dict:
    return _load(_p(root, pid, "plan"), "research-plan", f"programs/{pid}/design/research/plan.yaml")


def load_registry(root, pid) -> dict:
    return _load(_p(root, pid, "registry"), "research-registry", f"programs/{pid}/design/research/registry.yaml")


def load_map(root, pid) -> dict:
    return _load(_p(root, pid, "map"), "competency-map", f"programs/{pid}/design/competencies.yaml")


def load_curriculum(root, pid) -> dict:
    return _load(_p(root, pid, "curriculum"), "curriculum", f"programs/{pid}/design/curriculum/draft.yaml")


def _exists(root, pid, what) -> bool:
    return _p(root, pid, what).is_file()


def _dups(ids: list[str]) -> list[str]:
    return sorted({i for i in ids if ids.count(i) > 1})


# --------------------------------------------------------------------------
# research plan
# --------------------------------------------------------------------------

def check_plan(plan: dict) -> list[str]:
    errs: list[str] = []
    for label, items in (("outcome", plan["outcomes"]), ("question", plan["questions"]),
                         ("source category", plan["source_categories"]), ("quality criterion", plan["quality_criteria"]),
                         ("gap", plan["gaps"]), ("task", plan["tasks"])):
        for d in _dups([i["id"] for i in items]):
            errs.append(f"duplicate {label} id {d!r}")
    outs = {o["id"] for o in plan["outcomes"]}
    qs = {q["id"] for q in plan["questions"]}
    cats = {c["id"] for c in plan["source_categories"]}
    if not plan["outcomes"]:
        errs.append("no learner outcomes")
    if not plan["questions"]:
        errs.append("no research questions")
    if not plan["source_categories"]:
        errs.append("no source categories")
    if not plan["quality_criteria"]:
        errs.append("no source-quality criteria")
    for q in plan["questions"]:
        if not q["outcomes"]:
            errs.append(f"question {q['id']!r} serves no outcome")
        for o in q["outcomes"]:
            if o not in outs:
                errs.append(f"question {q['id']!r} references unknown outcome {o!r}")
        if not any(t["question"] == q["id"] for t in plan["tasks"]):
            errs.append(f"question {q['id']!r} has no research task")
    for o in plan["outcomes"]:
        if not any(o["id"] in q["outcomes"] for q in plan["questions"]):
            errs.append(f"outcome {o['id']!r} has no research question")
    for t in plan["tasks"]:
        if t["question"] not in qs:
            errs.append(f"task {t['id']!r} references unknown question {t['question']!r}")
        if t["category"] not in cats:
            errs.append(f"task {t['id']!r} references unknown source category {t['category']!r}")
    return errs


def init_plan(root: Path, pid: str, created: str | None = None) -> Path:
    state = spec(root, pid)
    if _exists(root, pid, "plan"):
        raise ValueError("research plan already exists; resume with `research status`")
    g = state["goal"]
    outcomes = [(f"outcome-{i}", t) for i, t in enumerate(g.get("competency_outcomes", []) + g.get("practical_outcomes", []), 1)]
    plan = {"schema_version": 1, "id": pid, "status": "draft", "revision": 1, "created": created or date.today().isoformat(),
            "basis": {"onboarding_revision": state["approval"]["revision"]},
            "outcomes": [{"id": i, "text": t} for i, t in outcomes],
            "questions": [], "source_categories": [],
            "quality_criteria": [{"id": i, "text": t} for i, t in DEFAULT_CRITERIA],
            "gaps": [], "tasks": []}
    _save(_p(root, pid, "plan"), plan)
    return _p(root, pid, "plan")


# --------------------------------------------------------------------------
# generic versioned document: plan and curriculum
# --------------------------------------------------------------------------

def _load_doc(root, pid, kind) -> dict:
    return load_plan(root, pid) if kind == "plan" else load_curriculum(root, pid)


def _doc_errors(root, pid, kind, doc, today, *, fresh: bool) -> list[str]:
    if kind == "plan":
        return check_plan(doc)
    return check_curriculum(root, pid, doc, today=today, fresh=fresh).errors


def update_doc(root: Path, pid: str, kind: str, patch: Any) -> dict:
    spec(root, pid)
    doc = _load_doc(root, pid, kind)
    if not isinstance(patch, dict) or not patch:
        raise ValueError("update needs a non-empty YAML mapping")
    locked = {"schema_version", "id", "status", "revision", "created", "approval", "basis"}
    bad = sorted(set(patch) & locked)
    if bad:
        raise ValueError(f"cannot update {bad}; these are managed by the CLI")
    new = {**doc, **patch}  # top-level keys are replaced wholesale: send the whole section you changed
    rep = model.Report()
    if not model.check_schema(rep, "update", new, SCHEMA[kind]):
        raise ValueError("; ".join(rep.errors))
    if {k: v for k, v in new.items() if k not in VOLATILE} == {k: v for k, v in doc.items() if k not in VOLATILE}:
        return doc
    new["revision"] = doc["revision"] + 1
    new["status"] = "draft"  # every change needs a fresh review; the old approval cannot carry over
    new.pop("approval", None)
    _save(_p(root, pid, kind), new)
    return new


def submit_doc(root: Path, pid: str, kind: str, today: str | None = None) -> dict:
    spec(root, pid)
    doc = _load_doc(root, pid, kind)
    if doc["status"] == "approved":
        raise ValueError("already approved at this revision; `update` first to start a new revision")
    errs = _doc_errors(root, pid, kind, doc, _today(today), fresh=True)
    if errs:
        raise ValueError("cannot submit:\n  - " + "\n  - ".join(errs))
    doc["status"] = "in_review"
    _save(_p(root, pid, kind), doc)
    return doc


def approve_doc(root: Path, pid: str, kind: str, *, revision: int, statement: str, confirm: bool,
                today: str | None = None) -> dict:
    spec(root, pid)
    doc = _load_doc(root, pid, kind)
    if not confirm:
        raise ValueError("approval needs --confirm, passed only after the learner explicitly said yes in chat")
    if not statement.strip():
        raise ValueError("approval needs --statement quoting the learner's approval")
    if doc["status"] != "in_review":
        raise ValueError(f"status is {doc['status']!r}; submit and present it to the learner before approving")
    if revision != doc["revision"]:
        raise ValueError(f"learner reviewed revision {revision} but current is {doc['revision']}; present it again")
    errs = _doc_errors(root, pid, kind, doc, _today(today), fresh=True)
    if errs:
        raise ValueError("cannot approve:\n  - " + "\n  - ".join(errs))
    snap = _p(root, pid, f"{kind}-snap", revision)
    if snap.exists():
        raise ValueError(f"{snap.name} already exists; refusing to overwrite an approved version")
    doc["status"] = "approved"
    doc["approval"] = {"revision": revision, "date": _today(today), "statement": statement.strip(),
                       "content_sha256": content_hash(doc)}
    _save(snap, doc)
    _save(_p(root, pid, kind), doc)
    if kind == "plan":
        _sync_registry(root, pid, doc)
    return doc


def _sync_registry(root: Path, pid: str, plan: dict) -> None:
    path = _p(root, pid, "registry")
    if path.is_file():
        reg = load_registry(root, pid)
    else:
        reg = {"schema_version": 1, "id": pid, "basis": {"plan_revision": plan["revision"]}, "browsing": "unknown",
               "sources": [], "findings": [], "tasks": [], "limitations": []}
    have = {t["id"] for t in reg["tasks"]}
    reg["tasks"] += [{"id": t["id"], "status": "pending"} for t in plan["tasks"] if t["id"] not in have]
    reg["basis"] = {"plan_revision": plan["revision"]}
    _save(path, reg)


# --------------------------------------------------------------------------
# source registry
# --------------------------------------------------------------------------

def check_registry(reg: dict, plan: dict) -> model.Report:
    rep = model.Report()
    qs = {q["id"] for q in plan["questions"]}
    sources = {s["id"]: s for s in reg["sources"]}
    for label, items in (("source", reg["sources"]), ("finding", reg["findings"]), ("task", reg["tasks"])):
        for d in _dups([i["id"] for i in items]):
            rep.error(label, f"duplicate id {d!r}")
    for s in reg["sources"]:
        w = f"source {s['id']!r}"
        if "url" not in s and "citation" not in s:
            rep.error(w, "needs a url or a bibliographic citation")
        if not s["relevance"]["questions"]:
            rep.error(w, "relevance names no research question")
        for q in s["relevance"]["questions"]:
            if q not in qs:
                rep.error(w, f"relevance references unknown question {q!r}")
        if s["status"] in INSPECTED:
            if "accessed" not in s:
                rep.error(w, f"status {s['status']!r} requires the date accessed")
            if "inspection" not in s:
                rep.error(w, f"status {s['status']!r} requires `inspection` (browsed, learner-provided or local-file)")
            if reg["browsing"] == "unavailable" and s.get("inspection") == "browsed":
                rep.error(w, "browsing is recorded as unavailable, so a source cannot have been 'browsed'")
        elif "inspection" in s:
            rep.error(w, f"{s['status']!r} source cannot claim an inspection")
        if s["status"] == "verified" and s["quality"]["rating"] == "unrated":
            rep.error(w, "a verified source must be quality-rated")
    for f in reg["findings"]:
        w = f"finding {f['id']!r}"
        for sid in f["sources"]:
            if sid not in sources:
                rep.error(w, f"references unknown source {sid!r}")
        for q in f["questions"]:
            if q not in qs:
                rep.error(w, f"references unknown question {q!r}")
        if f["kind"] != "claim" and f["status"] == "verified":
            rep.error(w, f"a {f['kind']} is model-generated and can never be 'verified'")
        if f["kind"] == "claim" and f["status"] == "verified":
            if not any(sources.get(s, {}).get("status") in INSPECTED for s in f["sources"]):
                rep.error(w, "a verified claim needs at least one inspected source (discovered sources are not evidence)")
    tids = {t["id"] for t in plan["tasks"]}
    for t in reg["tasks"]:
        if t["id"] not in tids:
            rep.warn(f"task {t['id']!r}", "not in the current research plan")
        if t["status"] == "blocked" and not t.get("note"):
            rep.error(f"task {t['id']!r}", "blocked tasks need a note saying why")
    return rep


def add_research(root: Path, pid: str, patch: Any, today: str | None = None) -> dict:
    """Upsert sources/findings/tasks by id, append limitations, set browsing. Refuses invalid results."""
    spec(root, pid)
    plan = load_plan(root, pid)
    if plan["status"] != "approved":
        raise ValueError("the research plan is not approved; research execution waits for the learner's approval of the plan")
    reg = load_registry(root, pid)
    if not isinstance(patch, dict) or not patch:
        raise ValueError("add needs a non-empty YAML mapping")
    bad = sorted(set(patch) - {"browsing", "sources", "findings", "tasks", "limitations"})
    if bad:
        raise ValueError(f"cannot add {bad}")
    new = json.loads(json.dumps(reg))
    if "browsing" in patch:
        new["browsing"] = patch["browsing"]
    for key in ("sources", "findings", "tasks"):
        if key in patch:
            if not isinstance(patch[key], list):
                raise ValueError(f"{key} must be a list")
            idx = {i["id"]: n for n, i in enumerate(new[key]) if isinstance(i, dict) and "id" in i}
            for item in patch[key]:
                if isinstance(item, dict) and item.get("id") in idx:
                    new[key][idx[item["id"]]] = item  # upsert replaces the whole entry
                else:
                    new[key].append(item)
    for lim in patch.get("limitations", []) or []:
        if isinstance(lim, str):
            lim = {"date": _today(today), "text": lim}
        if lim not in new["limitations"]:
            new["limitations"].append(lim)
    rep = model.Report()
    if not model.check_schema(rep, "registry", new, "research-registry"):
        raise ValueError("; ".join(rep.errors))
    chk = check_registry(new, plan)
    if chk.errors:
        raise ValueError("registry rejected:\n  - " + "\n  - ".join(chk.errors))
    if new != reg:
        _save(_p(root, pid, "registry"), new)
    return new


# --------------------------------------------------------------------------
# competency map (domain-wide)
# --------------------------------------------------------------------------

def check_map(cmap: dict, reg: dict) -> model.Report:
    rep = model.Report()
    comps = cmap["competencies"]
    ids = [c["id"] for c in comps]
    for d in _dups(ids):
        rep.error("map", f"duplicate competency id {d!r}")
    known = set(ids)
    sources = {s["id"]: s for s in reg["sources"]}
    for c in comps:
        w = f"competency {c['id']!r}"
        for p in c["prerequisites"]:
            if p == c["id"]:
                rep.error(w, "lists itself as a prerequisite")
            elif p not in known:
                rep.error(w, f"missing prerequisite {p!r}")
        for s in c["sources"]:
            if s not in sources:
                rep.error(w, f"references nonexistent source {s!r}")
            elif sources[s]["status"] == "unavailable":
                rep.error(w, f"cites unavailable source {s!r}")
        oids = [o["id"] for o in c["objectives"]]
        for d in _dups(oids):
            rep.error(w, f"duplicate objective id {d!r}")
        covered = set()
        for a in c["assessment_criteria"]:
            if a["objective"] not in oids:
                rep.error(w, f"assessment criterion references invalid objective {a['objective']!r}")
            covered.add(a["objective"])
        for o in oids:
            if o not in covered:
                rep.error(w, f"objective {o!r} has no assessment criterion")
    cycle = model._find_cycle({c["id"]: c["prerequisites"] for c in comps})
    if cycle:
        rep.error("map", "prerequisite cycle: " + " -> ".join(cycle))
    return rep


def set_map(root: Path, pid: str, patch: Any, today: str | None = None) -> dict:
    """Replace the domain competency map. Validates the whole graph; keeps the replaced revision."""
    spec(root, pid)
    plan = load_plan(root, pid)
    if plan["status"] != "approved":
        raise ValueError("the research plan is not approved yet")
    reg = load_registry(root, pid)
    if not isinstance(patch, dict) or "competencies" not in patch:
        raise ValueError("competencies set needs a YAML mapping with a `competencies` list")
    old = load_map(root, pid) if _exists(root, pid, "map") else None
    new = {"schema_version": 1, "id": pid, "revision": (old["revision"] + 1) if old else 1,
           "created": old["created"] if old else _today(today), "competencies": patch["competencies"]}
    rep = model.Report()
    if not model.check_schema(rep, "map", new, "competency-map"):
        raise ValueError("; ".join(rep.errors))
    chk = check_map(new, reg)
    if chk.errors:
        raise ValueError("competency map rejected:\n  - " + "\n  - ".join(chk.errors))
    if old:
        if old["competencies"] == new["competencies"]:
            return old
        snap = _p(root, pid, "map-snap", old["revision"])
        if not snap.exists():
            _save(snap, old)
    _save(_p(root, pid, "map"), new)
    return new


# --------------------------------------------------------------------------
# curriculum checks
# --------------------------------------------------------------------------

def current_basis(root: Path, pid: str) -> dict:
    return {"onboarding_revision": spec(root, pid)["approval"]["revision"],
            "plan_revision": load_plan(root, pid)["revision"],
            "competencies_revision": load_map(root, pid)["revision"]}


def _included(cur: dict) -> dict[str, str]:
    return {d["competency"]: d["disposition"] for d in cur["personalization"]["decisions"] if d["disposition"] != "deprioritize"}


def _objrefs(cmap: dict) -> set[str]:
    return {f"{c['id']}:{o['id']}" for c in cmap["competencies"] for o in c["objectives"]}


def check_curriculum(root: Path, pid: str, cur: dict, *, today: str | None = None, fresh: bool = True) -> model.Report:
    """Deterministic gate. `fresh` also enforces that the basis matches the current spec/plan/map."""
    rep = model.Report()
    state, plan, reg, cmap = spec(root, pid), load_plan(root, pid), load_registry(root, pid), load_map(root, pid)
    if plan["status"] != "approved":
        rep.error("basis", "research plan is not approved")
    if fresh and cur["basis"] != current_basis(root, pid):
        rep.error("basis", f"stale: draft built on {cur['basis']}, current is {current_basis(root, pid)}; run `curriculum rebase` after re-checking the draft")
    comps = {c["id"]: c for c in cmap["competencies"]}
    sources = {s["id"]: s for s in reg["sources"]}
    objrefs = _objrefs(cmap)
    # personalization
    decisions = cur["personalization"]["decisions"]
    for d in _dups([x["competency"] for x in decisions]):
        rep.error("personalization", f"competency {d!r} has more than one decision")
    dmap = {x["competency"]: x for x in decisions}
    for cid in comps:
        if cid not in dmap:
            rep.error("personalization", f"no decision for competency {cid!r}")
    for x in decisions:
        w = f"decision {x['competency']!r}"
        if x["competency"] not in comps:
            rep.error(w, "unknown competency")
        kinds = {e["kind"] for e in x["evidence"]}
        if x["disposition"] == "deprioritize" and not kinds & {"diagnostic", "goal"}:
            rep.error(w, "cannot be deprioritized on self-reported experience or constraints alone; "
                         "needs diagnostic evidence or a goal-based reason (self-report is not mastery)")
    inc = _included(cur)
    for cid, c in comps.items():
        if cid in inc:
            for p in c["prerequisites"]:
                if p in dmap and dmap[p]["disposition"] == "deprioritize" and "diagnostic" not in {e["kind"] for e in dmap[p]["evidence"]}:
                    rep.error(f"prerequisite gap {cid!r}", f"prerequisite {p!r} is assumed known without diagnostic evidence; set it to 'verify'")
    seq = cur["personalization"]["sequence"]
    if set(seq) != set(inc) or len(seq) != len(set(seq)):
        rep.error("sequence", "must list every studied/verified competency exactly once and nothing else")
    else:
        pos = {c: i for i, c in enumerate(seq)}
        for cid in seq:
            for p in comps.get(cid, {}).get("prerequisites", []):
                if p in pos and pos[p] > pos[cid]:
                    rep.error("sequence", f"{p!r} must come before {cid!r} (prerequisite)")
    # modules
    mods = cur["modules"]
    for d in _dups([m["id"] for m in mods]):
        rep.error("modules", f"duplicate module id {d!r}")
    mpos = {m["id"]: i for i, m in enumerate(mods)}
    first_cover: dict[str, int] = {}
    cover_by: dict[str, set[str]] = {}
    items = [i["id"] for m in mods for i in m["exercises"] + m["assessments"]]
    for d in _dups(items):
        rep.error("modules", f"duplicate exercise/assessment id {d!r}")
    for i, m in enumerate(mods):
        w = f"module {m['id']!r}"
        if not m["competencies"]:
            rep.error(w, "covers no competency")
        for c in m["competencies"]:
            if c not in comps:
                rep.error(w, f"unknown competency {c!r}")
            elif c not in inc:
                rep.error(w, f"covers deprioritized competency {c!r}")
            else:
                first_cover.setdefault(c, i)
                cover_by.setdefault(c, set()).add(m["id"])
        for o in m["objectives"]:
            if o not in objrefs:
                rep.error(w, f"invalid objective reference {o!r}")
            elif o.split(":")[0] not in m["competencies"]:
                rep.error(w, f"objective {o!r} belongs to a competency the module does not cover")
        for p in m["prerequisites"]:
            if p not in mpos:
                rep.error(w, f"unknown prerequisite module {p!r}")
            elif mpos[p] >= i:
                rep.error(w, f"prerequisite module {p!r} must be listed earlier")
        if not m["resources"]:
            rep.error(w, "no recommended resources")
        for r in m["resources"]:
            s = sources.get(r["source"])
            if s is None:
                rep.error(w, f"resource references nonexistent source {r['source']!r}")
            elif s["status"] not in INSPECTED:
                rep.error(w, f"resource {r['source']!r} was never inspected (status {s['status']!r}); do not recommend unseen material")
        if not m["exercises"]:
            rep.error(w, "no exercises or practical assignment")
        if not m["completion_criteria"]:
            rep.error(w, "no measurable completion criteria")
        for item in m["exercises"] + m["assessments"]:
            for o in item["objectives"]:
                if o not in objrefs:
                    rep.error(f"{w} item {item['id']!r}", f"invalid objective reference {o!r}")
        if not any(a["independent"] for a in m["assessments"]):
            rep.error(w, "needs at least one independent assessment (taken without assistance)")
        spent = sum(e["est_hours"] for e in m["exercises"]) + sum(a.get("est_hours", 0) for a in m["assessments"])
        if spent > m["est_hours"] + 1e-9:
            rep.error(w, f"est_hours {m['est_hours']} is less than its exercises and assessments ({spent})")
    for cid in inc:
        if cid not in first_cover:
            rep.error("coverage", f"competency {cid!r} is not covered by any module")
            continue
        for o in comps[cid]["objectives"]:
            if not any(f"{cid}:{o['id']}" in m["objectives"] for m in mods):
                rep.error("coverage", f"objective {cid}:{o['id']} is in no module")
        purposes = {a["purpose"] for m in mods if cid in m["competencies"] for a in m["assessments"]
                    if any(x.startswith(cid + ":") for x in a["objectives"])}
        if inc[cid] == "verify" and "diagnostic" not in purposes:
            rep.error("coverage", f"competency {cid!r} is marked 'verify' but no diagnostic assessment targets it")
        if inc[cid] == "study" and "mastery" not in purposes:
            rep.error("coverage", f"competency {cid!r} has no mastery assessment")
        for p in comps[cid]["prerequisites"]:
            if p in inc and first_cover.get(p, 10**6) > first_cover[cid]:
                rep.error("coverage", f"module order teaches {cid!r} before its prerequisite {p!r}")
        evid = [s for s in comps[cid]["sources"] if sources.get(s, {}).get("status") in INSPECTED]
        if not evid:
            rep.error("evidence", f"competency {cid!r} rests only on sources nobody inspected")
    if set(seq) == set(inc):
        order = [first_cover.get(c, 0) for c in seq]
        if order != sorted(order):
            rep.error("sequence", "module order does not follow the personalized sequence")
    # checkpoints and capstone
    if len(mods) > 1 and not cur["checkpoints"]:
        rep.error("checkpoints", "a multi-module curriculum needs at least one review checkpoint")
    for d in _dups([c["id"] for c in cur["checkpoints"]]):
        rep.error("checkpoints", f"duplicate checkpoint id {d!r}")
    for cp in cur["checkpoints"]:
        w = f"checkpoint {cp['id']!r}"
        if cp["after_module"] not in mpos:
            rep.error(w, f"unknown module {cp['after_module']!r}")
            continue
        if not cp["reviews"]:
            rep.error(w, "reviews no competency")
        for c in cp["reviews"]:
            if c not in first_cover or first_cover[c] > mpos[cp["after_module"]]:
                rep.error(w, f"reviews {c!r}, which is not taught by or before {cp['after_module']!r}")
    cap = cur.get("capstone")
    if cap:
        for c in cap["competencies"]:
            if c not in inc:
                rep.error("capstone", f"unknown or deprioritized competency {c!r}")
        if not cap["completion_criteria"]:
            rep.error("capstone", "no measurable completion criteria")
    # realism
    total = effort_hours(cur)
    hpw = state.get("constraints", {}).get("hours_per_week")
    deadline = state.get("constraints", {}).get("deadline", "none")
    if hpw and deadline != "none":
        weeks_needed = total / hpw
        weeks_have = (date.fromisoformat(deadline) - date.fromisoformat(_today(today))).days / 7
        if weeks_needed > weeks_have + 1e-9:
            rep.error("effort", f"{total:g} h at {hpw:g} h/week needs {weeks_needed:.1f} weeks but only {weeks_have:.1f} remain before {deadline}; cut scope or revise the constraints")
    return rep


def effort_hours(cur: dict) -> float:
    return (sum(m["est_hours"] for m in cur["modules"]) + sum(c.get("est_hours", 0) for c in cur["checkpoints"])
            + (cur.get("capstone") or {}).get("est_hours", 0))


def init_curriculum(root: Path, pid: str, created: str | None = None) -> dict:
    spec(root, pid)
    if _exists(root, pid, "curriculum"):
        raise ValueError("curriculum draft already exists; use `curriculum update`")
    if load_plan(root, pid)["status"] != "approved" or not _exists(root, pid, "map"):
        raise ValueError("needs an approved research plan and a competency map first")
    cur = {"schema_version": 1, "id": pid, "status": "draft", "revision": 1, "created": created or date.today().isoformat(),
           "basis": current_basis(root, pid), "personalization": {"decisions": [], "sequence": []},
           "modules": [], "checkpoints": []}
    _save(_p(root, pid, "curriculum"), cur)
    return cur


def update_curriculum(root: Path, pid: str, patch: Any) -> dict:
    if not _exists(root, pid, "curriculum"):
        init_curriculum(root, pid)
    cur = update_doc(root, pid, "curriculum", patch)
    return cur


def rebase_curriculum(root: Path, pid: str) -> dict:
    cur = load_curriculum(root, pid)
    basis = current_basis(root, pid)
    if cur["basis"] == basis:
        return cur
    cur = {**cur, "basis": basis, "revision": cur["revision"] + 1, "status": "draft"}
    cur.pop("approval", None)
    _save(_p(root, pid, "curriculum"), cur)
    return cur


# --------------------------------------------------------------------------
# activation
# --------------------------------------------------------------------------

def active_competencies(cur: dict, cmap: dict) -> list[dict]:
    comps = {c["id"]: c for c in cmap["competencies"]}
    inc = _included(cur)
    out = []
    for cid in cur["personalization"]["sequence"]:
        c = comps[cid]
        out.append({"id": cid, "title": c["name"], "description": c["description"],
                    "prerequisites": [p for p in c["prerequisites"] if p in inc], "tags": [c["priority"]]})
    return out


def load_snapshot(root: Path, pid: str, revision: int) -> dict:
    snap = _p(root, pid, "curriculum-snap", revision)
    if not snap.is_file():
        raise ValueError(f"no approved curriculum revision {revision}; only approved revisions can be activated")
    doc = _load(snap, "curriculum", f"design/curriculum/versions/{snap.name}")
    ap = doc.get("approval")
    if doc["status"] != "approved" or not ap or ap["revision"] != revision or ap["content_sha256"] != content_hash(doc):
        raise ValueError(f"{snap.name} does not match its approval record; refusing to activate")
    return doc


def activate(root: Path, pid: str, revision: int, today: str | None = None) -> Path:
    """Replace program.yaml `competencies` with the approved curriculum's. Never touches logs, state or lessons."""
    spec(root, pid)
    cur = load_snapshot(root, pid, revision)
    cmap = _load_map_for(root, pid, cur)
    new_comps = active_competencies(cur, cmap)
    pdir = model.program_dir(root, pid)
    ppath = pdir / "program.yaml"
    before = ppath.read_text("utf-8")
    prog = miniyaml.loads(before)
    keep = {c["id"] for c in new_comps}
    events, _ = model.read_events(pdir / "logs" / "assessments.jsonl")
    lost = sorted({e["competency"] for e in events} - keep)
    if lost:
        raise ValueError(f"assessment history references {lost}, which this curriculum drops; refusing to orphan learner evidence")
    for rec in model.read_lessons(pdir)[0]:
        meta = rec["meta"]
        gone = sorted({c for k in ("competencies_covered", "next_focus") for c in meta.get(k, [])} - keep)
        if gone:
            raise ValueError(f"lesson {rec['file']} references {gone}, which this curriculum drops")
    backup = _p(root, pid, "program-before", revision)
    if not backup.exists():
        onboarding._atomic_write(backup, before)
    prog["competencies"] = new_comps
    prog["curriculum"] = {"revision": revision, "activated": _today(today),
                          "snapshot": f"design/curriculum/versions/r{revision:03d}.yaml"}
    try:
        onboarding._atomic_write(ppath, "# Competencies come from the approved curriculum (`curriculum activate`); see design/.\n"
                                 + onboarding._dump_state(prog))
        rep = model.rebuild(root, pid)
        if not rep.ok:
            raise ValueError("activated program is invalid: " + "; ".join(rep.errors))
    except BaseException:
        onboarding._atomic_write(ppath, before)
        try:
            model.rebuild(root, pid)
        except Exception:
            pass
        raise
    return ppath


def _load_map_for(root: Path, pid: str, cur: dict) -> dict:
    want = cur["basis"]["competencies_revision"]
    live = load_map(root, pid)
    if live["revision"] == want:
        return live
    snap = _p(root, pid, "map-snap", want)
    return _load(snap, "competency-map", f"design/versions/{snap.name}")


def versions(root: Path, pid: str) -> list[str]:
    d = ddir(root, pid)
    out = []
    for sub, pat in (("research/versions", "plan-r*.yaml"), ("curriculum/versions", "r*.yaml"), ("versions", "competencies-r*.yaml")):
        out += sorted(str(p.relative_to(d)) for p in (d / sub).glob(pat)) if (d / sub).is_dir() else []
    return out


# --------------------------------------------------------------------------
# stage, status, briefs, learner views (all computed)
# --------------------------------------------------------------------------

def stage(root: Path, pid: str) -> tuple[str, str]:
    try:
        spec(root, pid)
    except ValueError as exc:
        return "onboarding", f"{exc}"
    if not _exists(root, pid, "plan"):
        return "research-planning", "`research init`, then design questions, source categories and tasks (protocol 07)."
    plan = load_plan(root, pid)
    if plan["status"] == "draft":
        return "research-planning", "Complete the plan with `research plan-update`, then `research plan-submit`."
    if plan["status"] == "in_review":
        return "research-plan-review", "Present `research plan-show`; approve only on the learner's explicit yes, else `plan-update`."
    reg = load_registry(root, pid)
    pending = [t["id"] for t in reg["tasks"] if t["status"] == "pending"]
    if pending and not _exists(root, pid, "map"):
        return "source-research", f"{len(pending)} research task(s) pending. `research brief`, run them, record with `research add`."
    if not _exists(root, pid, "map"):
        return "competency-discovery", "Build the domain map from the evidence: `curriculum competencies-set`."
    if not _exists(root, pid, "curriculum"):
        return "personalization", "Create the curriculum draft with `curriculum update` (decisions, sequence, modules)."
    cur = load_curriculum(root, pid)
    prog = miniyaml.loads((model.program_dir(root, pid) / "program.yaml").read_text("utf-8"))
    active = prog.get("curriculum", {}).get("revision")
    if cur["status"] == "draft":
        return "curriculum-draft", "Run `curriculum check`, fix every error, then `curriculum submit`."
    if cur["status"] == "in_review":
        return "curriculum-review", "Present `curriculum show`; approve only on the learner's explicit yes, else `curriculum update`."
    if active != cur["revision"]:
        return "approved-not-active", f"Run `curriculum activate --revision {cur['revision']}`."
    return "active", "Curriculum is active. Lessons may start (`context`)."


def status_text(root: Path, pid: str) -> str:
    st, nxt = stage(root, pid)
    lines = [f"{pid}: stage {st}", f"next: {nxt}"]
    if st != "onboarding":
        lines.append(f"plan: {load_plan(root, pid)['status'] if _exists(root, pid, 'plan') else 'none'}"
                     f" | map: {'rev %d' % load_map(root, pid)['revision'] if _exists(root, pid, 'map') else 'none'}"
                     f" | curriculum: {'%s rev %d' % (load_curriculum(root, pid)['status'], load_curriculum(root, pid)['revision']) if _exists(root, pid, 'curriculum') else 'none'}")
    v = versions(root, pid)
    if v:
        lines.append("versions: " + ", ".join(v))
    return "\n".join(lines)


def _spec_lines(state: dict) -> list[str]:
    g, p, c = state["goal"], state["profile"], state["constraints"]
    out = [f"Goal: {g.get('statement', '')}", "Outcomes: " + "; ".join(g.get("competency_outcomes", []) + g.get("practical_outcomes", [])),
           "Success criteria: " + "; ".join(g.get("success_criteria", [])),
           "Prior experience (self-reported, NOT mastery): " + ("; ".join(p.get("prior_experience", [])) or "none"),
           "Known gaps: " + ("; ".join(p.get("knowledge_gaps", [])) or "none")]
    for i, d in enumerate(p.get("diagnostics", [])):
        out.append(f"Diagnostic {i}: {d['prompt']} -> {d['outcome']}" + (" (assisted)" if d.get("assisted") else ""))
    out.append("Constraints: " + ", ".join(f"{k}={v}" for k, v in c.items() if k not in ("preferred_methods", "other")))
    if c.get("preferred_methods"):
        out.append("Preferred methods: " + "; ".join(c["preferred_methods"]))
    return out


def research_brief(root: Path, pid: str, question: str | None = None, source: str | None = None) -> str:
    state = spec(root, pid)
    st, nxt = stage(root, pid)
    plan = load_plan(root, pid)
    lines = [f"# Research brief: {pid}", f"stage: {st}", f"next: {nxt}", "", "## Approved spec (summary)"] + _spec_lines(state)
    if source:
        reg = load_registry(root, pid)
        s = next((x for x in reg["sources"] if x["id"] == source), None)
        if s is None:
            raise ValueError(f"unknown source {source!r}")
        lines += ["", f"## Source {source}", miniyaml.dumps(s), "## Findings citing it"]
        lines += [f"- {f['id']} [{f['kind']}/{f['status']}] {f['text']}" for f in reg["findings"] if source in f["sources"]] or ["_none_"]
        return "\n".join(lines)
    lines += ["", f"## Research plan (revision {plan['revision']}, {plan['status']})"]
    qs = [q for q in plan["questions"] if not question or q["id"] == question]
    if question and not qs:
        raise ValueError(f"unknown question {question!r}")
    lines += [f"- {q['id']} ({q['priority']}): {q['text']}" for q in qs]
    lines += ["Quality criteria: " + "; ".join(f"{c['id']}: {c['text']}" for c in plan["quality_criteria"])]
    lines += ["Open gaps: " + ("; ".join(g["text"] for g in plan["gaps"]) or "none")]
    if plan["status"] != "approved" or not _exists(root, pid, "registry"):
        lines += ["", "Research execution has not started (plan not approved)."]
        return "\n".join(lines)
    reg = load_registry(root, pid)
    lines += ["", f"## Registry (browsing: {reg['browsing']})"]
    tmap = {t["id"]: t for t in plan["tasks"]}
    for t in reg["tasks"]:
        pt = tmap.get(t["id"])
        if pt and (not question or pt["question"] == question):
            lines.append(f"- task {t['id']} [{t['status']}] ({pt['question']}/{pt['category']}): {pt['description']}" + (f" -- {t['note']}" if t.get("note") else ""))
    lines.append("Sources (id | type | status | quality | title):")
    for s in reg["sources"]:
        if not question or question in s["relevance"]["questions"]:
            lines.append(f"- {s['id']} | {s['type']} | {s['status']} | {s['quality']['rating']} | {s['title']}")
    lines.append("Findings (id [kind/status]):")
    for f in reg["findings"]:
        if not question or question in f["questions"]:
            lines.append(f"- {f['id']} [{f['kind']}/{f['status']}, {len(f['sources'])} source(s)] {f['text']}")
    single = [f["id"] for f in reg["findings"] if f["kind"] == "claim" and f["status"] == "verified" and len(f["sources"]) < 2]
    if single:
        lines.append("Verified on a single source only (seek corroboration): " + ", ".join(single))
    if reg["limitations"]:
        lines += ["Limitations:"] + [f"- {x['date']}: {x['text']}" for x in reg["limitations"]]
    lines.append("Use `research brief --source <id>` for full source metadata.")
    return "\n".join(lines)


def curriculum_brief(root: Path, pid: str, competency: str | None = None) -> str:
    state = spec(root, pid)
    st, nxt = stage(root, pid)
    lines = [f"# Curriculum brief: {pid}", f"stage: {st}", f"next: {nxt}", "", "## Approved spec (summary)"] + _spec_lines(state)
    if not _exists(root, pid, "map"):
        return "\n".join(lines + ["", "No competency map yet."])
    cmap, reg = load_map(root, pid), load_registry(root, pid)
    sources = {s["id"]: s for s in reg["sources"]}
    if competency:
        c = next((x for x in cmap["competencies"] if x["id"] == competency), None)
        if c is None:
            raise ValueError(f"unknown competency {competency!r}")
        lines += ["", f"## Competency {competency}", miniyaml.dumps(c), "Sources:"]
        lines += [f"- {s}: {sources[s]['status']}, {sources[s]['quality']['rating']}, {sources[s]['title']}" for s in c["sources"] if s in sources]
        return "\n".join(lines)
    lines += ["", f"## Domain competency map (revision {cmap['revision']}; personalization-free)"]
    for c in cmap["competencies"]:
        ev = "inspected" if any(sources.get(s, {}).get("status") in INSPECTED for s in c["sources"]) else "UNINSPECTED"
        lines.append(f"- {c['id']} [{c['priority']}/{c['level']}] needs {c['prerequisites'] or '-'}; {len(c['objectives'])} objective(s); evidence {ev}: {c['name']}")
    if _exists(root, pid, "curriculum"):
        cur = load_curriculum(root, pid)
        lines += ["", f"## Curriculum draft (revision {cur['revision']}, {cur['status']})"]
        lines += [f"- {d['disposition']:12} {d['competency']}: {d['rationale']}" for d in cur["personalization"]["decisions"]]
        lines += ["Sequence: " + " > ".join(cur["personalization"]["sequence"]),
                  "Modules: " + ", ".join(f"{m['id']} ({m['est_hours']:g} h)" for m in cur["modules"]),
                  f"Total effort: {effort_hours(cur):g} h"]
        chk = check_curriculum(root, pid, cur)
        lines += [f"Check: {len(chk.errors)} error(s)"] + [f"  - {e}" for e in chk.errors]
    lines.append("Use `curriculum brief --competency <id>` for one competency in full.")
    return "\n".join(lines)


def render_plan(root: Path, pid: str) -> str:
    plan = load_plan(root, pid)
    L = [f"# Research plan: {pid}", f"Status: **{plan['status']}** (revision {plan['revision']})", "", "## Intended learner outcomes"]
    L += [f"- {o['id']}: {o['text']}" for o in plan["outcomes"]]
    L += ["", "## Research questions"] + [f"- {q['id']} ({q['priority']}, serves {', '.join(q['outcomes'])}): {q['text']}" for q in plan["questions"]]
    L += ["", "## Evidence and source categories"] + [f"- {c['id']} [{c['type']}, at least {c['min_sources']}]: {c['purpose']}" for c in plan["source_categories"]]
    L += ["", "## Source-quality criteria"] + [f"- {c['id']}: {c['text']}" for c in plan["quality_criteria"]]
    L += ["", "## Information gaps"] + ([f"- {g['id']}: {g['text']}" for g in plan["gaps"]] or ["_none recorded_"])
    L += ["", "## Research tasks (not yet executed)"] + [f"- {t['id']} ({t['question']} via {t['category']}): {t['description']}" for t in plan["tasks"]]
    if "approval" in plan:
        a = plan["approval"]
        L += ["", f"Approved revision {a['revision']} on {a['date']}: \"{a['statement']}\""]
    return "\n".join(L) + "\n"


def render_curriculum(root: Path, pid: str, cur: dict | None = None) -> str:
    cur = cur or load_curriculum(root, pid)
    state, cmap, reg = spec(root, pid), load_map(root, pid), load_registry(root, pid)
    if cur["basis"]["competencies_revision"] != cmap["revision"]:
        cmap = _load_map_for(root, pid, cur)
    comps = {c["id"]: c for c in cmap["competencies"]}
    sources = {s["id"]: s for s in reg["sources"]}
    total = effort_hours(cur)
    hpw = state["constraints"].get("hours_per_week")
    L = [f"# Curriculum: {state['title']}", f"Status: **{cur['status']}** (revision {cur['revision']})",
         f"Built on: onboarding rev {cur['basis']['onboarding_revision']}, research plan rev {cur['basis']['plan_revision']}, competency map rev {cur['basis']['competencies_revision']}", "",
         f"Estimated effort: {total:g} h" + (f" = about {total / hpw:.1f} weeks at {hpw:g} h/week" if hpw else ""), "",
         "## Personalization decisions"]
    for d in cur["personalization"]["decisions"]:
        ev = ", ".join(f"{e['kind']}: {e['ref']}" for e in d["evidence"])
        L.append(f"- **{d['competency']}** -> {d['disposition']}. {d['rationale']} (evidence: {ev})")
    L += ["", "Sequence: " + " > ".join(cur["personalization"]["sequence"]), "", "## Modules"]
    for m in cur["modules"]:
        L += ["", f"### {m['id']}: {m['title']} ({m['est_hours']:g} h)", "Competencies: " + ", ".join(m["competencies"]),
              "Needs modules: " + (", ".join(m["prerequisites"]) or "none"), "Objectives:"]
        L += [f"- {o}: " + next((x["text"] for x in comps.get(o.split(":")[0], {"objectives": []})["objectives"] if x["id"] == o.split(":")[1]), "?") for o in m["objectives"]]
        L += ["Resources:"] + [f"- [{r['use']}] {sources.get(r['source'], {}).get('title', r['source'])} ({r['source']})" + (f" - {r['note']}" if r.get("note") else "") for r in m["resources"]]
        L += ["Exercises:"] + [f"- {e['id']}: {e['title']} ({e['est_hours']:g} h)" for e in m["exercises"]]
        L += ["Assessments:"] + [f"- {a['id']}: {a['title']} [{a['purpose']}{', independent' if a['independent'] else ''}]" for a in m["assessments"]]
        L += ["Complete when:"] + [f"- {c}" for c in m["completion_criteria"]]
    L += ["", "## Review checkpoints"] + ([f"- {c['id']} after {c['after_module']}: {c['title']} (reviews {', '.join(c['reviews'])})" for c in cur["checkpoints"]] or ["_none_"])
    if cur.get("capstone"):
        c = cur["capstone"]
        L += ["", f"## Capstone: {c['title']} ({c['est_hours']:g} h)", c["description"], "Complete when:"] + [f"- {x}" for x in c["completion_criteria"]]
    if "approval" in cur:
        a = cur["approval"]
        L += ["", f"Approved revision {a['revision']} on {a['date']}: \"{a['statement']}\""]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------
# validation hook (called from model.validate_root, per program)
# --------------------------------------------------------------------------

def validate_program(root: Path, pid: str, report: model.Report) -> None:
    if not ddir(root, pid).is_dir():
        return
    base = f"programs/{pid}/design"

    def load(what, schema, label):
        if not _exists(root, pid, what):
            return None
        try:
            return _load(_p(root, pid, what), schema, f"{base}/{label}")
        except ValueError as exc:
            report.error(f"{base}/{label}", str(exc))
            return None

    plan = load("plan", "research-plan", "research/plan.yaml")
    reg = load("registry", "research-registry", "research/registry.yaml")
    cmap = load("map", "competency-map", "competencies.yaml")
    cur = load("curriculum", "curriculum", "curriculum/draft.yaml")
    for label, doc in (("plan", plan), ("registry", reg), ("map", cmap), ("curriculum", cur)):
        if doc is not None and doc["id"] != pid:
            report.error(f"{base}/{label}", f"id {doc['id']!r} does not match program")
    if (reg or cmap or cur) and (plan is None or plan["status"] != "approved"):
        report.error(base, "research registry/map/curriculum exist without an approved research plan")
        return
    for kind, doc in (("plan", plan), ("curriculum", cur)):
        if doc is None:
            continue
        w = f"{base}/{kind}"
        if doc["status"] == "approved":
            ap = doc.get("approval")
            if not ap or ap["revision"] != doc["revision"] or ap["content_sha256"] != content_hash(doc):
                report.error(w, "approved but content differs from its approval record (modified after approval?)")
            snap = _p(root, pid, f"{kind}-snap", doc["revision"])
            if not snap.is_file():
                report.error(w, f"approved revision has no preserved snapshot {snap.name}")
        elif "approval" in doc:
            report.error(w, "unapproved draft carries an approval record")
    if plan is not None and plan["status"] != "draft":
        for e in check_plan(plan):
            report.error(f"{base}/plan", e)
    if plan is not None and reg is not None:
        report.extend(_prefixed(check_registry(reg, plan), f"{base}/registry"))
    if cmap is not None and reg is not None:
        report.extend(_prefixed(check_map(cmap, reg), f"{base}/competencies"))
    if cur is not None and cur["status"] == "in_review" and cmap is not None and reg is not None:
        try:
            for e in check_curriculum(root, pid, cur, fresh=False).errors:
                if not e.startswith("effort:"):  # realism depends on the date; it is gated at submit/approve
                    report.error(f"{base}/curriculum", e)
        except ValueError as exc:
            report.error(f"{base}/curriculum", str(exc))
    prog_path = model.program_dir(root, pid) / "program.yaml"
    try:
        prog = miniyaml.loads(prog_path.read_text("utf-8"))
    except Exception:
        return
    if isinstance(prog, dict) and "curriculum" in prog:
        rev = prog["curriculum"]["revision"] if isinstance(prog["curriculum"], dict) and "revision" in prog["curriculum"] else None
        try:
            snap = load_snapshot(root, pid, rev)
            if prog["competencies"] != active_competencies(snap, _load_map_for(root, pid, snap)):
                report.error(f"programs/{pid}/program.yaml", f"competencies drifted from approved curriculum revision {rev}")
        except (ValueError, TypeError, KeyError) as exc:
            report.error(f"programs/{pid}/program.yaml", f"active curriculum revision invalid: {exc}")


def _prefixed(rep: model.Report, base: str) -> model.Report:
    out = model.Report()
    out.errors = [f"{base}: {e}" for e in rep.errors]
    out.warnings = [f"{base}: {w}" for w in rep.warnings]
    return out
