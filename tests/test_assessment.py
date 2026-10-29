"""Phase 6: assessment workflow, evidence-backed mastery, review scheduling, misconceptions, context, reliability.

These are CLI/library tests on synthetic abstract data. They do not exercise the Claude or Codex desktop apps.
"""
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date

import helpers
from helpers import PID, REPO, TmpRootCase
from learning_os import assessment, cli, evidence, lifecycle, miniyaml, model, review

SECRET = "SECRETKEY-do-not-leak"
STRICT = "evidence_policy:\n  mode: strict\nreview_policy:\n  intervals: [1, 3, 7, 14, 30]\n  max_per_day: 5\n"


def run(root, *argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(["--root", str(root), *argv])
    return code, out.getvalue(), err.getvalue()


def draft(task_id="t-one", type="recall", comp="fixture-a", difficulty="medium", judged=True, prompt=None, key=SECRET):
    crit = [{"id": "sum", "kind": "objective", "weight": 1, "description": "correct sum", "item": "q1",
             "check": {"type": "number", "value": 5}}]
    if judged:
        crit.append({"id": "why", "kind": "judged", "weight": 1, "description": "gives the reason",
                     "full": "states the reason", "partial": "vague", "zero": "none"})
    return {"task_id": task_id, "type": type, "competency": comp, "difficulty": difficulty, "title": f"Task {task_id}",
            "prompt": prompt or f"Answer from memory ({task_id}).",
            "items": [{"id": "q1", "prompt": "What is 2+3?"}, {"id": "q2", "prompt": "Why?"}],
            "rubric": {"answer_key": key, "criteria": crit}}


def grading(credit=1.0, confidence="high", **extra):
    return {"criteria": {"why": {"credit": credit, "evidence": "quoted the reason"}}, "feedback": "ok",
            "confidence": confidence, "uncertainty": "none", **extra}


class Base(TmpRootCase):
    def setUp(self):
        super().setUp()
        with (self.pdir / "program.yaml").open("a", encoding="utf-8") as fh:
            fh.write(STRICT)
        model.rebuild(self.root, PID)
        self.n = 0

    def tick(self, ts):
        return ts

    def lesson(self, ts="2026-02-01T09:00:00Z"):
        doc, _ = lifecycle.start_lesson(self.root, PID, ts=ts)
        return doc

    def full(self, d, ts, *, answer="5", why="because", g=None, hint=None, commit=True):
        """create -> (hint) -> submit -> grade -> commit. Returns the final task. ts is YYYY-MM-DD."""
        t, _ = assessment.create(self.root, PID, d, ts=f"{ts}T09:00:00Z")
        aid = t["id"]
        if hint:
            assessment.hint(self.root, PID, aid, hint, ts=f"{ts}T09:01:00Z")
        assessment.submit(self.root, PID, aid, "", {"q1": answer, "q2": why}, ts=f"{ts}T09:02:00Z")
        assessment.grade(self.root, PID, aid, g or grading(), ts=f"{ts}T09:03:00Z")
        if commit:
            assessment.commit(self.root, PID, aid, ts=f"{ts}T09:04:00Z")
        return assessment.load_task(self.root, PID, aid)

    def events(self):
        return [{k: v for k, v in e.items()} for e in model.read_events(self.pdir / "logs" / "assessments.jsonl")[0]]

    def mastery(self, cid="fixture-a"):
        return miniyaml.loads((self.pdir / "state" / "mastery.yaml").read_text("utf-8"))["competencies"][cid]

    def evstate(self):
        return miniyaml.loads((self.pdir / "state" / "evidence.yaml").read_text("utf-8"))

    def log(self, cid, score, ts, **extra):
        return model.append_event(self.root, PID, lesson=1, competency=cid, kind="quiz", score=score, ts=ts,
                                  extra={"independence": "independent", **extra})

    def strict_validate(self):
        rep = model.validate_root(self.root)
        self.assertEqual((rep.errors, rep.warnings), ([], []))


# --------------------------------------------------------------------------
class RubricAndCreation(Base):
    def test_valid_draft_creates_task_and_private_key(self):
        self.lesson()
        t = self.full(draft(), "2026-02-01", commit=False)
        self.assertEqual(t["status"], "graded")
        self.assertTrue((self.pdir / "assessments" / "asm-001" / "private.yaml").is_file())
        self.assertNotIn(SECRET, (self.pdir / "assessments" / "asm-001" / "task.yaml").read_text("utf-8"))

    def test_rubric_validation(self):
        self.lesson()
        bad = draft()
        bad["rubric"]["criteria"][1].pop("zero")
        with self.assertRaisesRegex(ValueError, "needs `zero`"):
            assessment.create(self.root, PID, bad)
        bad = draft()
        bad["rubric"]["criteria"][0].pop("check")
        with self.assertRaisesRegex(ValueError, "needs a `check`"):
            assessment.create(self.root, PID, bad)
        bad = draft()
        bad["rubric"]["criteria"][0]["item"] = "nope"
        with self.assertRaisesRegex(ValueError, "needs `item`"):
            assessment.create(self.root, PID, bad)
        bad = draft()
        bad["rubric"]["criteria"][1]["id"] = "sum"
        with self.assertRaisesRegex(ValueError, "duplicate criterion"):
            assessment.create(self.root, PID, bad)
        bad = draft()
        bad["rubric"]["criteria"][0]["check"] = {"type": "regex", "pattern": "("}
        with self.assertRaisesRegex(ValueError, "bad regex"):
            assessment.create(self.root, PID, bad)
        bad = draft()
        bad["rubric"]["criteria"] = []
        with self.assertRaises(ValueError):
            assessment.create(self.root, PID, bad)
        self.assertFalse((self.pdir / "assessments").exists() and any((self.pdir / "assessments").iterdir()))

    def test_invalid_references_are_rejected(self):
        self.lesson()
        with self.assertRaisesRegex(ValueError, "unknown competency"):
            assessment.create(self.root, PID, draft(comp="no-such"))
        d = draft()
        d["objective"] = "fixture-a:missing"
        with self.assertRaisesRegex(ValueError, "unknown objective"):
            assessment.create(self.root, PID, d)
        d["objective"] = "fixture-b:overall"
        with self.assertRaisesRegex(ValueError, "does not belong"):
            assessment.create(self.root, PID, d)
        d = draft()
        d["surprise"] = 1
        with self.assertRaisesRegex(ValueError, "keys from"):
            assessment.create(self.root, PID, d)

    def test_needs_a_lesson_or_review_context(self):
        with self.assertRaisesRegex(ValueError, "no active lesson and no open review"):
            assessment.create(self.root, PID, draft())

    def test_task_id_is_idempotent_and_conflicts_on_change(self):
        self.lesson()
        a, _ = assessment.create(self.root, PID, draft())
        b, what = assessment.create(self.root, PID, draft())
        self.assertEqual((a["id"], "no change" in what), (b["id"], True))
        changed = draft(prompt="A different prompt entirely")
        with self.assertRaises(assessment.Conflict):
            assessment.create(self.root, PID, changed)

    def test_same_prompt_cannot_be_reused_under_a_new_task_id(self):
        self.lesson()
        assessment.create(self.root, PID, draft("t-one", prompt="Same words"))
        with self.assertRaisesRegex(ValueError, "do not reuse"):
            assessment.create(self.root, PID, draft("t-two", prompt="same   WORDS"))

    def test_delayed_review_needs_earlier_independent_pass(self):
        self.lesson()
        with self.assertRaisesRegex(ValueError, "nothing to review"):
            assessment.create(self.root, PID, draft("t-d", "delayed_review", "fixture-b"), ts="2026-02-02T09:00:00Z")


# --------------------------------------------------------------------------
class IsolationAndGrading(Base):
    def test_key_is_not_revealed_before_submission_or_in_learner_views(self):
        self.lesson()
        t, _ = assessment.create(self.root, PID, draft())
        with self.assertRaisesRegex(ValueError, "not revealed before"):
            assessment.brief(self.root, PID, t["id"])
        shown = assessment.show(self.root, PID, t["id"])
        for text in (shown, model.build_context(self.root, PID, date(2026, 2, 2)), assessment.status_text(self.root, PID)):
            self.assertNotIn(SECRET, text)
            self.assertNotIn("states the reason", text)
        assessment.submit(self.root, PID, t["id"], "a", {"q1": "5"})
        self.assertIn(SECRET, assessment.brief(self.root, PID, t["id"]))

    def test_review_brief_never_contains_keys(self):
        self.log("fixture-a", 0.8, "2026-02-01T09:00:00Z")
        review.start(self.root, PID, today=date(2026, 2, 5))
        rs = review.open_session(self.root, PID)
        assessment.create(self.root, PID, draft(), review_session=rs["id"], ts="2026-02-05T09:00:00Z")
        text = review.brief(self.root, PID)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("states the reason", text)
        self.assertIn("Task t-one", text)  # used-item titles are listed so they are not reused

    def test_objective_checks_cannot_be_overridden_and_judged_needs_evidence(self):
        self.lesson()
        t, _ = assessment.create(self.root, PID, draft())
        assessment.submit(self.root, PID, t["id"], "", {"q1": "7", "q2": "x"})
        with self.assertRaisesRegex(ValueError, "cannot override"):
            assessment.grade(self.root, PID, t["id"], {**grading(), "criteria": {"sum": {"credit": 1.0}, "why": {"credit": 1, "evidence": "e"}}})
        g = grading()
        g["criteria"]["why"]["evidence"] = " "
        with self.assertRaisesRegex(ValueError, "evidence is required"):
            assessment.grade(self.root, PID, t["id"], g)
        with self.assertRaisesRegex(ValueError, "needs a credit"):
            assessment.grade(self.root, PID, t["id"], {"criteria": {}, "feedback": "x", "confidence": "high"})
        with self.assertRaisesRegex(ValueError, "unknown criteria"):
            assessment.grade(self.root, PID, t["id"], {**grading(), "criteria": {"ghost": {"credit": 1}}})
        _, what = assessment.grade(self.root, PID, t["id"], grading(0.5))
        self.assertIn("0.25", what)  # wrong sum (0) + half credit on the judged criterion, equal weights

    def test_objective_only_task_is_auto_graded(self):
        self.lesson()
        t, _ = assessment.create(self.root, PID, draft(judged=False))
        assessment.submit(self.root, PID, t["id"], "", {"q1": "about 5.0"})
        assessment.grade(self.root, PID, t["id"], {"feedback": "auto"})
        t = assessment.load_task(self.root, PID, t["id"])
        self.assertEqual((t["grading"]["method"], t["grading"]["score"], t["status"]), ("auto", 1.0, "graded"))

    def test_low_confidence_needs_human_review_before_commit(self):
        self.lesson()
        t = self.full(draft(), "2026-02-01", g=grading(0.5, "low"), commit=False)
        self.assertEqual(t["status"], "needs_review")
        with self.assertRaisesRegex(ValueError, "human review"):
            assessment.commit(self.root, PID, t["id"])
        with self.assertRaisesRegex(ValueError, "--statement"):
            assessment.review_human(self.root, PID, t["id"], confirm=False, statement=None)
        with self.assertRaisesRegex(ValueError, "not a judged"):
            assessment.review_human(self.root, PID, t["id"], confirm=True, statement="ok", credits={"sum": 0.0})
        assessment.review_human(self.root, PID, t["id"], confirm=True, statement="reviewer agrees it is correct", credits={"why": 1.0})
        assessment.commit(self.root, PID, t["id"])
        ev = self.events()[-1]
        self.assertEqual((ev["grading_method"], ev["score"], ev["confidence"]), ("human_reviewed", 1.0, "medium"))

    def test_tampering_with_the_private_rubric_is_detected(self):
        self.lesson()
        t, _ = assessment.create(self.root, PID, draft())
        assessment.submit(self.root, PID, t["id"], "", {"q1": "5", "q2": "x"})
        p = self.pdir / "assessments" / t["id"] / "private.yaml"
        p.write_text(p.read_text("utf-8").replace("value: 5", "value: 6"), "utf-8")
        with self.assertRaisesRegex(ValueError, "changed after the task was issued"):
            assessment.grade(self.root, PID, t["id"], grading())
        rep = model.validate_root(self.root)
        self.assertTrue(any("no longer matches" in e for e in rep.errors))


class SubmissionsAndAttempts(Base):
    def test_duplicate_and_conflicting_submissions(self):
        self.lesson()
        t, _ = assessment.create(self.root, PID, draft())
        assessment.submit(self.root, PID, t["id"], "", {"q1": "5"})
        _, what = assessment.submit(self.root, PID, t["id"], "", {"q1": "5"})
        self.assertIn("no change", what)
        with self.assertRaises(assessment.Conflict):
            assessment.submit(self.root, PID, t["id"], "", {"q1": "6"})
        with self.assertRaisesRegex(ValueError, "unknown item"):
            assessment.submit(self.root, PID, assessment.create(self.root, PID, draft("t-b"))[0]["id"], "", {"zz": "1"})

    def test_hints_make_the_attempt_assisted_and_it_never_counts(self):
        self.lesson()
        self.full(draft("t-i"), "2026-02-01")
        before = self.mastery()
        t = self.full(draft("t-h"), "2026-02-01", hint="hint-2")
        self.assertEqual(t["grading"]["raw_score"], 1.0)
        self.assertEqual(t["grading"]["score"], 0.7)  # capped by the assistance level
        ev = self.events()[-1]
        self.assertEqual((ev["independence"], ev["assistance"], ev["hints"]), ("assisted", "hint-2", 1))
        self.assertEqual(self.mastery(), {**before})  # assisted evidence does not move mastery
        self.assertEqual(self.evstate()["competencies"]["fixture-a"]["assisted"], 1)

    def test_help_after_submission_is_refused(self):
        self.lesson()
        t, _ = assessment.create(self.root, PID, draft())
        assessment.submit(self.root, PID, t["id"], "x")
        with self.assertRaisesRegex(ValueError, "before submission"):
            assessment.hint(self.root, PID, t["id"], "hint-1")

    def test_event_rules_reject_inconsistent_independence(self):
        for extra in ({"independence": "independent", "assistance": "hint-1"},
                      {"independence": "assisted"},
                      {"independence": "assisted", "assistance": "hint-1", "score": 0.95},
                      {"assessment_id": "asm-009"}):
            kw = {"competency": "fixture-a", "kind": "quiz", "score": extra.pop("score", 0.5), "lesson": 1, "extra": extra}
            with self.assertRaises(ValueError, msg=str(extra)):
                model.append_event(self.root, PID, ts="2026-03-01T00:00:00Z", **kw)

    def test_completed_is_not_the_same_as_valid_mastery_evidence(self):
        self.lesson()
        self.full(draft(), "2026-02-01")
        c = self.evstate()["competencies"]["fixture-a"]
        self.assertEqual((c["valid"], c["unverified"]), (1, 3))  # fixture lines are legacy/unverified
        self.assertTrue(c["mastered_blockers"])

    def test_lesson_cannot_complete_with_a_half_recorded_assessment(self):
        self.lesson()
        self.full(draft(), "2026-02-01", commit=False)
        with self.assertRaisesRegex(ValueError, "not committed"):
            lifecycle.complete_lesson(self.root, PID, {"summary": "s", "handoff": "h", "next_action": "n"})
        assessment.commit(self.root, PID, "asm-001")
        doc, _ = lifecycle.complete_lesson(self.root, PID, {"summary": "s", "handoff": "h", "next_action": "n"})
        self.assertEqual(doc["closure"]["assessment"]["status"], "logged")


# --------------------------------------------------------------------------
class MasteryTransitions(unittest.TestCase):
    """Pure-function tests of the evidence rules."""

    PROGRAM = {"id": "p", "competencies": [{"id": "c", "prerequisites": []}],
               "mastery_policy": {"ewma_alpha": 0.5, "proficient_threshold": 0.7, "mastered_threshold": 0.9, "min_evidence": 2},
               "evidence_policy": {"mode": "strict"}}

    def valid(self, score, ts, type="recall", difficulty="medium", n=[0]):
        n[0] += 1
        return {"competency": "c", "score": score, "ts": ts, "independence": "independent", "assessment_id": f"asm-{n[0]:03d}",
                "rubric_sha256": "a" * 64, "type": type, "difficulty": difficulty, "confidence": "high"}

    def status(self, events, program=None):
        return evidence.derive_mastery(program or self.PROGRAM, events)["competencies"]["c"]["status"]

    def test_levels(self):
        p = self.PROGRAM
        ev = lambda evs, exposed=False: evidence.derive_evidence(p, evs, [{"meta": {"outcome": "completed", "competencies_covered": ["c"]}}] if exposed else [])["competencies"]["c"]["level"]
        self.assertEqual(ev([]), "unseen")
        self.assertEqual(ev([], True), "exposure")
        assisted = {**self.valid(0.8, "2026-01-01T00:00:00Z"), "independence": "assisted", "assistance": "hint-1"}
        self.assertEqual(ev([assisted]), "assisted")
        self.assertEqual(ev([self.valid(0.8, "2026-01-01T00:00:00Z")]), "independent")
        retained = [self.valid(0.8, "2026-01-01T00:00:00Z"), self.valid(0.9, "2026-01-05T00:00:00Z", "delayed_review")]
        self.assertEqual(ev(retained), "retained")
        too_soon = [self.valid(0.8, "2026-01-01T00:00:00Z"), self.valid(0.9, "2026-01-02T00:00:00Z", "delayed_review")]
        self.assertEqual(ev(too_soon), "independent")

    def test_single_easy_or_single_type_evidence_is_not_mastery(self):
        easy = [self.valid(1.0, "2026-01-01T00:00:00Z", difficulty="easy"), self.valid(1.0, "2026-01-02T00:00:00Z", difficulty="easy")]
        self.assertEqual(self.status(easy), "proficient")
        one_type = [self.valid(1.0, "2026-01-01T00:00:00Z"), self.valid(1.0, "2026-01-02T00:00:00Z")]
        self.assertEqual(self.status(one_type), "proficient")
        self.assertEqual(self.status([self.valid(1.0, "2026-01-01T00:00:00Z")]), "learning")  # below min_evidence

    def test_unverified_events_reach_proficient_but_never_strict_mastered(self):
        legacy = [{"competency": "c", "score": 1.0, "ts": f"2026-01-0{i}T00:00:00Z"} for i in (1, 2, 3)]
        self.assertEqual(self.status(legacy), "proficient")
        self.assertEqual(self.status(legacy, {**self.PROGRAM, "evidence_policy": {"mode": "legacy"}}), "mastered")

    def test_full_evidence_earns_mastered(self):
        evs = [self.valid(0.95, "2026-01-01T00:00:00Z", "recall"), self.valid(0.95, "2026-01-02T00:00:00Z", "application", "hard"),
               self.valid(0.95, "2026-01-06T00:00:00Z", "delayed_review")]
        self.assertEqual(self.status(evs), "mastered")
        self.assertEqual(evidence.mastered_blockers(self.PROGRAM, evs), [])

    def test_assisted_success_never_counts(self):
        evs = [{**self.valid(0.85, "2026-01-0%dT00:00:00Z" % i), "independence": "assisted", "assistance": "hint-1"} for i in (1, 2, 3)]
        self.assertEqual(self.status(evs), "unseen")
        self.assertEqual(self.status(evs, {**self.PROGRAM, "evidence_policy": {"mode": "legacy"}}), "unseen")

    def test_transfer_requirement_is_configurable(self):
        p = {**self.PROGRAM, "evidence_policy": {"mode": "strict", "require_transfer": True}}
        evs = [self.valid(0.95, "2026-01-01T00:00:00Z", "recall"), self.valid(0.95, "2026-01-02T00:00:00Z", "application", "hard"),
               self.valid(0.95, "2026-01-06T00:00:00Z", "delayed_review")]
        self.assertEqual(self.status(evs, p), "proficient")
        self.assertEqual(self.status(evs + [self.valid(0.95, "2026-01-07T00:00:00Z", "transfer")], p), "mastered")


class LegacyCompatibility(Base):
    def test_fixture_log_is_unchanged_and_legacy_mode_keeps_old_rule(self):
        src = (helpers.FIXTURE_ROOT / "programs" / PID / "logs" / "assessments.jsonl").read_text("utf-8")
        self.assertEqual((self.pdir / "logs" / "assessments.jsonl").read_text("utf-8"), src)
        self.assertEqual(self.mastery()["status"], "proficient")
        self.assertNotIn("independence", src)

    def test_legacy_event_needs_lesson_or_review_session(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            model.append_event(self.root, PID, competency="fixture-a", kind="quiz", score=0.5, ts="2026-03-01T00:00:00Z")

    def test_missing_evidence_state_is_only_a_warning_and_rebuild_repairs_it(self):
        (self.pdir / "state" / "evidence.yaml").unlink()
        rep = model.validate_root(self.root)
        self.assertEqual(rep.errors, [])
        self.assertEqual(len(rep.warnings), 1)
        model.rebuild(self.root, PID)
        self.strict_validate()

    def test_evidence_state_drift_is_an_error(self):
        self.edit("state/evidence.yaml", "level: independent", "level: retained")
        self.assertTrue(any("drifted" in e for e in model.validate_root(self.root).errors))

    def test_log_cli_flags(self):
        code, out, err = run(self.root, "log", PID, "--lesson", "1", "--competency", "fixture-a", "--kind", "quiz", "--score", "0.5",
                             "--ts", "2026-03-01T00:00:00Z")
        self.assertEqual(code, 0)
        self.assertIn("unclassified", err)
        code, out, _ = run(self.root, "log", PID, "--lesson", "1", "--competency", "fixture-a", "--kind", "quiz", "--score", "0.5",
                           "--independence", "assisted", "--ts", "2026-03-02T00:00:00Z")
        self.assertEqual(code, 2)  # assisted must name the assistance


# --------------------------------------------------------------------------
class Scheduler(Base):
    INTERVALS = [1, 3, 7, 14, 30]

    def sched(self, events, program=None):
        p = program or {"id": "p", "competencies": [{"id": "c", "prerequisites": []}],
                        "mastery_policy": {"ewma_alpha": 0.5, "proficient_threshold": 0.7, "mastered_threshold": 0.9, "min_evidence": 1}}
        evs = [{"competency": "c", "ts": ts, "score": s, **extra} for ts, s, extra in events]
        return evidence.derive_reviews(p, evs).get("c")

    def test_ladder_advances_on_strong_passes(self):
        s = self.sched([("2026-01-01T00:00:00Z", 0.95, {}), ("2026-01-02T00:00:00Z", 0.95, {}), ("2026-01-05T00:00:00Z", 0.95, {})])
        self.assertEqual((s["stage"], s["interval_days"], s["due"]), (2, 7, "2026-01-12"))
        self.assertIn("strong pass", s["reason"])

    def test_borderline_pass_repeats_interval_once_then_advances(self):
        s = self.sched([("2026-01-01T00:00:00Z", 0.8, {}), ("2026-01-02T00:00:00Z", 0.8, {})])
        self.assertEqual((s["stage"], s["last_result"], s["due"]), (0, "held", "2026-01-03"))
        s = self.sched([("2026-01-01T00:00:00Z", 0.8, {}), ("2026-01-02T00:00:00Z", 0.8, {}), ("2026-01-03T00:00:00Z", 0.8, {})])
        self.assertEqual((s["stage"], s["last_result"], s["due"]), (1, "advanced", "2026-01-06"))

    def test_failure_drops_two_stages_and_is_recorded(self):
        s = self.sched([("2026-01-01T00:00:00Z", 0.95, {}), ("2026-01-02T00:00:00Z", 0.95, {}), ("2026-01-05T00:00:00Z", 0.95, {}),
                        ("2026-01-12T00:00:00Z", 0.2, {})])
        self.assertEqual((s["stage"], s["last_result"], s["lapses"], s["due"]), (0, "failed", 1, "2026-01-13"))
        self.assertIn("failed independent retrieval", s["reason"])

    def test_early_success_does_not_lengthen_and_assisted_is_ignored(self):
        s = self.sched([("2026-01-01T00:00:00Z", 0.95, {}), ("2026-01-01T12:00:00Z", 1.0, {})])
        self.assertEqual((s["stage"], s["due"]), (0, "2026-01-02"))
        s = self.sched([("2026-01-01T00:00:00Z", 0.95, {}), ("2026-01-02T00:00:00Z", 0.1, {"independence": "assisted", "assistance": "hint-1"})])
        self.assertEqual((s["stage"], s["lapses"]), (0, 0))

    def test_no_review_before_first_independent_pass(self):
        self.assertIsNone(self.sched([("2026-01-01T00:00:00Z", 0.3, {}), ("2026-01-02T00:00:00Z", 0.4, {})]))

    def test_custom_intervals(self):
        p = {"id": "p", "competencies": [{"id": "c", "prerequisites": []}], "review_policy": {"intervals": [2, 4]},
             "mastery_policy": {"ewma_alpha": 0.5, "proficient_threshold": 0.7, "mastered_threshold": 0.9, "min_evidence": 1}}
        s = self.sched([("2026-01-01T00:00:00Z", 0.95, {})], p)
        self.assertEqual(s["due"], "2026-01-03")

    def test_queue_overdue_missed_and_priority(self):
        # fixture-a passed on 2026-01-05 (legacy events). b passes later, c fails after passing.
        self.log("fixture-b", 0.9, "2026-02-01T00:00:00Z")
        self.log("fixture-c", 0.9, "2026-02-01T00:00:00Z")
        self.log("fixture-c", 0.2, "2026-02-10T00:00:00Z")
        q = review.queue(self.root, PID, date(2026, 2, 12))
        tiers = {e["competency"]: e["tier"] for e in q["entries"]}
        self.assertEqual(tiers["fixture-c"], "failed")
        self.assertEqual(q["entries"][0]["competency"], "fixture-c")  # failed reviews come first
        self.assertEqual(tiers["fixture-a"], "prerequisite-critical")  # blocks b/c? b is proficient-learning: see below
        a = next(e for e in q["entries"] if e["competency"] == "fixture-a")
        self.assertGreater(a["overdue_days"], 30)
        self.assertIn("MISSED", a["reason"])

    def test_overdue_beats_due_and_ordering_is_stable(self):
        self.log("fixture-a", 0.95, "2026-02-01T00:00:00Z")   # stage 1 (3 days): due 02-04
        self.log("fixture-b", 0.95, "2026-02-03T00:00:00Z")   # due 02-04
        self.log("fixture-c", 0.95, "2026-02-03T00:00:00Z")   # due 02-04
        q = review.queue(self.root, PID, date(2026, 2, 6))
        self.assertEqual(len(q["entries"]), 3)
        tiers = [review.TIERS.index(e["tier"]) for e in q["entries"]]
        self.assertEqual(tiers, sorted(tiers))
        self.assertEqual(q, review.queue(self.root, PID, date(2026, 2, 6)))  # deterministic

    def test_daily_workload_limit_defers_the_rest(self):
        for cid in ("fixture-a", "fixture-b", "fixture-c"):
            self.log(cid, 0.95, "2026-02-01T00:00:00Z")
        self.edit("program.yaml", "max_per_day: 5", "max_per_day: 2")
        model.rebuild(self.root, PID)
        q = review.queue(self.root, PID, date(2026, 2, 5))
        self.assertEqual((len(q["shown"]), len(q["deferred"]), q["cap"]), (2, 1, 2))
        rs, _ = review.start(self.root, PID, today=date(2026, 2, 5))
        self.assertEqual(len(rs["items"]), 2)
        for i in rs["items"]:
            review.skip(self.root, PID, i["competency"], "no time")
        review.complete(self.root, PID)
        # assigned work counts against the day even when skipped: no second batch, and skipped items wait for tomorrow
        self.assertEqual(review.queue(self.root, PID, date(2026, 2, 5))["remaining"], 0)
        with self.assertRaisesRegex(ValueError, "no reviews to assign"):
            review.start(self.root, PID, today=date(2026, 2, 5))
        tomorrow = review.queue(self.root, PID, date(2026, 2, 6))
        self.assertEqual(len(tomorrow["shown"]), 2)

    def test_time_budget_comes_from_the_program(self):
        self.edit("program.yaml", "target_minutes: 30", "target_minutes: 10")
        self.assertEqual(review.budget(model._load_valid_program(self.root, PID)), 2)  # 10 min / 5 min per item

    def test_rescheduling_after_a_committed_review(self):
        self.log("fixture-b", 0.95, "2026-02-01T00:00:00Z")
        self.assertEqual(self.evstate()["reviews"]["fixture-b"]["due"], "2026-02-02")
        self.log("fixture-b", 0.95, "2026-02-02T00:00:00Z")
        r = self.evstate()["reviews"]["fixture-b"]
        self.assertEqual((r["stage"], r["due"]), (1, "2026-02-05"))
        q = review.queue(self.root, PID, date(2026, 2, 4))
        self.assertNotIn("fixture-b", [e["competency"] for e in q["entries"]])

    def test_deterministic_rebuild(self):
        for i, s in enumerate([0.9, 0.8, 0.3, 0.95]):
            self.log("fixture-b", s, f"2026-02-0{i + 1}T00:00:00Z", misconceptions=[{"text": "mixes up x and y", "status": "demonstrated"}])
        first = (self.pdir / "state" / "evidence.yaml").read_text("utf-8")
        m1 = (self.pdir / "state" / "mastery.yaml").read_text("utf-8")
        (self.pdir / "state" / "evidence.yaml").unlink()
        (self.pdir / "state" / "mastery.yaml").unlink()
        model.rebuild(self.root, PID)
        self.assertEqual(first, (self.pdir / "state" / "evidence.yaml").read_text("utf-8"))
        self.assertEqual(m1, (self.pdir / "state" / "mastery.yaml").read_text("utf-8"))
        self.strict_validate()


# --------------------------------------------------------------------------
class ReviewSessions(Base):
    def prime(self):
        self.log("fixture-a", 0.95, "2026-02-01T00:00:00Z")
        return review.start(self.root, PID, today=date(2026, 2, 5), provider="claude", ts="2026-02-05T08:00:00Z")[0]

    def test_start_is_idempotent_and_does_not_touch_lessons(self):
        lessons_before = sorted(p.name for p in (self.pdir / "lessons").iterdir())
        rs = self.prime()
        again, what = review.start(self.root, PID, today=date(2026, 2, 5))
        self.assertEqual((rs["id"], again["id"], "already open" in what), ("review-001", "review-001", True))
        self.assertEqual(sorted(p.name for p in (self.pdir / "lessons").iterdir()), lessons_before)
        self.assertFalse((self.pdir / "sessions").exists())  # no lesson session was created
        self.assertIsNone(lifecycle.open_session(self.root, PID))
        self.strict_validate()

    def test_review_runs_end_to_end_and_updates_schedule(self):
        rs = self.prime()
        t, _ = assessment.create(self.root, PID, draft("t-r", "delayed_review"), review_session=rs["id"], ts="2026-02-05T09:00:00Z")
        self.assertEqual(t["review_session"], "review-001")
        with self.assertRaisesRegex(ValueError, "not finished"):
            review.complete(self.root, PID)
        assessment.submit(self.root, PID, t["id"], "", {"q1": "5", "q2": "x"}, ts="2026-02-05T09:02:00Z")
        assessment.grade(self.root, PID, t["id"], grading(1.0), ts="2026-02-05T09:03:00Z")
        assessment.commit(self.root, PID, t["id"], ts="2026-02-05T09:04:00Z")
        ev = self.events()[-1]
        self.assertEqual((ev["review_session"], ev["type"], ev["kind"], "lesson" in ev), ("review-001", "delayed_review", "review", False))
        r = self.evstate()["reviews"]["fixture-a"]
        self.assertEqual((r["stage"], r["last_result"]), (2, "advanced"))  # fixture pass + 02-01 pass + this retrieval
        _, what = review.complete(self.root, PID)
        self.assertIn("completed", what)
        summary = review.all_sessions(self.root, PID)[0]["summary"]
        self.assertIn("passed independently", summary)
        self.strict_validate()

    def test_duplicate_review_assignment_is_prevented(self):
        rs = self.prime()
        assessment.create(self.root, PID, draft("t-r1", "delayed_review"), review_session=rs["id"], ts="2026-02-05T09:00:00Z")
        with self.assertRaises(review.Conflict):
            assessment.create(self.root, PID, draft("t-r2", "delayed_review", prompt="Another prompt"), review_session=rs["id"],
                              ts="2026-02-05T09:01:00Z")
        # a voided task frees the slot
        assessment.void(self.root, PID, "asm-001", "bad item")
        assessment.create(self.root, PID, draft("t-r2", "delayed_review", prompt="Another prompt"), review_session=rs["id"],
                          ts="2026-02-05T09:02:00Z")
        # competencies in an open session are excluded from a new queue
        self.assertEqual(review.queue(self.root, PID, date(2026, 2, 5))["shown"], [])

    def test_failed_review_is_prioritized_next_time(self):
        rs = self.prime()
        t = self.full(draft("t-f", "delayed_review"), "2026-02-05", why="?", g=grading(0.0))
        self.assertLess(t["grading"]["score"], 0.7)
        r = self.evstate()["reviews"]["fixture-a"]
        self.assertEqual((r["last_result"], r["lapses"]), ("failed", 1))
        review.complete(self.root, PID)
        q = review.queue(self.root, PID, date(2026, 2, 6))
        self.assertEqual(q["entries"][0]["tier"], "failed")

    def test_skip_abandon_and_confirmations(self):
        rs = self.prime()
        with self.assertRaisesRegex(ValueError, "--reason"):
            review.skip(self.root, PID, "fixture-a", "")
        review.skip(self.root, PID, "fixture-a", "learner is out of time")
        with self.assertRaisesRegex(ValueError, "--confirm"):
            review.abandon(self.root, PID, reason="x", confirm=False)
        review.abandon(self.root, PID, reason="learner stopped", confirm=True)
        self.assertIsNone(review.open_session(self.root, PID))
        self.strict_validate()

    def test_assisted_review_keeps_the_item_due(self):
        self.prime()
        self.full(draft("t-a", "delayed_review"), "2026-02-05", hint="hint-1")
        q = review.queue(self.root, PID, date(2026, 2, 6))
        self.assertIn("fixture-a", [e["competency"] for e in q["entries"]])

    def test_nothing_due_is_a_clean_message(self):
        with self.assertRaisesRegex(ValueError, "no reviews to assign"):
            review.start(self.root, PID, today=date(2026, 1, 5))


# --------------------------------------------------------------------------
class Misconceptions(Base):
    TEXT = "believes the order of operands never matters"

    def valid_ev(self, ts, score=0.9, difficulty="medium", **extra):
        return {"competency": "fixture-a", "score": score, "ts": ts, "independence": "independent", "assessment_id": "asm-001",
                "rubric_sha256": "a" * 64, "difficulty": difficulty, "type": "recall", "confidence": "high", **extra}

    def derive(self, events):
        p = model._load_valid_program(self.root, PID)
        return evidence.derive_misconceptions(p, events)

    def test_suspected_then_demonstrated_then_resolved_then_recurring(self):
        mid = evidence.misconception_id("fixture-a", self.TEXT)
        evs = [self.valid_ev("2026-01-01T00:00:00Z", 0.4, misconceptions=[{"text": self.TEXT, "status": "suspected"}])]
        self.assertEqual(self.derive(evs)[mid]["status"], "suspected")
        evs.append(self.valid_ev("2026-01-02T00:00:00Z", 0.4, misconceptions=[{"text": self.TEXT, "status": "demonstrated"}]))
        self.assertEqual(self.derive(evs)[mid]["status"], "demonstrated")
        evs.append(self.valid_ev("2026-01-03T00:00:00Z", 0.9, resolves=[self.TEXT]))
        got = self.derive(evs)[mid]
        self.assertEqual((got["status"], got["recurrences"]), ("resolved", 0))
        evs.append(self.valid_ev("2026-01-04T00:00:00Z", 0.4, misconceptions=[{"text": self.TEXT.upper(), "status": "demonstrated"}]))
        got = self.derive(evs)[mid]
        self.assertEqual((got["status"], got["recurrences"], got["demonstrated"]), ("demonstrated", 1, 2))
        self.assertNotIn("resolved_by", got)

    def test_unsupported_resolutions_are_ignored_and_counted(self):
        mid = evidence.misconception_id("fixture-a", self.TEXT)
        shown = self.valid_ev("2026-01-01T00:00:00Z", 0.3, misconceptions=[{"text": self.TEXT, "status": "demonstrated"}])
        for bad in (self.valid_ev("2026-01-02T00:00:00Z", 0.9, difficulty="easy", resolves=[self.TEXT]),
                    self.valid_ev("2026-01-02T00:00:00Z", 0.5, resolves=[self.TEXT]),
                    {**self.valid_ev("2026-01-02T00:00:00Z", 0.9, resolves=[self.TEXT]), "independence": "assisted", "assistance": "hint-1"},
                    {k: v for k, v in self.valid_ev("2026-01-02T00:00:00Z", 0.9, resolves=[self.TEXT]).items() if k != "assessment_id"}):
            got = self.derive([shown, bad])[mid]
            self.assertEqual(got["status"], "demonstrated", bad)

    def test_assisted_attempts_can_only_suspect(self):
        mid = evidence.misconception_id("fixture-a", self.TEXT)
        ev = {**self.valid_ev("2026-01-01T00:00:00Z", 0.4, misconceptions=[{"text": self.TEXT, "status": "demonstrated"}]),
              "independence": "assisted", "assistance": "hint-1"}
        got = self.derive([ev])[mid]
        self.assertEqual((got["status"], got["demonstrated"]), ("suspected", 0))

    def test_commit_refuses_an_unsupported_resolution_and_end_to_end_resolution_works(self):
        self.lesson()
        self.full(draft("t-1"), "2026-02-01", g=grading(0.3, "high", misconceptions=[{"text": self.TEXT, "status": "demonstrated"}]))
        t = self.full(draft("t-2", difficulty="easy"), "2026-02-02", g=grading(1.0, resolves=[self.TEXT]), commit=False)
        with self.assertRaisesRegex(ValueError, "cannot resolve"):
            assessment.commit(self.root, PID, t["id"])
        assessment.void(self.root, PID, t["id"], "easy items cannot resolve")
        self.full(draft("t-3", difficulty="hard"), "2026-02-03", g=grading(1.0, resolves=[self.TEXT]))
        mc = next(iter(self.evstate()["misconceptions"].values()))
        self.assertEqual((mc["status"], mc["demonstrated"]), ("resolved", 1))
        self.assertIn("resolved_by", mc)
        self.strict_validate()

    def test_assisted_attempt_cannot_resolve_at_grading(self):
        self.lesson()
        t, _ = assessment.create(self.root, PID, draft())
        assessment.hint(self.root, PID, t["id"], "hint-1")
        assessment.submit(self.root, PID, t["id"], "x", {"q1": "5"})
        with self.assertRaisesRegex(ValueError, "assisted attempt cannot resolve"):
            assessment.grade(self.root, PID, t["id"], grading(1.0, resolves=[self.TEXT]))

    def test_recurring_misconceptions_come_first_in_context(self):
        self.lesson()
        other = "thinks every sum is odd"
        for i, (text, n) in enumerate([(other, 1), (self.TEXT, 2)]):
            for k in range(n):
                self.log("fixture-a", 0.4, f"2026-02-0{i * 2 + k + 1}T00:00:00Z", misconceptions=[{"text": text, "status": "demonstrated"}])
        self.log("fixture-a", 0.4, "2026-02-09T00:00:00Z", misconceptions=[{"text": self.TEXT, "status": "demonstrated"}])
        ctx = model.build_context(self.root, PID, date(2026, 2, 10))
        self.assertIn("## Weak competencies and evidence-backed misconceptions", ctx)
        self.assertLess(ctx.index(self.TEXT), ctx.index(other))


# --------------------------------------------------------------------------
class ContextAndProgress(Base):
    def test_lesson_context_has_reviews_gaps_and_assessment_requirements(self):
        self.lesson()
        self.log("fixture-b", 0.4, "2026-02-01T00:00:00Z")
        t, _ = assessment.create(self.root, PID, draft())
        ctx = model.build_context(self.root, PID, date(2026, 2, 20))
        self.assertIn("## Reviews due", ctx)
        self.assertIn("## Assessment requirements", ctx)
        self.assertIn(f"`{t['id']}` recall on `fixture-a` is issued", ctx)
        self.assertNotIn(SECRET, ctx)

    def test_context_respects_the_size_limit_by_shrinking_optional_blocks(self):
        self.lesson()
        big = model.build_context(self.root, PID, date(2026, 2, 20))
        small = model.build_context(self.root, PID, date(2026, 2, 20), max_chars=len(big) - 300)
        self.assertIn("Size limit", small)
        self.assertIn("## Assessment requirements", small)  # required block survives

    def test_old_assessments_of_other_competencies_are_excluded_from_gaps(self):
        self.lesson()
        self.log("fixture-c", 0.3, "2026-02-01T00:00:00Z", misconceptions=[{"text": "unrelated confusion about c", "status": "demonstrated"}])
        doc = lifecycle.open_session(self.root, PID)
        self.assertEqual(doc["objectives"], ["fixture-b:overall"])
        ctx = model.build_context(self.root, PID, date(2026, 2, 2))
        self.assertNotIn("unrelated confusion about c", ctx)

    def test_fresh_review_conversation_context_is_minimal_and_isolated(self):
        self.log("fixture-a", 0.95, "2026-02-01T00:00:00Z")
        rs, _ = review.start(self.root, PID, today=date(2026, 2, 5))
        text = review.brief(self.root, PID)
        self.assertIn("RETRIEVAL session", text)
        self.assertNotIn("SECRET-HISTORY", text)
        self.assertNotIn("fixture-b`] state", text)
        small = review.brief(self.root, PID, max_chars=1500)
        self.assertIn("## Steps", small)  # required content is never cut
        review.abandon(self.root, PID, reason="done", confirm=True)
        with self.assertRaisesRegex(ValueError, "no open review session"):
            review.brief(self.root, PID)

    def test_progress_separates_facts_from_interpretation_and_avoids_thin_percentages(self):
        text = review.progress_text(self.root, PID, date(2026, 2, 1))
        facts, interp = text.split("## Interpretation")
        self.assertIn("## Measured facts", facts)
        self.assertNotIn("%", text)
        self.assertIn("Recommended next action", interp)
        self.assertIn("Delayed retention: no delayed review yet", facts)

    def test_progress_with_no_evidence_makes_no_mastery_claim(self):
        root = self.root
        (self.pdir / "logs" / "assessments.jsonl").write_text("", "utf-8")
        model.write_mastery(root, PID)
        text = review.progress_text(root, PID, date(2026, 2, 1))
        self.assertIn("0 mastered, 0 proficient", text)
        self.assertIn("Too few for a trend", text)

    def test_cli_progress_and_review_due(self):
        code, out, _ = run(self.root, "progress", PID, "--today", "2026-02-01")
        self.assertEqual(code, 0)
        self.assertIn("Measured facts", out)
        code, out, _ = run(self.root, "review", "due", PID, "--today", "2026-02-01")
        self.assertEqual(code, 0)
        self.assertIn("Reviews due on 2026-02-01", out)


# --------------------------------------------------------------------------
class Reliability(Base):
    def test_duplicate_commit_does_not_duplicate_the_event(self):
        self.lesson()
        t = self.full(draft(), "2026-02-01")
        n = len(self.events())
        assessment.commit(self.root, PID, t["id"])
        self.assertEqual(len(self.events()), n)

    def test_duplicate_assessment_id_in_log_is_a_validation_error(self):
        self.lesson()
        self.full(draft(), "2026-02-01")
        log = self.pdir / "logs" / "assessments.jsonl"
        lines = log.read_text("utf-8").splitlines()
        log.write_text("\n".join(lines + [lines[-1]]) + "\n", "utf-8")
        errs = model.validate_root(self.root).errors
        self.assertTrue(any("more than once" in e for e in errs), errs)

    def test_interrupted_commit_is_detected_and_recovered(self):
        self.lesson()
        t = self.full(draft(), "2026-02-01", commit=False)
        original = assessment._save_task
        calls = {"n": 0}

        def boom(root, doc):
            if doc["status"] == "committed":
                calls["n"] += 1
                raise OSError("simulated crash after the event was appended")
            return original(root, doc)

        assessment._save_task = boom
        try:
            with self.assertRaises(OSError):
                assessment.commit(self.root, PID, t["id"], ts="2026-02-01T09:04:00Z")
        finally:
            assessment._save_task = original
        self.assertEqual(calls["n"], 1)
        rep = model.validate_root(self.root)
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("interrupted commit" in w for w in rep.warnings), rep.warnings)
        n = len(self.events())
        assessment.commit(self.root, PID, t["id"])  # resumes: no second event
        self.assertEqual(len(self.events()), n)
        self.strict_validate()

    def test_interrupted_state_refresh_is_repaired_by_rebuild(self):
        self.lesson()
        self.full(draft(), "2026-02-01")
        (self.pdir / "state" / "evidence.yaml").write_text("garbage: [", "utf-8")
        self.assertTrue(model.validate_root(self.root).errors)
        model.rebuild(self.root, PID)
        self.strict_validate()

    def test_leftover_temp_files_only_warn(self):
        self.lesson()
        self.full(draft(), "2026-02-01")
        (self.pdir / "assessments" / "asm-001" / ".tmp-xyz").write_text("x", "utf-8")
        rep = model.validate_root(self.root)
        self.assertEqual(rep.errors, [])
        self.assertTrue(any(".tmp-" in w for w in rep.warnings))

    def test_concurrent_writers_never_corrupt_the_log(self):
        code = ("import sys; sys.path.insert(0, ROOT_SCRIPTS); from pathlib import Path; from learning_os import model\n"
                "for k in range(8):\n"
                "    model.append_event(Path(ROOT_DATA), 'sample-program', lesson=1, competency='fixture-b', kind='quiz', score=0.5)\n"
                ).replace("ROOT_SCRIPTS", repr(str(REPO / "scripts"))).replace("ROOT_DATA", repr(str(self.root)))
        procs = [subprocess.Popen([sys.executable, "-c", code], stderr=subprocess.PIPE, text=True) for _ in range(3)]
        errs = [p.communicate()[1] for p in procs]
        events, problems = model.read_events(self.pdir / "logs" / "assessments.jsonl")
        self.assertEqual(problems, [], errs)
        self.assertEqual(len(events), 3 + 24, errs)  # fixture has 3 events; every append landed exactly once
        self.assertEqual(model.validate_root(self.root).errors, [])

    def test_lock_is_reentrant_within_a_process(self):
        with model.program_lock(self.root, PID):
            with model.program_lock(self.root, PID):
                model.write_mastery(self.root, PID)

    def test_cross_program_isolation(self):
        import shutil
        shutil.copytree(self.pdir, self.root / "programs" / "other-program")
        p = self.root / "programs" / "other-program" / "program.yaml"
        p.write_text(p.read_text("utf-8").replace("id: sample-program", "id: other-program"), "utf-8")
        for f in (self.root / "programs" / "other-program" / "logs" / "assessments.jsonl",):
            f.write_text(f.read_text("utf-8").replace("sample-program", "other-program"), "utf-8")
        for f in (self.root / "programs" / "other-program" / "lessons").glob("*.md"):
            f.write_text(f.read_text("utf-8").replace("sample-program", "other-program"), "utf-8")
        model.rebuild(self.root, "other-program")
        self.log("fixture-b", 0.4, "2026-02-01T00:00:00Z", misconceptions=[{"text": "only in sample program", "status": "demonstrated"}])
        self.lesson()
        assessment.create(self.root, PID, draft())
        other = model.build_context(self.root, "other-program", date(2026, 2, 2))
        self.assertNotIn("only in sample program", other)
        self.assertEqual(assessment.all_tasks(self.root, "other-program"), [])
        with self.assertRaisesRegex(ValueError, "no assessment"):
            assessment.show(self.root, "other-program", "asm-001")
        self.assertEqual(model.read_events(self.root / "programs" / "other-program" / "logs" / "assessments.jsonl")[0][-1]["program"], "other-program")
        self.assertEqual(model.validate_root(self.root).errors, [])


# --------------------------------------------------------------------------
class EndToEnd(Base):
    """A synthetic multi-day journey through the CLI: lesson -> assessments -> reviews -> mastered."""

    def cli(self, *argv, expect=0):
        code, out, err = run(self.root, *argv)
        self.assertEqual(code, expect, out + err)
        return out

    def write(self, name, obj):
        p = self.root / name
        p.write_text(miniyaml.dumps(obj), "utf-8")
        return str(p)

    def assess_cli(self, d, day, answers, g, hint=None, extra=None):
        out = self.cli("assess", "create", PID, "--file", self.write("d.yaml", d), "--ts", f"{day}T09:00:00Z", *(extra or []))
        aid = next(w for w in out.split() if w.startswith("asm-"))
        if hint:
            self.cli("assess", "hint", PID, aid, "--level", hint, "--ts", f"{day}T09:01:00Z")
        self.cli("assess", "submit", PID, aid, "--file", self.write("s.yaml", {"responses": answers}), "--ts", f"{day}T09:02:00Z")
        self.cli("assess", "brief", PID, aid)
        self.cli("assess", "grade", PID, aid, "--file", self.write("g.yaml", g), "--ts", f"{day}T09:03:00Z")
        self.cli("assess", "commit", PID, aid, "--ts", f"{day}T09:04:00Z")
        return aid

    def test_journey_to_retained_mastery(self):
        self.cli("lesson", "start", PID, "--provider", "claude", "--ts", "2026-02-01T09:00:00Z")
        self.cli("lesson", "await-assessment", PID, "--ts", "2026-02-01T09:30:00Z")
        # day 1: an assisted attempt first (does not count), then independent recall + hard application
        self.assess_cli(draft("e-assisted"), "2026-02-01", {"q1": "5", "q2": "y"}, grading(1.0), hint="hint-1")
        self.assess_cli(draft("e-recall"), "2026-02-01", {"q1": "5", "q2": "y"}, grading(0.95))
        self.assess_cli(draft("e-app", "application", difficulty="hard"), "2026-02-01", {"q1": "5", "q2": "y"}, grading(0.95))
        self.cli("lesson", "complete", PID, "--file", self.write("c.yaml", {"summary": "s", "handoff": "h", "next_action": "n"}), "--ts", "2026-02-01T10:00:00Z")
        ms = self.mastery()
        self.assertEqual(ms["status"], "proficient")  # evidence is strong but nothing has been retained yet
        c = self.evstate()["competencies"]["fixture-a"]
        self.assertTrue(any("delayed review" in b for b in c["mastered_blockers"]))
        # nothing due the same day; due next day; review session on day 5 (a "fresh conversation")
        self.assertIn("Nothing to assign", self.cli("review", "due", PID, "--today", "2026-02-01"))
        out = self.cli("review", "start", PID, "--today", "2026-02-05", "--provider", "codex", "--ts", "2026-02-05T08:00:00Z")
        self.assertIn("review-001", out)
        brief = self.cli("review", "brief", PID)
        self.assertNotIn(SECRET, brief)
        self.assess_cli(draft("e-del", "delayed_review"), "2026-02-05", {"q1": "5", "q2": "y"}, grading(0.95))
        summary = self.cli("review", "complete", PID)
        self.assertIn("passed independently", summary)
        self.assertEqual(self.mastery()["status"], "mastered")
        self.assertEqual(self.evstate()["competencies"]["fixture-a"]["level"], "retained")
        self.cli("validate", "--strict")
        report = self.cli("progress", PID, "--today", "2026-02-06")
        self.assertIn("1 retained", report)
        self.assertIn("1 passed, 0 failed of 1 delayed review", report)
        self.assertIn("1 of 4 structured attempt(s) were assisted", report)
        # lesson numbering was untouched by the review session
        self.assertEqual(len(list((self.pdir / "lessons").iterdir())), 2)  # fixture lesson 1 + the one lesson of this journey


class Wiring(unittest.TestCase):
    def test_protocol_and_entry_points_exist(self):
        idx = (REPO / "engine/protocol/README.md").read_text("utf-8")
        self.assertIn("09-assessment-and-review.md", idx)
        for f in ("engine/protocol/09-assessment-and-review.md", "docs/assessment.md", ".claude/commands/review.md",
                  ".claude/commands/assess.md", ".claude/commands/progress.md", "adapters/codex/prompts/review.md",
                  "adapters/codex/prompts/assess.md", "adapters/codex/prompts/progress.md"):
            self.assertTrue((REPO / f).is_file(), f)
        agents = (REPO / "AGENTS.md").read_text("utf-8")
        for phrase in ("Test my understanding", "What should I review today", "Show my learning progress"):
            self.assertIn(phrase, agents)

    def test_examiner_never_gets_write_tools(self):
        text = (REPO / ".claude/agents/examiner.md").read_text("utf-8")
        tools = next(line for line in text.splitlines() if line.startswith("tools:"))
        self.assertNotRegex(tools, r"Write|Edit|Bash")


if __name__ == "__main__":
    unittest.main()
