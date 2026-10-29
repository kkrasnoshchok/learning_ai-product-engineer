"""Command-line interface: `python3 scripts/los.py <command>`."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import assessment, design, lifecycle, model, onboarding, miniyaml, review


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
    c.add_argument("--max-chars", type=int, help="size budget for the pack (default: program lesson_policy.context_max_chars or 16000)")
    c.add_argument("--objective", help="focus the pack on this objective ref (<competency>:<objective>)")

    sub.add_parser("programs", help="list programs and any open lesson (for choosing where to work)")

    lg = sub.add_parser("log", help="append one assessment event and refresh mastery")
    lg.add_argument("program")
    lg.add_argument("--lesson", type=int, help="lesson number (omit only with --review-session)")
    lg.add_argument("--review-session", help="review-NNN (instead of --lesson)")
    lg.add_argument("--independence", choices=["independent", "assisted"],
                    help="classify the attempt; omitted = legacy/unverified evidence (prefer the `assess` workflow)")
    lg.add_argument("--assistance", choices=["none", "hint-1", "hint-2", "hint-3", "hint-4", "worked-example", "explained"])
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
    _lesson_parsers(sub)
    _assess_parsers(sub)
    pr = sub.add_parser("progress", help="compact, evidence-based progress report (facts first, interpretation labelled)")
    pr.add_argument("program")
    pr.add_argument("--today", help="YYYY-MM-DD (default: today)")
    return p


def _assess_parsers(sub) -> None:
    a = sub.add_parser("assess", help="independent assessments: create/show/hint/submit/brief/grade/review/commit/void/status")
    g = a.add_subparsers(dest="acmd", required=True)

    def cmd(name, helptext, ident=True):
        c = g.add_parser(name, help=helptext)
        c.add_argument("program")
        if ident:
            c.add_argument("assessment", help="assessment id, e.g. asm-001")
        c.add_argument("--ts", help=argparse.SUPPRESS)
        return c

    c = cmd("create", "issue an assessment from the Examiner's draft (task + private rubric)", ident=False)
    c.add_argument("--file", required=True, help="draft YAML, or - for stdin")
    c.add_argument("--review", help="review session id (default: the open lesson, else the open review session)")
    cmd("show", "learner-facing task only (never the rubric or key)")
    c = cmd("hint", "record help given before submission (makes the attempt assisted)")
    c.add_argument("--level", required=True, choices=["hint-1", "hint-2", "hint-3", "hint-4", "worked-example", "explained"])
    c.add_argument("--note")
    c = cmd("submit", "record the learner's final answer")
    c.add_argument("--answer", help="answer text")
    c.add_argument("--file", help="YAML with `answer` and/or `responses` (item id -> text), or - for stdin")
    cmd("brief", "Examiner brief with the private rubric (refuses before a submission exists)")
    c = cmd("grade", "record the Examiner's grading (validated against the rubric)")
    c.add_argument("--file", required=True, help="grading YAML, or - for stdin")
    c = cmd("review", "human review of an ambiguous grading")
    c.add_argument("--statement", help="the reviewer's decision in words")
    c.add_argument("--credit", action="append", default=[], metavar="CRITERION=CREDIT", help="adjust a judged criterion (0-1)")
    c.add_argument("--confirm", action="store_true", help="only after the human actually decided")
    cmd("commit", "append the graded result to the evidence log (idempotent)")
    c = cmd("void", "withdraw an uncommitted assessment")
    c.add_argument("--reason")
    cmd("status", "open assessments and their next step", ident=False)

    r = sub.add_parser("review", help="spaced-repetition review: due/start/brief/status/skip/complete/abandon")
    g = r.add_subparsers(dest="vcmd", required=True)

    def rcmd(name, helptext):
        c = g.add_parser(name, help=helptext)
        c.add_argument("program")
        c.add_argument("--ts", help=argparse.SUPPRESS)
        return c

    rcmd("due", "what is due, prioritized, within the daily limit (writes nothing)").add_argument("--today")
    c = rcmd("start", "open a review session for today's queue (idempotent)")
    c.add_argument("--today")
    c.add_argument("--provider", choices=["claude", "codex", "other"])
    c.add_argument("--thread")
    rcmd("brief", "minimal context pack for the open review session").add_argument("--max-chars", type=int)
    rcmd("status", "items and their next step")
    c = rcmd("skip", "skip one item with a reason")
    c.add_argument("--competency", required=True)
    c.add_argument("--reason", required=True)
    rcmd("complete", "finish the session (all items committed or skipped) and print its summary")
    c = rcmd("abandon", "abandon the open review session")
    c.add_argument("--reason")
    c.add_argument("--confirm", action="store_true")


def _assess(args) -> int:
    root, c, pid = args.root, args.acmd, args.program
    if c == "create":
        task, what = assessment.create(root, pid, _read_patch(args), review_session=args.review, ts=args.ts)
        print(what)
        print(assessment.render_task(task))
        print("next: show the learner ONLY the task above; they answer without help, then `assess submit`")
    elif c == "show":
        print(assessment.show(root, pid, args.assessment))
    elif c == "hint":
        t = assessment.hint(root, pid, args.assessment, args.level, args.note, args.ts)
        print(f"{t['id']}: assistance now {t['attempt']['assistance']}; this attempt is ASSISTED and will not count as independent evidence")
    elif c == "submit":
        if args.file:
            body = _read_patch(args)
            if not isinstance(body, dict) or set(body) - {"answer", "responses"}:
                raise ValueError("submission file must be a mapping with `answer` and/or `responses`")
            t, what = assessment.submit(root, pid, args.assessment, str(body.get("answer", "")), body.get("responses"), args.ts)
        else:
            t, what = assessment.submit(root, pid, args.assessment, args.answer or "", None, args.ts)
        print(what)
        print(f"next: `assess brief {pid} {t['id']}` for the Examiner")
    elif c == "brief":
        print(assessment.brief(root, pid, args.assessment))
    elif c == "grade":
        t, what = assessment.grade(root, pid, args.assessment, _read_patch(args), args.ts)
        print(what)
    elif c == "review":
        credits = {}
        for item in args.credit:
            k, _, v = item.partition("=")
            credits[k] = float(v)
        t, what = assessment.review_human(root, pid, args.assessment, confirm=args.confirm, statement=args.statement, credits=credits, ts=args.ts)
        print(what)
    elif c == "commit":
        t, what = assessment.commit(root, pid, args.assessment, args.ts)
        print(what)
    elif c == "void":
        t, what = assessment.void(root, pid, args.assessment, args.reason or "", args.ts)
        print(what)
    elif c == "status":
        print(assessment.status_text(root, pid))
    return 0


def _review(args) -> int:
    root, c, pid = args.root, args.vcmd, args.program
    if c == "due":
        today = date.fromisoformat(args.today) if args.today else date.today()
        print(review.format_queue(review.queue(root, pid, today), today))
    elif c == "start":
        today = date.fromisoformat(args.today) if args.today else None
        rs, what = review.start(root, pid, today=today, provider=args.provider, thread=args.thread, ts=args.ts)
        print(what)
        print(review.status_text(root, pid))
        print(f"next: `review brief {pid}` is the briefing for this conversation")
    elif c == "brief":
        print(review.brief(root, pid, args.max_chars))
    elif c == "status":
        print(review.status_text(root, pid))
    elif c == "skip":
        review.skip(root, pid, args.competency, args.reason, args.ts)
        print(f"skipped {args.competency}")
    elif c == "complete":
        rs, what = review.complete(root, pid, args.ts)
        print(what)
        print(rs["summary"])
        print("next: tell the learner the review is done; start any lesson in a NEW conversation")
    elif c == "abandon":
        rs, what = review.abandon(root, pid, reason=args.reason, confirm=args.confirm, ts=args.ts)
        print(what)
    return 0


def _lesson_parsers(sub) -> None:
    ls = sub.add_parser("lesson", help="lesson lifecycle: next/start/status/brief/note/pause/resume/complete/abandon")
    g = ls.add_subparsers(dest="lcmd", required=True)

    def cmd(name, helptext, *flags):
        c = g.add_parser(name, help=helptext)
        c.add_argument("program")
        for f in flags:
            if f == "ts":
                c.add_argument("--ts", help=argparse.SUPPRESS)
            elif f == "provider":
                c.add_argument("--provider", choices=["claude", "codex", "other"], help="which desktop app hosts this conversation")
                c.add_argument("--thread", help="the conversation's reference/title, if the app exposes one")
            elif f == "select":
                c.add_argument("--objective", help="learner-chosen objective ref; default is the recommendation")
                c.add_argument("--override-rationale", help="why unmet prerequisites are being skipped")
                c.add_argument("--statement", help="the learner's approving words for the override")
                c.add_argument("--confirm", action="store_true", help="only after the learner agreed in chat")
            elif f == "file":
                c.add_argument("--file", required=True, help="YAML file, or - for stdin")
        return c

    cmd("next", "recommend the next objective (writes nothing)")
    cmd("start", "plan (if needed) and activate a lesson; idempotent", "select", "provider", "ts")
    cmd("status", "open lesson and recent history")
    cmd("brief", "resume brief for the open lesson (the context pack)").add_argument("--max-chars", type=int)
    cmd("note", "record concepts/attempts/misconceptions/questions during the lesson", "file", "ts")
    cmd("pause", "pause the active lesson", "ts").add_argument("--note")
    cmd("resume", "resume a paused lesson in this conversation", "provider", "ts").add_argument("--takeover", action="store_true", help="the lesson is active in a conversation that no longer exists")
    cmd("await-assessment", "instruction done; independent assessment still pending (see `assess`)", "ts")
    c = cmd("complete", "close the lesson: write the record, refresh derived state", "ts")
    c.add_argument("--file", help="closure YAML (summary, handoff, next_action, ...), or - for stdin; optional only when finishing an interrupted close")
    c.add_argument("--outcome", choices=["completed", "partial"], default="completed")
    c = cmd("abandon", "abandon the lesson (needs learner confirmation)", "ts")
    c.add_argument("--reason")
    c.add_argument("--confirm", action="store_true", help="only after the learner said yes in chat")


def _lesson(args) -> int:
    root, c, pid = args.root, args.lcmd, args.program
    if c == "next":
        rec = lifecycle.recommend(root, pid)
        print(lifecycle.format_recommendation(rec))
        return 0 if rec["pick"] else 1
    if c == "status":
        print(lifecycle.status_text(root, pid))
        return 0
    if c == "brief":
        if lifecycle.open_session(root, pid) is None:
            raise ValueError("no open lesson; use `lesson next` / `lesson start`")
        print(model.build_context(root, pid, max_chars=args.max_chars))
        return 0
    if c == "start":
        doc, what = lifecycle.start_lesson(root, pid, objective=args.objective, override_rationale=args.override_rationale,
                                           statement=args.statement, confirm=args.confirm, provider=args.provider,
                                           thread=args.thread, ts=args.ts)
        print(f"{doc['id']}: {what}")
        print("\n".join(lifecycle._session_lines(doc)))
        print("next: `lesson brief` for the briefing, then teach (protocol 08)")
        return 0
    if c == "resume":
        doc, what = lifecycle.resume_lesson(root, pid, provider=args.provider, thread=args.thread, takeover=args.takeover, ts=args.ts)
    elif c == "pause":
        doc, what = lifecycle.pause_lesson(root, pid, note=args.note, ts=args.ts)
    elif c == "await-assessment":
        doc, what = lifecycle.await_assessment(root, pid, ts=args.ts)
    elif c == "note":
        doc = lifecycle.add_notes(root, pid, _read_patch(args), args.ts)
        what = "notes recorded"
    elif c == "complete":
        doc, what = lifecycle.complete_lesson(root, pid, _read_patch(args) if args.file else None, outcome=args.outcome, ts=args.ts)
    elif c == "abandon":
        doc, what = lifecycle.abandon_lesson(root, pid, reason=args.reason, confirm=args.confirm, ts=args.ts)
    print(f"{doc['id']}: {what} (status {doc['status']})")
    if c == "await-assessment":
        print(assessment.status_text(root, pid))
        print("next: independent assessments via `assess create/submit/grade/commit` (protocol 09), then `lesson complete`")
    if c in ("complete", "abandon"):
        cl = doc["closure"]
        print(f"assessment: {cl['assessment']['status']}"
              + (" (instruction only; mastery unchanged)" if cl["assessment"]["status"] == "not_assessed" else ""))
        print("next: tell the learner to start the next lesson in a NEW conversation")
    return 0


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
            print(model.build_context(args.root, args.program, today, max_chars=args.max_chars, objective=args.objective))
            return 0
        if args.cmd == "lesson":
            return _lesson(args)
        if args.cmd == "assess":
            return _assess(args)
        if args.cmd == "review":
            return _review(args)
        if args.cmd == "progress":
            print(review.progress_text(args.root, args.program, date.fromisoformat(args.today) if args.today else None))
            return 0
        if args.cmd == "programs":
            for pid in model.list_programs(args.root):
                try:
                    prog = miniyaml.loads((model.program_dir(args.root, pid) / "program.yaml").read_text("utf-8"))
                    cur = lifecycle.open_session(args.root, pid)
                    rv = review.open_session(args.root, pid)
                    print(f"{pid}: {prog['title']} [{prog['status']}]"
                          + (f"; open lesson {cur['id']} {cur['status']} on {cur['objectives'][0]}" if cur else "")
                          + (f"; open review {rv['id']}" if rv else ""))
                except (ValueError, OSError):
                    print(f"{pid}: (unreadable; run `validate`)")
            return 0
        if args.cmd == "log":
            extra = {k: v for k, v in (("independence", args.independence), ("assistance", args.assistance),
                                       ("review_session", args.review_session)) if v}
            ev = model.append_event(args.root, args.program, lesson=args.lesson, competency=args.competency,
                                    kind=args.kind, score=args.score, notes=args.notes, ts=args.ts, extra=extra)
            print(json.dumps(ev, ensure_ascii=False))
            if "independence" not in ev:
                print("note: unclassified (legacy) event: counts toward score/proficient, never toward strict `mastered`. "
                      "Use the `assess` workflow for evidence that can support mastery.", file=sys.stderr)
            return 0
        if args.cmd == "rebuild":
            return _print_report(model.rebuild(args.root, args.program), False)
        if args.cmd == "close":
            return _print_report(model.close_lesson(args.root, args.program, args.lesson), False)
    except (ValueError, OSError, miniyaml.YamlError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2
