"""Domain-agnostic state model: loading, deriving, validating, context packs.

Nothing here knows any subject matter. Competencies come exclusively from a
program's own program.yaml.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import miniyaml, schema as jschema

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = REPO_ROOT / "engine"
SCHEMA_VERSION = 1
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LESSON_FILE_RE = re.compile(r"^(\d{3})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")
REQUIRED_HEADINGS = ("## Summary", "## Handoff")
MAX_FOCUS = 4

STATE_HEADER = (
    "# DERIVED STATE - rebuilt from logs/lessons by `python3 scripts/los.py rebuild`.\n"
    "# Do not edit by hand; `validate` fails if it drifts from its sources.\n"
)


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")

    def extend(self, other: "Report") -> None:
        self.errors += other.errors
        self.warnings += other.warnings

    @property
    def ok(self) -> bool:
        return not self.errors


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    return miniyaml.loads((ENGINE_DIR / "schemas" / f"{name}.schema.yaml").read_text("utf-8"))


def check_schema(report: Report, where: str, instance: Any, name: str) -> bool:
    errs = jschema.validate(instance, load_schema(name))
    for e in errs:
        report.error(where, e)
    return not errs


def load_yaml(report: Report, path: Path, rel: str) -> Any:
    if not path.is_file():
        report.error(rel, "file is missing")
        return None
    try:
        return miniyaml.loads(path.read_text("utf-8"))
    except (miniyaml.YamlError, UnicodeDecodeError) as exc:
        report.error(rel, f"cannot parse YAML: {exc}")
        return None


def program_dir(root: Path, pid: str) -> Path:
    if not ID_RE.fullmatch(pid) or len(pid) > 48:
        raise ValueError(f"invalid program id {pid!r} (use lowercase letters, digits, hyphens; max 48)")
    return Path(root) / "programs" / pid


def read_events(path: Path) -> tuple[list[dict], list[str]]:
    """Parse a JSONL log. Returns (events, error messages)."""
    events: list[dict] = []
    errors: list[str] = []
    if not path.is_file():
        return events, ["file is missing"]
    lines = path.read_text("utf-8").split("\n")
    for n, line in enumerate(lines, 1):
        if line == "" and n == len(lines):
            continue  # trailing newline
        if line.strip() == "":
            errors.append(f"line {n}: blank line")
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {n}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(ev, dict):
            errors.append(f"line {n}: expected a JSON object")
            continue
        ev["_line"] = n
        events.append(ev)
    return events, errors


def read_lessons(pdir: Path) -> tuple[list[dict], list[str]]:
    """Parse lessons/*.md. Returns (records sorted by number, error messages)."""
    records: list[dict] = []
    errors: list[str] = []
    ldir = pdir / "lessons"
    if not ldir.is_dir():
        return records, ["lessons/: directory is missing"]
    for path in sorted(ldir.iterdir()):
        if path.name == ".gitkeep":
            continue
        m = LESSON_FILE_RE.match(path.name)
        if not m:
            errors.append(f"lessons/{path.name}: name must look like 001-short-slug.md")
            continue
        try:
            meta, body = miniyaml.split_frontmatter(path.read_text("utf-8"))
        except (miniyaml.YamlError, UnicodeDecodeError) as exc:
            errors.append(f"lessons/{path.name}: {exc}")
            continue
        records.append({"file": path.name, "file_number": int(m.group(1)), "meta": meta, "body": body})
    return records, errors


# --------------------------------------------------------------------------
# derived state
# --------------------------------------------------------------------------

def derive_mastery(program: dict, events: list[dict]) -> dict:
    pol = program["mastery_policy"]
    alpha = pol["ewma_alpha"]
    acc = {c["id"]: {"score": None, "n": 0, "last": None} for c in program["competencies"]}
    as_of = None
    for ev in events:
        s = acc.get(ev["competency"])
        if s is None:
            continue
        s["score"] = ev["score"] if s["score"] is None else alpha * ev["score"] + (1 - alpha) * s["score"]
        s["n"] += 1
        s["last"] = ev["ts"]
        as_of = ev["ts"]
    comps = {}
    for cid, s in acc.items():
        n = s["n"]
        score = round(s["score"], 4) if n else 0.0
        if n == 0:
            status = "unseen"
        elif n >= pol["min_evidence"] and score >= pol["mastered_threshold"]:
            status = "mastered"
        elif n >= pol["min_evidence"] and score >= pol["proficient_threshold"]:
            status = "proficient"
        else:
            status = "learning"
        comps[cid] = {"score": score, "evidence_count": n, "status": status, "last_assessed": s["last"]}
    return {"schema_version": SCHEMA_VERSION, "program": program["id"], "as_of": as_of, "competencies": comps}


def derive_progress(program: dict, lessons: list[dict]) -> dict:
    ordered = sorted(lessons, key=lambda r: r["file_number"])
    last = ordered[-1] if ordered else None
    return {
        "schema_version": SCHEMA_VERSION,
        "program": program["id"],
        "as_of": last["meta"]["date"] if last else None,
        "lessons_completed": sum(1 for r in ordered if r["meta"]["outcome"] != "abandoned"),
        "last_lesson_file": last["file"] if last else None,
        "next_focus": list(last["meta"]["next_focus"]) if last else [],
    }


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def _find_cycle(prereqs: dict[str, list[str]]) -> list[str] | None:
    WHITE, GREY, BLACK = 0, 1, 2
    color = {k: WHITE for k in prereqs}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GREY
        stack.append(node)
        for nxt in prereqs[node]:
            if nxt not in color:
                continue
            if color[nxt] == GREY:
                return stack[stack.index(nxt):] + [nxt]
            if color[nxt] == WHITE:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for k in prereqs:
        if color[k] == WHITE:
            found = visit(k)
            if found:
                return found
    return None


def _scan_todo(report: Report, where: str, node: Any) -> None:
    if isinstance(node, str) and "TODO" in node:
        report.warn(where, f"unfinished placeholder: {node[:60]!r}")
    elif isinstance(node, dict):
        for v in node.values():
            _scan_todo(report, where, v)
    elif isinstance(node, list):
        for v in node:
            _scan_todo(report, where, v)


def validate_program_definition(report: Report, rel: str, program: Any) -> bool:
    if not check_schema(report, rel, program, "program"):
        return False
    ids = [c["id"] for c in program["competencies"]]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        report.error(rel, f"duplicate competency id {dup!r}")
    known = set(ids)
    for c in program["competencies"]:
        for p in c["prerequisites"]:
            if p == c["id"]:
                report.error(rel, f"competency {c['id']!r} lists itself as a prerequisite")
            elif p not in known:
                report.error(rel, f"competency {c['id']!r} has unknown prerequisite {p!r}")
    cycle = _find_cycle({c["id"]: c["prerequisites"] for c in program["competencies"]})
    if cycle:
        report.error(rel, "prerequisite cycle: " + " -> ".join(cycle))
    pol = program["mastery_policy"]
    if pol["proficient_threshold"] >= pol["mastered_threshold"]:
        report.error(rel, "proficient_threshold must be lower than mastered_threshold")
    _scan_todo(report, rel, program)
    return True


def validate_program(root: Path, pid: str) -> Report:
    report = Report()
    pdir = program_dir(root, pid)
    base = f"programs/{pid}"
    if not pdir.is_dir():
        report.error(base, "program directory does not exist")
        return report

    program = load_yaml(report, pdir / "program.yaml", f"{base}/program.yaml")
    if program is None or not validate_program_definition(report, f"{base}/program.yaml", program):
        return report
    if program["id"] != pid:
        report.error(f"{base}/program.yaml", f"id {program['id']!r} does not match directory name {pid!r}")
    known = {c["id"] for c in program["competencies"]}

    # lessons
    lessons, lerrs = read_lessons(pdir)
    for e in lerrs:
        report.error(base, e)
    valid_lessons: list[dict] = []
    for rec in lessons:
        where = f"{base}/lessons/{rec['file']}"
        if not check_schema(report, where, rec["meta"], "lesson-record"):
            continue
        meta = rec["meta"]
        if meta["program"] != pid:
            report.error(where, f"program {meta['program']!r} does not match {pid!r}")
        if meta["lesson"] != rec["file_number"]:
            report.error(where, f"lesson {meta['lesson']} does not match file number {rec['file_number']}")
        for key in ("competencies_covered", "next_focus"):
            for cid in meta[key]:
                if cid not in known:
                    report.error(where, f"{key} references unknown competency {cid!r}")
        for h in REQUIRED_HEADINGS:
            if not re.search(rf"^{re.escape(h)}\s*$", rec["body"], re.M):
                report.error(where, f"missing required section {h!r}")
        valid_lessons.append(rec)
    nums = [r["file_number"] for r in lessons]
    if nums != list(range(1, len(nums) + 1)):
        report.error(f"{base}/lessons", f"lesson numbers must be 1..N without gaps or duplicates, got {nums}")
    max_lesson = max(nums, default=0)

    # assessment log
    events, jerrs = read_events(pdir / "logs" / "assessments.jsonl")
    for e in jerrs:
        report.error(f"{base}/logs/assessments.jsonl", e)
    good_events: list[dict] = []
    prev_ts = ""
    for ev in events:
        where = f"{base}/logs/assessments.jsonl:{ev['_line']}"
        clean = {k: v for k, v in ev.items() if k != "_line"}
        if not check_schema(report, where, clean, "assessment-event"):
            continue
        if clean["program"] != pid:
            report.error(where, f"program {clean['program']!r} does not match {pid!r}")
        if clean["competency"] not in known:
            report.error(where, f"unknown competency {clean['competency']!r}")
        if clean["lesson"] > max_lesson + 1:
            report.error(where, f"references lesson {clean['lesson']} but only {max_lesson} lesson record(s) exist")
        if _norm_ts(clean["ts"]) < prev_ts:
            report.error(where, "timestamp is earlier than the previous event (log must be append-only)")
        prev_ts = max(prev_ts, _norm_ts(clean["ts"]))
        good_events.append(clean)

    # derived state
    expected_mastery = derive_mastery(program, good_events)
    mastery = load_yaml(report, pdir / "state" / "mastery.yaml", f"{base}/state/mastery.yaml")
    if mastery is not None and check_schema(report, f"{base}/state/mastery.yaml", mastery, "mastery"):
        if mastery != expected_mastery and report.ok:
            report.error(f"{base}/state/mastery.yaml", "drifted from logs/assessments.jsonl; run `python3 scripts/los.py rebuild " + pid + "`")
    if not report.errors:
        expected_progress = derive_progress(program, valid_lessons)
        progress = load_yaml(report, pdir / "state" / "progress.yaml", f"{base}/state/progress.yaml")
        if progress is not None and check_schema(report, f"{base}/state/progress.yaml", progress, "progress"):
            if progress != expected_progress:
                report.error(f"{base}/state/progress.yaml", "drifted from lessons/*.md; run `python3 scripts/los.py rebuild " + pid + "`")
    return report


def _norm_ts(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def list_programs(root: Path) -> list[str]:
    pdir = Path(root) / "programs"
    if not pdir.is_dir():
        return []
    return sorted(p.name for p in pdir.iterdir() if p.is_dir())


def validate_root(root: Path, program: str | None = None) -> Report:
    report = Report()
    root = Path(root)
    prefs = root / "learner" / "preferences.yaml"
    if prefs.is_file():
        data = load_yaml(report, prefs, "learner/preferences.yaml")
        if data is not None:
            check_schema(report, "learner/preferences.yaml", data, "learner-preferences")
    else:
        report.warn("learner/preferences.yaml", "not found; lessons will use defaults")
    targets = [program] if program else list_programs(root)
    from . import design  # lazy: design imports model
    for pid in targets:
        try:
            report.extend(validate_program(root, pid))
            design.validate_program(root, pid, report)
        except ValueError as exc:
            report.error(f"programs/{pid}", str(exc))
    if not program:
        from . import onboarding  # lazy: onboarding imports model
        onboarding.validate_all(root, report)
    return report


# --------------------------------------------------------------------------
# state mutation
# --------------------------------------------------------------------------

def _load_valid_program(root: Path, pid: str) -> dict:
    pdir = program_dir(root, pid)
    rep = Report()
    program = load_yaml(rep, pdir / "program.yaml", f"programs/{pid}/program.yaml")
    if program is None or not validate_program_definition(rep, "program.yaml", program) or not rep.ok:
        raise ValueError("; ".join(rep.errors) or "invalid program.yaml")
    return program


def write_mastery(root: Path, pid: str) -> dict:
    program = _load_valid_program(root, pid)
    pdir = program_dir(root, pid)
    events, errs = read_events(pdir / "logs" / "assessments.jsonl")
    if errs:
        raise ValueError("assessment log is invalid: " + "; ".join(errs))
    mastery = derive_mastery(program, [{k: v for k, v in e.items() if k != "_line"} for e in events])
    (pdir / "state" / "mastery.yaml").write_text(STATE_HEADER + miniyaml.dumps(mastery), "utf-8")
    return mastery


def write_progress(root: Path, pid: str) -> dict:
    program = _load_valid_program(root, pid)
    pdir = program_dir(root, pid)
    lessons, errs = read_lessons(pdir)
    if errs:
        raise ValueError("lesson records are invalid: " + "; ".join(errs))
    for rec in lessons:
        r = Report()
        if not check_schema(r, rec["file"], rec["meta"], "lesson-record"):
            raise ValueError("; ".join(r.errors))
    progress = derive_progress(program, lessons)
    (pdir / "state" / "progress.yaml").write_text(STATE_HEADER + miniyaml.dumps(progress), "utf-8")
    return progress


def rebuild(root: Path, pid: str) -> Report:
    write_mastery(root, pid)
    write_progress(root, pid)
    return validate_program(root, pid)


def now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_event(root: Path, pid: str, *, lesson: int, competency: str, kind: str,
                 score: float, notes: str | None = None, ts: str | None = None) -> dict:
    program = _load_valid_program(root, pid)
    pdir = program_dir(root, pid)
    log = pdir / "logs" / "assessments.jsonl"
    events, errs = read_events(log)
    if errs:
        raise ValueError("assessment log is invalid, fix before appending: " + "; ".join(errs))
    ev: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "ts": ts or now_ts(), "program": pid,
        "lesson": lesson, "competency": competency, "kind": kind, "score": score,
    }
    if notes:
        ev["notes"] = notes
    problems = jschema.validate(ev, load_schema("assessment-event"))
    if competency not in {c["id"] for c in program["competencies"]}:
        problems.append(f"unknown competency {competency!r}")
    if events and not problems and _norm_ts(ev["ts"]) < max(_norm_ts(e["ts"]) for e in events):
        problems.append("timestamp is earlier than the last logged event")
    lessons, _ = read_lessons(pdir)
    if lesson > max((r["file_number"] for r in lessons), default=0) + 1:
        problems.append(f"lesson {lesson} is ahead of the next lesson number")
    if problems:
        raise ValueError("; ".join(problems))
    line = json.dumps(ev, ensure_ascii=False, separators=(",", ":"))
    needs_nl = log.stat().st_size > 0 and not log.read_text("utf-8").endswith("\n")
    with log.open("a", encoding="utf-8") as fh:  # append-only, never rewrite
        fh.write(("\n" if needs_nl else "") + line + "\n")
    write_mastery(root, pid)
    return ev


def close_lesson(root: Path, pid: str, lesson: int) -> Report:
    """Validate a finished lesson record, then refresh derived state."""
    pdir = program_dir(root, pid)
    matches = sorted((pdir / "lessons").glob(f"{lesson:03d}-*.md"))
    if not matches:
        raise ValueError(f"no lesson record for lesson {lesson} in programs/{pid}/lessons/")
    return rebuild(root, pid)


def new_program(root: Path, pid: str, title: str, created: str | None = None) -> Path:
    pdir = program_dir(root, pid)
    if pdir.exists():
        raise ValueError(f"programs/{pid} already exists")
    created = created or date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", created):
        raise ValueError("created must be YYYY-MM-DD")
    tpl = ENGINE_DIR / "templates" / "program"
    for sub in ("state", "logs", "lessons", "materials"):
        (pdir / sub).mkdir(parents=True)
    text = (tpl / "program.yaml").read_text("utf-8")
    text = (text.replace("__PROGRAM_ID__", pid)
                .replace("__PROGRAM_TITLE__", json.dumps(title, ensure_ascii=False))
                .replace("__CREATED__", created))
    (pdir / "program.yaml").write_text(text, "utf-8")
    (pdir / "materials" / "README.md").write_text((tpl / "materials" / "README.md").read_text("utf-8"), "utf-8")
    (pdir / "logs" / "assessments.jsonl").write_text("", "utf-8")
    (pdir / "lessons" / ".gitkeep").write_text("", "utf-8")
    rep = rebuild(root, pid)
    if not rep.ok:
        raise ValueError("scaffolded program failed validation: " + "; ".join(rep.errors))
    return pdir


# --------------------------------------------------------------------------
# context pack (the only input a fresh lesson conversation receives)
# --------------------------------------------------------------------------

def extract_sections(body: str, headings: tuple[str, ...]) -> str:
    out: list[str] = []
    cur: list[str] | None = None
    for line in body.split("\n"):
        if line.startswith("## "):
            cur = None
            if line.strip() in headings:
                cur = [line.strip()]
                out.append("")
                out.append(cur[0])
                continue
        if cur is not None:
            out.append(line)
    return "\n".join(out).strip()


def suggest_focus(program: dict, mastery: dict, progress: dict, today: date) -> list[tuple[str, str]]:
    comps = {c["id"]: c for c in program["competencies"]}
    order = [c["id"] for c in program["competencies"]]
    m = mastery["competencies"]
    review_days = program["lesson_policy"]["review_after_days"]

    def ready(cid: str) -> bool:
        return all(m[p]["status"] in ("proficient", "mastered") for p in comps[cid]["prerequisites"])

    picks: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(cid: str, why: str) -> None:
        if cid not in seen:
            seen.add(cid)
            picks.append((cid, why))

    for cid in progress["next_focus"]:
        if cid in comps and m[cid]["status"] != "mastered":
            add(cid, "planned by the previous lesson")
    for cid in sorted((c for c in order if m[c]["status"] == "learning" and ready(c)), key=lambda c: m[c]["score"]):
        add(cid, f"in progress (score {m[cid]['score']})")
    for cid in order:
        last = m[cid]["last_assessed"]
        if m[cid]["status"] in ("proficient", "mastered") and last:
            if datetime.fromisoformat(last.replace("Z", "+00:00")).date() + timedelta(days=review_days) <= today:
                add(cid, f"review due (last assessed {last[:10]})")
    for cid in order:
        if m[cid]["status"] == "unseen" and ready(cid):
            add(cid, "not started; prerequisites met")
    return picks[:MAX_FOCUS]


def build_context(root: Path, pid: str, today: date | None = None) -> str:
    today = today or date.today()
    root = Path(root)
    report = validate_program(root, pid)
    if not report.ok:
        raise ValueError("program does not validate; fix first:\n  " + "\n  ".join(report.errors))
    pdir = program_dir(root, pid)
    program = miniyaml.loads((pdir / "program.yaml").read_text("utf-8"))
    mastery = miniyaml.loads((pdir / "state" / "mastery.yaml").read_text("utf-8"))
    progress = miniyaml.loads((pdir / "state" / "progress.yaml").read_text("utf-8"))
    prefs_path = root / "learner" / "preferences.yaml"
    prefs = miniyaml.loads(prefs_path.read_text("utf-8")) if prefs_path.is_file() else None

    L: list[str] = []
    L.append(f"# Lesson context pack: {program['title']} (`{pid}`)")
    L.append("")
    L.append(f"Generated {today.isoformat()} from program state only. It contains no earlier conversation.")
    L.append("")
    L.append("## Learner preferences (global)")
    L.append("")
    L.append("```yaml")
    L.append(miniyaml.dumps(prefs).rstrip() if prefs else "(none set; use neutral defaults)")
    L.append("```")
    L.append("")
    L.append("## Program")
    L.append("")
    L.append(f"- Goal: {program['goal']}")
    L.append(f"- Status: {program['status']}; lessons completed: {progress['lessons_completed']}")
    lp = program["lesson_policy"]
    L.append(f"- Target lesson length: {lp['target_minutes']} min; review interval: {lp['review_after_days']} days")
    L.append("")
    L.append("## Competency snapshot")
    L.append("")
    L.append("| id | title | status | score | evidence | last assessed | prerequisites |")
    L.append("|---|---|---|---|---|---|---|")
    for c in program["competencies"]:
        s = mastery["competencies"][c["id"]]
        L.append(f"| {c['id']} | {c['title']} | {s['status']} | {s['score']} | {s['evidence_count']} | "
                 f"{(s['last_assessed'] or '-')[:10]} | {', '.join(c['prerequisites']) or '-'} |")
    L.append("")
    L.append("## Suggested focus for this lesson")
    L.append("")
    picks = suggest_focus(program, mastery, progress, today)
    L.extend([f"{i}. `{cid}`: {why}" for i, (cid, why) in enumerate(picks, 1)] or ["(nothing eligible; discuss next steps with the learner)"])
    L.append("")
    n = lp["history_lessons_in_context"]
    lessons, _ = read_lessons(pdir)
    L.append(f"## Previous lesson handoff{'s' if n != 1 else ''}")
    L.append("")
    recent = sorted(lessons, key=lambda r: r["file_number"])[-n:] if n else []
    if not recent:
        L.append("(none)")
    for rec in recent:
        L.append(f"### Lesson {rec['file_number']}: {rec['meta']['title']} ({rec['meta']['date']}, {rec['meta']['outcome']})")
        L.append(extract_sections(rec["body"], REQUIRED_HEADINGS))
        L.append("")
    L.append("")
    L.append("## Rules")
    L.append("")
    L.append("Follow `engine/protocol/`. Do not read `archive/`, other programs, or older lesson records.")
    L.append("")
    return "\n".join(L)
