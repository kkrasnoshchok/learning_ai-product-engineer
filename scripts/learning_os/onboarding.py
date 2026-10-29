"""Program onboarding: learner goal -> approved program specification.

Subject-agnostic. The durable source of truth while onboarding is
onboarding/<id>/state.yaml; goals.md and program.draft.yaml next to it are
DERIVED previews. Approval creates programs/<id>/ (never overwrites) and
freezes the spec into program.yaml. No curriculum is generated here.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from . import miniyaml, model

SECTIONS = ("goal", "profile", "constraints", "assumptions", "open_questions")
UPDATABLE = SECTIONS + ("title",)
DRAFT_HEADER = (
    "# DERIVED PREVIEW - regenerated from state.yaml by `python3 scripts/los.py onboarding`.\n"
    "# Do not edit by hand; change state.yaml through `onboarding update`.\n"
)
GOALS_HEADER = "<!-- DERIVED PREVIEW: regenerated from state.yaml. Do not edit by hand. -->\n\n"


def onboarding_dir(root: Path, pid: str) -> Path:
    model.program_dir(root, pid)  # validates the id
    return Path(root) / "onboarding" / pid


def list_onboardings(root: Path) -> list[str]:
    d = Path(root) / "onboarding"
    return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.is_dir() else []


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _dump_state(state: dict) -> str:
    text = miniyaml.dumps(state)
    if miniyaml.loads(text) != state:  # never persist something that does not round-trip
        raise ValueError("state cannot be represented losslessly in YAML")
    return text


def load_state(root: Path, pid: str) -> dict:
    path = onboarding_dir(root, pid) / "state.yaml"
    if not path.is_file():
        raise ValueError(f"no onboarding for {pid!r}; start one with `onboarding start`")
    rep = model.Report()
    state = model.load_yaml(rep, path, f"onboarding/{pid}/state.yaml")
    if state is None or not model.check_schema(rep, f"onboarding/{pid}/state.yaml", state, "onboarding"):
        raise ValueError("; ".join(rep.errors))
    return state


# --------------------------------------------------------------------------
# completeness
# --------------------------------------------------------------------------

def missing(state: dict) -> list[str]:
    """Items that block submission, in the order the interview should cover them."""
    g, p, c = state.get("goal", {}), state.get("profile", {}), state.get("constraints", {})
    out: list[str] = []
    for key, label in (("statement", "goal.statement"), ("competency_outcomes", "goal.competency_outcomes"),
                       ("practical_outcomes", "goal.practical_outcomes"),
                       ("success_criteria", "goal.success_criteria (measurable)"),
                       ("motivation", "goal.motivation"), ("applications", "goal.applications")):
        if not g.get(key):
            out.append(label)
    for key in ("prior_experience", "knowledge_gaps"):  # [] is a valid, confirmed "none"
        if key not in p:
            out.append(f"profile.{key} (use [] if the learner confirms none)")
    for key in ("hours_per_week", "depth", "pace", "deadline"):
        if key not in c:
            out.append(f"constraints.{key}")
    for q in state.get("open_questions", []):
        if q["blocking"] and not q.get("answer"):
            out.append(f"open question {q['id']!r} (blocking): {q['text']}")
    return out


def next_step(state: dict) -> str:
    status = state["status"]
    if status == "approved":
        return "Approved. Curriculum authoring may start: `onboarding brief`, then protocol 05."
    if status == "in_review":
        return "Present `onboarding show` to the learner. Approve only on their explicit yes; otherwise `update` to revise."
    gaps = missing(state)
    if gaps:
        head = gaps[0].split(".")[0].split(" ")[0]
        stage = {"goal": "goal-discovery", "profile": "learner-profiling", "constraints": "constraints",
                 "open": "open-questions"}.get(head, head)
        return f"Continue the {stage} stage. Still missing: {gaps[0]}"
    return "Complete. Run `onboarding submit` and present `onboarding show` for review."


# --------------------------------------------------------------------------
# rendering (pure functions of state + the engine template)
# --------------------------------------------------------------------------

def _bullets(items: list[str], empty: str = "_none recorded_") -> str:
    return "\n".join(f"- {i}" for i in items) if items else empty


def render_goals(state: dict) -> str:
    g, p, c = state.get("goal", {}), state.get("profile", {}), state.get("constraints", {})
    lines = [f"# {state['title']}: learning goals", "",
             f"Status: **{state['status']}** (revision {state['revision']})", "",
             "## Goal", g.get("statement", "_not yet defined_"), "",
             "## Motivation", g.get("motivation", "_not yet defined_"), "",
             "## Intended applications", _bullets(g.get("applications", [])), "",
             "## Target competencies (outcomes, not yet a curriculum)", _bullets(g.get("competency_outcomes", [])), "",
             "## Practical outcomes", _bullets(g.get("practical_outcomes", [])), "",
             "## Success criteria", _bullets(g.get("success_criteria", [])), "",
             "## Learner profile",
             "Prior experience:", _bullets(p.get("prior_experience", [])), "",
             "Initial knowledge gaps:", _bullets(p.get("knowledge_gaps", [])), ""]
    diags = p.get("diagnostics", [])
    if diags:
        lines += ["Diagnostics:"] + [f"- {d['prompt']} -> {d['outcome']}" + (" (assisted)" if d.get("assisted") else "")
                                      for d in diags] + [""]
    lines += ["## Constraints and preferences"]
    for key, label in (("hours_per_week", "Hours per week"), ("session_minutes", "Session length (min)"),
                       ("depth", "Depth"), ("pace", "Pace"), ("deadline", "Deadline")):
        if key in c:
            lines.append(f"- {label}: {c[key]}")
    if c.get("preferred_methods"):
        lines.append("- Preferred methods: " + ", ".join(c["preferred_methods"]))
    lines += [f"- Other: {o}" for o in c.get("other", [])]
    lines += ["", "Global learner preferences (`learner/preferences.yaml`) apply on top of these and are not copied here.", "",
              "## Assumptions", _bullets(state.get("assumptions", [])), "", "## Open questions"]
    qs = state.get("open_questions", [])
    lines += [f"- [{'x' if q.get('answer') else ' '}] {q['text']}" + (" (blocking)" if q["blocking"] else "")
              + (f" -> {q['answer']}" if q.get("answer") else "") for q in qs] or ["_none_"]
    if "approval" in state:
        a = state["approval"]
        lines += ["", "## Approval", f"Approved revision {a['revision']} on {a['date']}: \"{a['statement']}\""]
    lines += ["", "The curriculum (competency graph) has not been generated yet.", ""]
    return "\n".join(lines)


def build_program(state: dict) -> dict:
    """The program.yaml for this spec: placeholder curriculum, real goal and frozen spec."""
    tpl = miniyaml.loads(
        (model.ENGINE_DIR / "templates" / "program" / "program.yaml").read_text("utf-8")
        .replace("__PROGRAM_ID__", state["id"]).replace("__PROGRAM_TITLE__", '"x"').replace("__CREATED__", state["created"]))
    prog = {k: tpl[k] for k in ("schema_version", "id")}
    prog["title"] = state["title"]
    prog["goal"] = state["goal"].get("statement", "TODO: goal not yet defined")
    prog["created"] = state["created"]
    prog["status"] = "active"
    prog["competencies"] = tpl["competencies"]  # TODO placeholder: curriculum comes after approval
    prog["mastery_policy"] = tpl["mastery_policy"]
    lp = dict(tpl["lesson_policy"])
    if "session_minutes" in state.get("constraints", {}):
        lp["target_minutes"] = state["constraints"]["session_minutes"]
    prog["lesson_policy"] = lp
    prog["spec"] = {k: state[k] for k in (*SECTIONS, "approval") if k in state}
    return prog


def _write_previews(root: Path, state: dict) -> None:
    d = onboarding_dir(root, state["id"])
    _atomic_write(d / "goals.md", GOALS_HEADER + render_goals(state))
    if state["status"] == "approved":
        for name in ("goals.md", "program.draft.yaml"):
            (d / name).unlink(missing_ok=True)
        return
    draft = build_program(state)
    _atomic_write(d / "program.draft.yaml", DRAFT_HEADER + miniyaml.dumps(draft))


def _save(root: Path, state: dict) -> None:
    _atomic_write(onboarding_dir(root, state["id"]) / "state.yaml", _dump_state(state))
    _write_previews(root, state)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def start(root: Path, pid: str, title: str, created: str | None = None) -> Path:
    d = onboarding_dir(root, pid)
    if (model.program_dir(root, pid)).exists():
        raise ValueError(f"programs/{pid} already exists; choose another id (onboarding never touches existing programs)")
    if d.exists():
        raise ValueError(f"onboarding/{pid} already exists; resume it with `onboarding status {pid}`")
    state = {"schema_version": 1, "id": pid, "title": title, "created": created or date.today().isoformat(),
             "status": "draft", "revision": 1,
             "goal": {}, "profile": {}, "constraints": {}, "assumptions": [], "open_questions": []}
    rep = model.Report()
    if not model.check_schema(rep, "state", state, "onboarding"):
        raise ValueError("; ".join(rep.errors))
    _save(root, state)
    return d


def update(root: Path, pid: str, patch: Any) -> dict:
    state = load_state(root, pid)
    if state["status"] == "approved":
        raise ValueError("onboarding is approved and frozen; program changes belong to the program itself")
    if not isinstance(patch, dict) or not patch:
        raise ValueError("update needs a non-empty YAML mapping")
    bad = sorted(set(patch) - set(UPDATABLE))
    if bad:
        raise ValueError(f"cannot update {bad}; allowed keys: {list(UPDATABLE)}")
    new = dict(state)
    for key, val in patch.items():
        if key in ("goal", "profile", "constraints"):
            if not isinstance(val, dict):
                raise ValueError(f"{key} must be a mapping")
            new[key] = {**state.get(key, {}), **val}  # shallow merge: send only what changed
        else:
            new[key] = val
    rep = model.Report()
    if not model.check_schema(rep, "update", new, "onboarding"):
        raise ValueError("; ".join(rep.errors))
    if new == state:
        return state
    new["revision"] = state["revision"] + 1
    new["status"] = "draft"  # any change after submission needs a fresh review
    _save(root, new)
    return new


def submit(root: Path, pid: str) -> dict:
    state = load_state(root, pid)
    if state["status"] == "approved":
        raise ValueError("already approved")
    gaps = missing(state)
    if gaps:
        raise ValueError("cannot submit; missing: " + "; ".join(gaps))
    state["status"] = "in_review"
    _save(root, state)
    return state


def approve(root: Path, pid: str, *, revision: int, statement: str, confirm: bool, today: str | None = None) -> Path:
    state = load_state(root, pid)
    if not confirm:
        raise ValueError("approval needs --confirm, passed only after the learner explicitly said yes in chat")
    if not statement.strip():
        raise ValueError("approval needs --statement quoting the learner's approval")
    if state["status"] != "in_review":
        raise ValueError(f"status is {state['status']!r}; submit and present the summary before approving")
    if revision != state["revision"]:
        raise ValueError(f"learner reviewed revision {revision} but current is {state['revision']}; present it again")
    gaps = missing(state)
    if gaps:
        raise ValueError("cannot approve; missing: " + "; ".join(gaps))
    pdir = model.program_dir(root, pid)
    if pdir.exists():
        raise ValueError(f"programs/{pid} already exists; refusing to overwrite")
    approved = dict(state, status="approved",
                    approval={"revision": revision, "date": today or date.today().isoformat(),
                              "statement": statement.strip()})
    rep = model.Report()
    if not model.check_schema(rep, "state", approved, "onboarding"):
        raise ValueError("; ".join(rep.errors))
    prog = build_program(approved)
    created = False
    try:
        model.new_program(root, pid, state["title"], state["created"])
        created = True
        (pdir / "program.yaml").write_text(
            "# Created by onboarding. `competencies` is a placeholder: the curriculum is authored next\n"
            "# (engine/protocol/05-program-authoring.md). `spec` is the approved specification.\n"
            + miniyaml.dumps(prog), "utf-8")
        (pdir / "goals.md").write_text(render_goals(approved), "utf-8")
        r = model.validate_program(root, pid)
        if not r.ok:
            raise ValueError("generated program is invalid: " + "; ".join(r.errors))
        _save(root, approved)
    except BaseException:
        if created:
            shutil.rmtree(pdir, ignore_errors=True)  # only the directory this call just created
        raise
    return pdir


def brief(root: Path, pid: str) -> str:
    """Approved spec as input for curriculum design. The gate: refuses anything unapproved."""
    state = load_state(root, pid)
    if state["status"] != "approved":
        raise ValueError(f"onboarding is {state['status']!r}; curriculum work requires explicit learner approval")
    if not (model.program_dir(root, pid) / "program.yaml").is_file():
        raise ValueError("approved onboarding has no program; run `validate`")
    return render_goals(state)


def _prefs_summary(root: Path) -> str:
    p = Path(root) / "learner" / "preferences.yaml"
    if not p.is_file():
        return "(no learner/preferences.yaml; ask the learner or use defaults)"
    return p.read_text("utf-8").strip()


def status_text(root: Path, pid: str) -> str:
    state = load_state(root, pid)
    gaps = missing(state)
    lines = [f"onboarding {pid}: {state['status']} (revision {state['revision']})", f"next: {next_step(state)}"]
    if gaps and state["status"] != "approved":
        lines += ["missing:"] + [f"  - {g}" for g in gaps]
    lines += ["", "--- global learner preferences (reuse; do not re-ask) ---", _prefs_summary(root),
              "", "--- current spec ---", render_goals(state)]
    return "\n".join(lines)


def list_text(root: Path) -> str:
    rows = []
    for pid in list_onboardings(root):
        try:
            s = load_state(root, pid)
            rows.append(f"{pid}\t{s['status']}\trev {s['revision']}\t{s['title']}")
        except ValueError as exc:
            rows.append(f"{pid}\tINVALID\t{exc}")
    return "\n".join(rows) or "(no onboardings)"


# --------------------------------------------------------------------------
# validation hook (called from model.validate_root)
# --------------------------------------------------------------------------

def validate_all(root: Path, report: model.Report) -> None:
    for pid in list_onboardings(root):
        where = f"onboarding/{pid}"
        try:
            state = load_state(root, pid)
        except ValueError as exc:
            report.error(where, str(exc))
            continue
        if state["id"] != pid:
            report.error(where, f"id {state['id']!r} does not match directory name")
            continue
        exists = model.program_dir(root, pid).exists()
        if state["status"] == "approved":
            if not exists:
                report.error(where, "approved but programs/%s does not exist" % pid)
            if "approval" not in state:
                report.error(where, "approved without an approval record")
        elif exists:
            report.error(where, f"unapproved onboarding collides with existing programs/{pid}")
        if state["status"] == "in_review" and missing(state):
            report.error(where, "in_review but incomplete")
        d = onboarding_dir(root, pid)
        if state["status"] != "approved":
            for name, expected in (("goals.md", GOALS_HEADER + render_goals(state)),
                                   ("program.draft.yaml", DRAFT_HEADER + miniyaml.dumps(build_program(state)))):
                f = d / name
                if not f.is_file() or f.read_text("utf-8") != expected:
                    report.error(f"{where}/{name}", "drifted from state.yaml; run `onboarding render " + pid + "`")


def render(root: Path, pid: str) -> None:
    _write_previews(root, load_state(root, pid))
