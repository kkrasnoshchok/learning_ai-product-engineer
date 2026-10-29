"""Command-line interface: `python3 scripts/los.py <command>`."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import design, model, onboarding, miniyaml


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

    ob = sub.add_parser("onboarding", help="turn a learner goal into an approved program spec")
    osub = ob.add_subparsers(dest="ocmd", required=True)
    o = osub.add_parser("start", help="begin an onboarding (never touches existing programs)")
    o.add_argument("id")
    o.add_argument("--title", required=True)
    o.add_argument("--created")
    o = osub.add_parser("update", help="merge a YAML mapping (goal/profile/constraints/assumptions/open_questions/title)")
    o.add_argument("id")
    o.add_argument("--file", required=True, help="YAML file, or - for stdin")
    for name, helptext in (("status", "resume briefing: state, gaps, next step"), ("show", "learner review summary"),
                           ("submit", "mark complete and ready for learner review"), ("render", "regenerate previews"),
                           ("brief", "approved spec for curriculum design (refuses unless approved)")):
        o = osub.add_parser(name, help=helptext)
        o.add_argument("id")
    o = osub.add_parser("approve", help="record explicit learner approval and create the program")
    o.add_argument("id")
    o.add_argument("--revision", type=int, required=True, help="the revision the learner reviewed")
    o.add_argument("--statement", required=True, help="the learner's approving words")
    o.add_argument("--confirm", action="store_true", help="only after the learner said yes in chat")
    o.add_argument("--date")
    osub.add_parser("list", help="list onboardings")
    _design_parsers(sub)
    return p


def _design_parsers(sub) -> None:
    def cmd(group, name, helptext, *flags):
        c = group.add_parser(name, help=helptext)
        c.add_argument("id")
        for f in flags:
            if f == "file":
                c.add_argument("--file", required=True, help="YAML file, or - for stdin")
            elif f == "today":
                c.add_argument("--today", help="YYYY-MM-DD (default: today)")
            elif f == "approve":
                c.add_argument("--revision", type=int, required=True, help="the revision the learner reviewed")
                c.add_argument("--statement", required=True, help="the learner's approving words")
                c.add_argument("--confirm", action="store_true", help="only after the learner said yes in chat")
            else:
                c.add_argument(f"--{f}")
        return c

    rs = sub.add_parser("research", help="research planning and source registry (needs an approved onboarding)")
    g = rs.add_subparsers(dest="rcmd", required=True)
    cmd(g, "init", "create the research plan from the approved spec", "today")
    cmd(g, "plan-update", "replace top-level plan sections from a YAML mapping", "file")
    cmd(g, "plan-show", "learner review view of the plan")
    cmd(g, "plan-submit", "mark the plan ready for learner review")
    cmd(g, "plan-approve", "record the learner's approval of the reviewed plan revision", "approve", "today")
    cmd(g, "add", "upsert sources/findings/tasks, append limitations, set browsing", "file", "today")
    cmd(g, "brief", "compact context for resuming research", "question", "source")
    cmd(g, "status", "stage and next step")

    cu = sub.add_parser("curriculum", help="competency map, personalized curriculum, approval, activation")
    g = cu.add_subparsers(dest="ccmd", required=True)
    cmd(g, "competencies-set", "replace the domain competency map (validates the graph)", "file", "today")
    cmd(g, "competencies-show", "print the competency map")
    cmd(g, "update", "replace top-level draft sections (personalization, modules, checkpoints, capstone)", "file")
    cmd(g, "rebase", "re-stamp the draft on the current spec/plan/map (new revision)")
    cmd(g, "check", "run every deterministic curriculum check", "today")
    cmd(g, "submit", "mark the draft ready for learner review", "today")
    cmd(g, "show", "learner review view of the whole curriculum")
    cmd(g, "approve", "record the learner's approval of the reviewed revision", "approve", "today")
    cmd(g, "activate", "write an approved revision into program.yaml", "today").add_argument("--revision", type=int, required=True)
    cmd(g, "versions", "list preserved snapshots")
    cmd(g, "brief", "compact context for resuming curriculum design", "competency")
    cmd(g, "status", "stage and next step")


def _read_patch(args):
    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text("utf-8")
    try:
        return miniyaml.loads(text)
    except miniyaml.YamlError as exc:
        raise ValueError(f"cannot parse YAML: {exc}")


def _research(args) -> int:
    root, c, pid = args.root, args.rcmd, args.id
    if c == "init":
        print(f"created {design.init_plan(root, pid, args.today)}")
        print("next:", design.stage(root, pid)[1])
    elif c == "plan-update":
        d = design.update_doc(root, pid, "plan", _read_patch(args))
        print(f"plan: {d['status']} revision {d['revision']}")
    elif c == "plan-show":
        print(design.render_plan(root, pid))
    elif c == "plan-submit":
        d = design.submit_doc(root, pid, "plan")
        print(f"plan: in_review revision {d['revision']}")
    elif c == "plan-approve":
        d = design.approve_doc(root, pid, "plan", revision=args.revision, statement=args.statement,
                               confirm=args.confirm, today=args.today)
        print(f"plan revision {d['revision']} approved; registry ready. Research may start.")
    elif c == "add":
        reg = design.add_research(root, pid, _read_patch(args), args.today)
        print(f"registry: {len(reg['sources'])} source(s), {len(reg['findings'])} finding(s), "
              f"{sum(t['status'] == 'pending' for t in reg['tasks'])} task(s) pending")
    elif c == "brief":
        print(design.research_brief(root, pid, args.question, args.source))
    elif c == "status":
        print(design.status_text(root, pid))
    return 0


def _curriculum(args) -> int:
    root, c, pid = args.root, args.ccmd, args.id
    if c == "competencies-set":
        m = design.set_map(root, pid, _read_patch(args), args.today)
        print(f"competency map revision {m['revision']}: {len(m['competencies'])} competencies, graph valid")
    elif c == "competencies-show":
        print(miniyaml.dumps(design.load_map(root, pid)))
    elif c == "update":
        d = design.update_curriculum(root, pid, _read_patch(args))
        print(f"curriculum: {d['status']} revision {d['revision']}")
    elif c == "rebase":
        d = design.rebase_curriculum(root, pid)
        print(f"curriculum: {d['status']} revision {d['revision']} on current basis")
    elif c == "check":
        rep = design.check_curriculum(root, pid, design.load_curriculum(root, pid), today=args.today)
        return _print_report(rep, False)
    elif c == "submit":
        d = design.submit_doc(root, pid, "curriculum", args.today)
        print(f"curriculum: in_review revision {d['revision']}")
    elif c == "show":
        print(design.render_curriculum(root, pid))
    elif c == "approve":
        d = design.approve_doc(root, pid, "curriculum", revision=args.revision, statement=args.statement,
                               confirm=args.confirm, today=args.today)
        print(f"curriculum revision {d['revision']} approved and preserved. Next: `curriculum activate --revision {d['revision']}`")
    elif c == "activate":
        design.activate(root, pid, args.revision, args.today)
        print(f"activated revision {args.revision} in programs/{pid}/program.yaml (logs, state and lessons untouched)")
    elif c == "versions":
        print("\n".join(design.versions(root, pid)) or "(no preserved versions)")
    elif c == "brief":
        print(design.curriculum_brief(root, pid, args.competency))
    elif c == "status":
        print(design.status_text(root, pid))
    return 0


def _onboarding(args) -> int:
    root, cmd = args.root, args.ocmd
    if cmd == "list":
        print(onboarding.list_text(root))
    elif cmd == "start":
        print(f"created {onboarding.start(root, args.id, args.title, args.created)}")
        print(f"next: `onboarding status {args.id}`, then interview the learner (protocol 06)")
    elif cmd == "update":
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text("utf-8")
        try:
            patch = miniyaml.loads(text)
        except miniyaml.YamlError as exc:
            raise ValueError(f"cannot parse update: {exc}")
        st = onboarding.update(root, args.id, patch)
        print(f"{args.id}: {st['status']} revision {st['revision']}")
        print("next:", onboarding.next_step(st))
    elif cmd == "status":
        print(onboarding.status_text(root, args.id))
    elif cmd == "show":
        print(onboarding.render_goals(onboarding.load_state(root, args.id)))
    elif cmd == "submit":
        st = onboarding.submit(root, args.id)
        print(f"{args.id}: in_review revision {st['revision']}")
        print("next:", onboarding.next_step(st))
    elif cmd == "render":
        onboarding.render(root, args.id)
    elif cmd == "brief":
        print(onboarding.brief(root, args.id))
    elif cmd == "approve":
        path = onboarding.approve(root, args.id, revision=args.revision, statement=args.statement,
                                  confirm=args.confirm, today=args.date)
        print(f"approved; created {path} (placeholder curriculum; author it per protocol 05)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "onboarding":
            return _onboarding(args)
        if args.cmd == "research":
            return _research(args)
        if args.cmd == "curriculum":
            return _curriculum(args)
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
