"""Command-line interface: `python3 scripts/los.py <command>`."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import model


def _print_report(report: model.Report, strict: bool) -> int:
    for w in report.warnings:
        print(f"warning: {w}")
    for e in report.errors:
        print(f"error: {e}")
    failed = bool(report.errors) or (strict and bool(report.warnings))
    print("FAILED" if failed else "OK", f"({len(report.errors)} error(s), {len(report.warnings)} warning(s))")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="los", description="Learning OS helper (file-first, no network).")
    p.add_argument("--root", type=Path, default=model.REPO_ROOT, help="data root holding learner/ and programs/")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="validate preferences and programs")
    v.add_argument("--program")
    v.add_argument("--strict", action="store_true", help="treat warnings as errors")

    n = sub.add_parser("new-program", help="scaffold an empty program from the template")
    n.add_argument("id")
    n.add_argument("--title", required=True)
    n.add_argument("--created")

    c = sub.add_parser("context", help="print the context pack for a fresh lesson")
    c.add_argument("program")
    c.add_argument("--today", help="YYYY-MM-DD (default: today)")

    lg = sub.add_parser("log", help="append one assessment event and refresh mastery")
    lg.add_argument("program")
    lg.add_argument("--lesson", type=int, required=True)
    lg.add_argument("--competency", required=True)
    lg.add_argument("--kind", required=True)
    lg.add_argument("--score", type=float, required=True)
    lg.add_argument("--notes")
    lg.add_argument("--ts", help="UTC timestamp, e.g. 2026-01-05T10:00:00Z (default: now)")

    r = sub.add_parser("rebuild", help="regenerate derived state files and validate")
    r.add_argument("program")

    cl = sub.add_parser("close", help="finish a lesson: refresh derived state and validate")
    cl.add_argument("program")
    cl.add_argument("--lesson", type=int, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "validate":
            return _print_report(model.validate_root(args.root, args.program), args.strict)
        if args.cmd == "new-program":
            path = model.new_program(args.root, args.id, args.title, args.created)
            print(f"created {path}")
            print("next: edit program.yaml (competencies, goal), then run `validate`")
            return 0
        if args.cmd == "context":
            today = date.fromisoformat(args.today) if args.today else None
            print(model.build_context(args.root, args.program, today))
            return 0
        if args.cmd == "log":
            ev = model.append_event(args.root, args.program, lesson=args.lesson, competency=args.competency,
                                    kind=args.kind, score=args.score, notes=args.notes, ts=args.ts)
            print(json.dumps(ev, ensure_ascii=False))
            return 0
        if args.cmd == "rebuild":
            return _print_report(model.rebuild(args.root, args.program), False)
        if args.cmd == "close":
            return _print_report(model.close_lesson(args.root, args.program, args.lesson), False)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2
