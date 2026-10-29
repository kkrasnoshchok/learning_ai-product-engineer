"""Domain-agnostic state model: loading, deriving, validating, context packs.

Nothing here knows any subject matter. Competencies come exclusively from a
program's own program.yaml.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import evidence, miniyaml, schema as jschema

try:
    import fcntl
except ImportError:  # non-POSIX: no advisory lock; single-writer discipline is then manual
    fcntl = None

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
    """Mastery status per competency. See evidence.derive_mastery for the evidence-class rules."""
    return evidence.derive_mastery(program, events)


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
    seen_assessments: set[str] = set()
    for ev in events:
        where = f"{base}/logs/assessments.jsonl:{ev['_line']}"
        clean = {k: v for k, v in ev.items() if k != "_line"}
        if not check_schema(report, where, clean, "assessment-event"):
            continue
        if clean["program"] != pid:
            report.error(where, f"program {clean['program']!r} does not match {pid!r}")
        if clean["competency"] not in known:
            report.error(where, f"unknown competency {clean['competency']!r}")
        if "lesson" in clean and clean["lesson"] > max_lesson + 1:
            report.error(where, f"references lesson {clean['lesson']} but only {max_lesson} lesson record(s) exist")
        for problem in evidence.check_event(clean, program):
            report.error(where, problem)
        aid = clean.get("assessment_id")
        if aid:
            if aid in seen_assessments:
                report.error(where, f"assessment {aid} was logged more than once (duplicate submission)")
            seen_assessments.add(aid)
        if _norm_ts(clean["ts"]) < prev_ts:
            report.error(where, "timestamp is earlier than the previous event (log must be append-only)")
        prev_ts = max(prev_ts, _norm_ts(clean["ts"]))
        good_events.append(ev)  # keeps `_line` so derived evidence can cite log lines

    # derived state
    expected_mastery = derive_mastery(program, good_events)
    expected_ev = evidence.derive_evidence(program, good_events, _lesson_records(pdir))
    mastery = load_yaml(report, pdir / "state" / "mastery.yaml", f"{base}/state/mastery.yaml")
    if mastery is not None and check_schema(report, f"{base}/state/mastery.yaml", mastery, "mastery"):
        if mastery != expected_mastery and report.ok:
            report.error(f"{base}/state/mastery.yaml", "drifted from logs/assessments.jsonl; run `python3 scripts/los.py rebuild " + pid + "`")
    ev_path = pdir / "state" / "evidence.yaml"
    if not ev_path.is_file():
        report.warn(f"{base}/state/evidence.yaml", "missing (created before Phase 6); run `python3 scripts/los.py rebuild " + pid + "`")
    else:
        stored = load_yaml(report, ev_path, f"{base}/state/evidence.yaml")
        if stored is not None and check_schema(report, f"{base}/state/evidence.yaml", stored, "evidence-state"):
            if stored != expected_ev and report.ok:
                report.error(f"{base}/state/evidence.yaml", "drifted from logs/assessments.jsonl; run `python3 scripts/los.py rebuild " + pid + "`")
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
            from . import lifecycle  # lazy: lifecycle imports model
            lifecycle.validate_program(root, pid, report)
            from . import assessment, review  # lazy: both import model
            assessment.validate_program(root, pid, report)
            review.validate_program(root, pid, report)
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


def atomic_write(path: Path, text: str) -> None:
    """Write via temp file + rename so readers never see a partial file."""
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


_HELD: dict[str, tuple[int, int]] = {}


@contextmanager
def program_lock(root: Path, pid: str, timeout: float = 10.0):
    """Exclusive, re-entrant, advisory per-program lock for every multi-file write (log append + derived state)."""
    pdir = program_dir(root, pid)
    key = str(pdir)
    if key in _HELD:
        fd, depth = _HELD[key]
        _HELD[key] = (fd, depth + 1)
        try:
            yield
        finally:
            _HELD[key] = (fd, _HELD[key][1] - 1)
        return
    if not pdir.is_dir():
        raise ValueError(f"programs/{pid} does not exist")
    fd = os.open(pdir / ".los.lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if fcntl is not None:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise ValueError(f"programs/{pid} is locked by another conversation; retry in a moment")
                    time.sleep(0.05)
        _HELD[key] = (fd, 1)
        try:
            yield
        finally:
            _HELD.pop(key, None)
    finally:
        os.close(fd)  # closing releases the flock


def _lesson_records(pdir: Path) -> list[dict]:
    """Schema-valid lesson records only (derived exposure must not depend on a broken file)."""
    recs, _ = read_lessons(pdir)
    return [r for r in recs if not jschema.validate(r["meta"], load_schema("lesson-record"))]


def write_mastery(root: Path, pid: str) -> dict:
    """Refresh state/mastery.yaml and state/evidence.yaml from the log (and completed lessons), atomically."""
    program = _load_valid_program(root, pid)
    pdir = program_dir(root, pid)
    with program_lock(root, pid):
        events, errs = read_events(pdir / "logs" / "assessments.jsonl")
        if errs:
            raise ValueError("assessment log is invalid: " + "; ".join(errs))
        mastery = derive_mastery(program, events)
        atomic_write(pdir / "state" / "mastery.yaml", STATE_HEADER + miniyaml.dumps(mastery))
        ev_state = evidence.derive_evidence(program, events, _lesson_records(pdir))
        atomic_write(pdir / "state" / "evidence.yaml", STATE_HEADER + miniyaml.dumps(ev_state))
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
    atomic_write(pdir / "state" / "progress.yaml", STATE_HEADER + miniyaml.dumps(progress))
    return progress


def rebuild(root: Path, pid: str) -> Report:
    write_mastery(root, pid)
    write_progress(root, pid)
    return validate_program(root, pid)


def now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_event(events: list[dict], assessment_id: str) -> dict | None:
    return next((e for e in events if e.get("assessment_id") == assessment_id), None)


def append_event(root: Path, pid: str, *, lesson: int | None = None, competency: str, kind: str,
                 score: float, notes: str | None = None, ts: str | None = None,
                 extra: dict | None = None) -> dict:
    """Append one event (locked, validated, idempotent on `assessment_id`) and refresh derived state.

    `extra` carries the optional Phase 6 fields (independence, type, assessment_id, ...). Re-appending an
    assessment_id that is already logged returns the existing event unchanged and writes nothing.
    """
    program = _load_valid_program(root, pid)
    pdir = program_dir(root, pid)
    log = pdir / "logs" / "assessments.jsonl"
    with program_lock(root, pid):
        events, errs = read_events(log)
        if errs:
            raise ValueError("assessment log is invalid, fix before appending: " + "; ".join(errs))
        extra = dict(extra or {})
        aid = extra.get("assessment_id")
        if aid and (prior := find_event(events, aid)):
            write_mastery(root, pid)  # finish an interrupted refresh
            return {k: v for k, v in prior.items() if k != "_line"}
        ev: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION, "ts": ts or now_ts(), "program": pid,
            "competency": competency, "kind": kind, "score": score,
        }
        if lesson is not None:
            ev["lesson"] = lesson
        if notes:
            ev["notes"] = notes
        ev.update(extra)
        problems = jschema.validate(ev, load_schema("assessment-event"))
        if not problems:
            problems += evidence.check_event(ev, program)
        if competency not in {c["id"] for c in program["competencies"]}:
            problems.append(f"unknown competency {competency!r}")
        if events and not problems and _norm_ts(ev["ts"]) < max(_norm_ts(e["ts"]) for e in events):
            problems.append("timestamp is earlier than the last logged event")
        lessons, _ = read_lessons(pdir)
        if lesson is not None and lesson > max((r["file_number"] for r in lessons), default=0) + 1:
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


def build_context(root: Path, pid: str, today: date | None = None, *, max_chars: int | None = None,
                  objective: str | None = None) -> str:
    """The lesson briefing. Built from this program's files only; sections shrink in a fixed order to fit `max_chars`."""
    from . import lifecycle  # lazy: lifecycle imports model
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
    lp = program["lesson_policy"]
    limit = max_chars or lp.get("context_max_chars") or lifecycle.DEFAULT_MAX_CHARS
    B = lifecycle.Block
    lc = lifecycle.lesson_blocks(root, pid, program, today, objective)
    lb = lc["blocks"]

    head = [f"# Lesson context pack: {program['title']} (`program:{pid}`)", "",
            f"Generated {today.isoformat()} from program files only. It contains no earlier conversation.", "",
            "## Learner preferences (global)", "", "```yaml",
            miniyaml.dumps(prefs).rstrip() if prefs else "(none set; use neutral defaults)", "```", "",
            "## Program", "", f"- Goal: {program['goal']}",
            f"- Status: {program['status']}; lessons completed: {progress['lessons_completed']}",
            f"- Target lesson length: {lp['target_minutes']} min; review interval: {lp['review_after_days']} days"]
    if program.get("curriculum"):
        head.append(f"- Active curriculum: revision {program['curriculum']['revision']} (`{program['curriculum']['snapshot']}`)")
    head.append("")

    full = ["## Competency snapshot", "", "| id | title | status | score | evidence | last assessed | prerequisites |",
            "|---|---|---|---|---|---|---|"]
    for c in program["competencies"]:
        st = mastery["competencies"][c["id"]]
        full.append(f"| {c['id']} | {c['title']} | {st['status']} | {st['score']} | {st['evidence_count']} | "
                    f"{(st['last_assessed'] or '-')[:10]} | {', '.join(c['prerequisites']) or '-'} |")
    full.append("")

    picks = suggest_focus(program, mastery, progress, today)
    sug = ["## Suggested focus for this lesson", ""]
    sug += [f"{i}. `{cid}`: {why}" for i, (cid, why) in enumerate(picks, 1)] or ["(nothing eligible; discuss next steps with the learner)"]
    sug.append("")

    n = lp["history_lessons_in_context"]
    lessons, _ = read_lessons(pdir)
    recent = sorted(lessons, key=lambda r: r["file_number"])[-n:] if n else []
    h_full = [f"## Previous lesson handoff{'s' if n != 1 else ''} (tutor interpretation)", ""]
    h_small = list(h_full)
    h_ref = h_full[:1] + ["", "(omitted for size; read the lesson record named below only if the learner asks)"]
    if not recent:
        h_full.append("(none)")
        h_small, h_ref = h_full, h_full
    for rec in recent:
        t = f"### Lesson {rec['file_number']}: {rec['meta']['title']} ({rec['meta']['date']}, {rec['meta']['outcome']}) [`lesson:{rec['file_number']:03d}`]"
        h_full += [t, extract_sections(rec["body"], REQUIRED_HEADINGS), ""]
        if recent:
            h_small += [t, extract_sections(rec["body"], ("## Handoff",)), ""]
            h_ref.append(f"- lessons/{rec['file']}")
    h_full.append("")

    rules = ["## Rules", "",
             "Follow `engine/protocol/` (08-lesson-lifecycle, 02-lesson-flow). Do not read `archive/`, other programs, or older "
             "lesson records. Instruction is not evidence: only logged assessment events change mastery. "
             "Lifecycle changes go through `python3 scripts/los.py lesson ...`.", ""]

    blocks: list = [B("head", "\n".join(head), required=True), lb["lesson"]]
    for k in ("objective", "progress"):
        if k in lb:
            blocks.append(lb[k])
    blocks.append(lb["snapshot"] if "snapshot" in lb else B("snapshot", "\n".join(full), required=True))
    for k in ("events", "interpretation", "resources", "misconceptions"):
        if k in lb:
            blocks.append(lb[k])
    if "prev_next" in lb:
        blocks.append(lb["prev_next"])
    if "snapshot" not in lb:
        blocks.append(B("suggested", "\n".join(sug), ""))
    focus_ids: list[str] = []
    if lc.get("focus") and lc.get("view"):
        fc = lc["focus"]["competency"]
        focus_ids = [fc, *lc["view"]["comps"][fc]["prerequisites"]]
    from . import review  # lazy: review imports model
    blocks += review.context_blocks(root, pid, program, today, focus_ids)
    blocks += [B("handoff", "\n".join(h_full), "\n".join(h_small), "\n".join(h_ref)), B("rules", "\n".join(rules), required=True)]
    return lifecycle.assemble(blocks, limit) + "\n"
