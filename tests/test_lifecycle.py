"""Phase 5: lesson lifecycle, planning, context, recovery. CLI-level tests on synthetic fixtures only.

These do NOT exercise Codex Desktop or Claude Desktop; see docs/lessons.md for what is unverified in the GUIs.
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers
from helpers import FIXTURE_ROOT, PID, REPO, TmpRootCase
from learning_os import design, lifecycle, miniyaml, model
from test_design import Base

LOG = "programs/demo/logs/assessments.jsonl"


class Pinned(Base):
    """A program whose curriculum is approved and activated: a(o1) -> b(o1); c is deprioritized."""

    def setUp(self):
        super().setUp()
        self.onboard()
        self.to_review()
        rev = self.cur()["revision"]
        self.ok("curriculum", "approve", "demo", "--revision", str(rev), "--statement", "yes", "--confirm", "--today", "2026-01-06")
        self.ok("curriculum", "activate", "demo", "--revision", str(rev), "--today", "2026-01-07")
        self.rev = rev
        self.n_events = 0

    def file(self, rel):
        return (self.root / "programs/demo" / rel)

    def lesson(self, *a, **kw):
        return self.ok("lesson", *a[:1], "demo", *a[1:], **kw)

    def demonstrate(self, cid, lesson):
        for _ in range(3):
            self.n_events += 1
            self.ok("log", "demo", "--lesson", str(lesson), "--competency", cid, "--kind", "quiz", "--score", "1.0",
                    "--ts", f"2026-02-01T10:{self.n_events:02d}:00Z")
        st = miniyaml.loads(self.file("state/mastery.yaml").read_text("utf-8"))["competencies"][cid]["status"]
        self.assertEqual(st, "mastered")

    def closure(self, **kw):
        d = {"summary": "Explained and practised.", "handoff": "Resume with a harder item.", "next_action": "Independent challenge"}
        d.update(kw)
        return d

    def finish(self, **kw):
        return self.ok("lesson", "complete", "demo", "--file", "-", data=self.closure(**kw))

    def session(self, n=1):
        return lifecycle.load_session(self.root, "demo", n)


class PlanningTests(Pinned):
    def test_auto_recommendation_explains_itself_and_does_not_trust_self_report(self):
        out = self.ok("lesson", "next", "demo")
        self.assertIn("`a:o1`", out)
        self.assertIn("next uncovered objective in curriculum order", out)
        self.assertIn("self-reported, NOT demonstrated", out)  # curriculum decision for a is 'verify' on self-report
        self.assertIn("`b:o1` is blocked", out)
        self.assertEqual(self.mastery("a"), "unseen")

    def mastery(self, cid):
        return miniyaml.loads(self.file("state/mastery.yaml").read_text("utf-8"))["competencies"][cid]["status"]

    def test_manual_selection_and_prerequisite_enforcement(self):
        self.fail("lesson", "start", "demo", "--objective", "b:o1", expect="prerequisites without demonstrated mastery")
        self.fail("lesson", "start", "demo", "--objective", "b:o1", "--override-rationale", "deadline",
                  expect="prerequisites without demonstrated mastery")  # missing --statement/--confirm
        self.assertFalse(self.file("sessions").exists())
        self.fail("lesson", "start", "demo", "--objective", "zz:o9", expect="unknown objective")

    def test_learner_approved_override_is_recorded(self):
        self.ok("lesson", "start", "demo", "--objective", "b:o1", "--override-rationale", "needs b for work this week",
                "--statement", "Yes skip a, I accept the risk", "--confirm")
        sel = self.session()["selection"]
        self.assertEqual(sel["mode"], "override")
        self.assertEqual(sel["unmet_prerequisites"], ["a"])
        self.assertIn("accept the risk", sel["override"]["statement"])
        self.assertIn("OVERRIDE", self.ok("lesson", "status", "demo"))

    def test_manual_selection_of_eligible_objective(self):
        self.ok("lesson", "start", "demo", "--objective", "a:o1")
        self.assertEqual(self.session()["selection"]["mode"], "manual")

    def test_unapproved_draft_cannot_be_taught(self):
        self.onboard("other")
        self.to_review(pid="other")  # draft in review, never approved/activated
        self.fail("lesson", "next", "other", expect="no approved, activated curriculum")
        self.fail("lesson", "start", "other", expect="no approved, activated curriculum")
        self.assertFalse((self.root / "programs/other/sessions").exists())

    def test_onboarded_program_with_placeholder_curriculum_is_refused(self):
        self.onboard("fresh")
        self.fail("lesson", "start", "fresh", expect="no approved, activated curriculum")

    def test_session_is_pinned_to_curriculum_version(self):
        self.ok("lesson", "start", "demo")
        cur = self.session()["curriculum"]
        self.assertEqual(cur["mode"], "pinned")
        self.assertEqual(cur["revision"], self.rev)
        self.assertEqual(cur["sha256"], design.content_hash(design.load_snapshot(self.root, "demo", self.rev)))
        self.assertEqual(self.session()["objectives"], ["a:o1"])
        self.ok("validate", "--strict")

    def test_tampering_with_the_pinned_snapshot_is_detected(self):
        self.ok("lesson", "start", "demo")
        snap = self.file(f"design/curriculum/versions/r{self.rev:03d}.yaml")
        snap.write_text(snap.read_text("utf-8").replace("Module m1", "Module changed", 1), "utf-8")
        c, out, err = self.r("validate")
        self.assertEqual(c, 1)
        self.assertIn("pinned", out)

    def test_materials_record_source_status_at_plan_time(self):
        self.ok("lesson", "start", "demo")
        self.assertEqual(self.session()["materials"], [{"source": "s1", "use": "primary", "status_at_plan": "inspected"}])

    def test_blockers_when_instruction_is_not_evidence(self):
        self.ok("lesson", "start", "demo")
        self.finish()
        out = self.ok("lesson", "next", "demo")
        # a was taught but never assessed: consolidate it, do not unlock b
        self.assertIn("`a:o1` (consolidate)", out)
        self.assertIn("`b:o1` is blocked", out)
        self.assertEqual(self.mastery("a"), "unseen")

    def test_progression_then_exhaustion_reports_blocker(self):
        self.ok("lesson", "start", "demo"); self.finish()
        self.demonstrate("a", 1)
        self.assertIn("`b:o1` (new)", self.ok("lesson", "next", "demo"))
        self.ok("lesson", "start", "demo"); self.finish()
        self.demonstrate("b", 2)
        c, out, _ = self.r("lesson", "next", "demo")
        self.assertEqual(c, 1)
        self.assertIn("nothing further to teach", out)
        self.fail("lesson", "start", "demo", expect="no suitable next objective")


class StateMachineTests(Pinned):
    def test_full_cycle_with_history(self):
        self.ok("lesson", "start", "demo", "--provider", "claude", "--thread", "chat-1")
        self.ok("lesson", "pause", "demo", "--note", "break")
        self.ok("lesson", "resume", "demo")
        self.ok("lesson", "await-assessment", "demo")
        self.ok("lesson", "resume", "demo")  # awaiting_assessment -> active is allowed
        self.finish()
        s = self.session()
        self.assertEqual([h["to"] for h in s["history"]],
                         ["planned", "active", "paused", "active", "awaiting_assessment", "active", "completed"])
        self.assertEqual(s["status"], "completed")
        self.assertEqual(s["provider"], {"name": "claude", "thread_ref": "chat-1"})
        self.ok("validate", "--strict")

    def test_invalid_transitions(self):
        doc, _ = lifecycle.plan_lesson(self.root, "demo")
        self.assertEqual(doc["status"], "planned")
        self.fail("lesson", "pause", "demo", expect="invalid transition planned -> paused")
        self.fail("lesson", "complete", "demo", "--file", "-", data=self.closure(), expect="invalid transition planned -> completed")
        self.ok("lesson", "start", "demo")
        self.ok("lesson", "pause", "demo")
        self.fail("lesson", "complete", "demo", "--file", "-", data=self.closure(), expect="invalid transition paused -> completed")
        self.fail("lesson", "await-assessment", "demo", expect="invalid transition paused -> awaiting_assessment")
        self.ok("lesson", "resume", "demo")
        self.finish()
        self.fail("lesson", "pause", "demo", expect="no open lesson")
        self.fail("lesson", "resume", "demo", expect="no open lesson to resume")

    def test_duplicate_requests_are_idempotent(self):
        a = self.ok("lesson", "start", "demo")
        b = self.ok("lesson", "start", "demo")
        self.assertIn("started", a)
        self.assertIn("already active (no change)", b)
        self.assertEqual([p.name for p in self.file("sessions").glob("*.yaml")], ["001.yaml"])
        self.ok("lesson", "pause", "demo")
        self.assertIn("already paused", self.ok("lesson", "pause", "demo"))
        self.ok("lesson", "resume", "demo")
        self.finish()
        first = self.file("lessons").glob("001-*.md")
        text = next(first).read_text("utf-8")
        self.assertIn("already completed", self.finish())
        self.assertEqual(next(self.file("lessons").glob("001-*.md")).read_text("utf-8"), text)
        self.assertEqual(len(list(self.file("lessons").glob("0*.md"))), 1)

    def test_only_one_open_lesson_and_other_objective_is_refused(self):
        self.ok("lesson", "start", "demo")
        self.fail("lesson", "start", "demo", "--objective", "b:o1", "--override-rationale", "x", "--statement", "y",
                  "--confirm", expect="already open")

    def test_conflicting_conversations_are_detected_when_thread_refs_differ(self):
        self.ok("lesson", "start", "demo", "--provider", "claude", "--thread", "chat-A")
        self.fail("lesson", "start", "demo", "--provider", "codex", "--thread", "chat-B", expect="active in another conversation")
        self.fail("lesson", "resume", "demo", "--provider", "codex", "--thread", "chat-B", expect="active in another conversation")
        self.assertEqual(self.session()["provider"]["thread_ref"], "chat-A")
        self.assertIn("took over", self.ok("lesson", "resume", "demo", "--provider", "codex", "--thread", "chat-B", "--takeover"))
        self.assertEqual(self.session()["provider"], {"name": "codex", "thread_ref": "chat-B"})

    def test_session_files_are_never_overwritten(self):
        doc, _ = lifecycle.plan_lesson(self.root, "demo")
        with self.assertRaises(lifecycle.Conflict):
            lifecycle._create(self.root, doc)

    def test_two_open_sessions_fail_validation(self):
        self.ok("lesson", "start", "demo")
        src = self.file("sessions/001.yaml")
        dup = src.read_text("utf-8").replace("lesson-001", "lesson-002").replace("lesson: 1", "lesson: 2")
        self.file("sessions/002.yaml").write_text(dup, "utf-8")
        c, out, _ = self.r("validate")
        self.assertEqual(c, 1)
        self.assertIn("more than one open lesson", out)
        self.fail("lesson", "status", "demo", expect="open lesson sessions")

    def test_abandon_needs_confirmation_and_consumes_the_number(self):
        self.ok("lesson", "start", "demo")
        self.fail("lesson", "abandon", "demo", "--reason", "no time", expect="explicit learner confirmation")
        self.fail("lesson", "abandon", "demo", "--confirm", expect="--reason")
        self.assertEqual(self.session()["status"], "active")
        self.ok("lesson", "abandon", "demo", "--reason", "no time", "--confirm")
        self.assertIn("already abandoned", self.ok("lesson", "abandon", "demo", "--reason", "no time", "--confirm"))
        meta, body = miniyaml.split_frontmatter(next(self.file("lessons").glob("001-*.md")).read_text("utf-8"))
        self.assertEqual(meta["outcome"], "abandoned")
        self.assertEqual(miniyaml.loads(self.file("state/progress.yaml").read_text("utf-8"))["lessons_completed"], 0)
        # the abandoned lesson taught nothing: the same objective is recommended again
        self.assertIn("`a:o1`", self.ok("lesson", "next", "demo"))
        self.ok("validate", "--strict")

    def test_pause_then_resume_in_new_conversation_keeps_notes(self):
        self.ok("lesson", "start", "demo")
        self.ok("lesson", "note", "demo", "--file", "-", data={"concepts_explained": ["what a is"], "unresolved_questions": ["why?"]})
        self.ok("lesson", "pause", "demo")
        self.assertEqual(self.session()["notes"]["concepts_explained"], ["what a is"])
        self.ok("lesson", "resume", "demo", "--provider", "codex", "--thread", "chat-2")
        self.assertEqual(self.session()["status"], "active")


class NotesAndClosureTests(Pinned):
    def setUp(self):
        super().setUp()
        self.ok("lesson", "start", "demo")

    def test_attempts_distinguish_assisted_from_independent(self):
        self.ok("lesson", "note", "demo", "--file", "-", data={"attempts": [
            {"objective": "a:o1", "task": "item 1", "assistance": "hint-2", "result": "partial"},
            {"objective": "a:o1", "task": "item 2", "assistance": "none", "result": "correct"}]})
        att = self.session()["notes"]["attempts"]
        self.assertEqual([a["assistance"] for a in att], ["hint-2", "none"])
        self.fail("lesson", "note", "demo", "--file", "-", data={"attempts": [
            {"objective": "a:o1", "task": "t", "assistance": "heavy", "result": "correct"}]}, expect="assistance")
        self.fail("lesson", "note", "demo", "--file", "-", data={"attempts": [
            {"objective": "b:o1", "task": "t", "assistance": "none", "result": "correct"}]}, expect="not this lesson's objective")

    def test_notes_are_deduplicated(self):
        patch = {"concepts_explained": ["x"], "misconceptions": [{"text": "believes p implies q", "competency": "a", "status": "open"}]}
        self.ok("lesson", "note", "demo", "--file", "-", data=patch)
        self.ok("lesson", "note", "demo", "--file", "-", data=patch)
        n = self.session()["notes"]
        self.assertEqual(n["concepts_explained"], ["x"])
        self.assertEqual(len(n["misconceptions"]), 1)

    def test_misconception_resolves_only_after_independent_success(self):
        mc = {"text": "believes p implies q", "competency": "a", "status": "open"}
        self.ok("lesson", "note", "demo", "--file", "-", data={"misconceptions": [mc]})
        res = dict(mc, status="resolved")
        self.fail("lesson", "note", "demo", "--file", "-", data={"misconceptions": [res]}, expect="independent")
        self.ok("lesson", "note", "demo", "--file", "-", data={
            "attempts": [{"objective": "a:o1", "task": "probe", "assistance": "none", "result": "correct"}], "misconceptions": [res]})
        self.assertEqual(self.session()["notes"]["misconceptions"][0]["status"], "resolved")

    def test_completion_persists_the_required_closure_and_never_claims_mastery(self):
        before_log = self.file("logs/assessments.jsonl").read_bytes()
        before_mastery = self.file("state/mastery.yaml").read_bytes()
        self.ok("lesson", "note", "demo", "--file", "-", data={
            "concepts_explained": ["definition of a"], "unresolved_questions": ["edge case?"],
            "attempts": [{"objective": "a:o1", "task": "item", "assistance": "hint-1", "result": "partial"}],
            "misconceptions": [{"text": "confuses a with b", "competency": "a", "status": "open"}]})
        out = self.finish(next_focus=["a"])
        self.assertIn("assessment: not_assessed (instruction only; mastery unchanged)", out)
        self.assertEqual(self.file("logs/assessments.jsonl").read_bytes(), before_log)
        self.assertEqual(self.file("state/mastery.yaml").read_bytes(), before_mastery)
        rec = next(self.file("lessons").glob("001-*.md")).read_text("utf-8")
        meta, body = miniyaml.split_frontmatter(rec)
        self.assertEqual(meta["objectives"], ["a:o1"])
        self.assertEqual(meta["assessment_status"], "not_assessed")
        self.assertEqual(meta["curriculum_revision"], self.rev)
        self.assertEqual(meta["session"], "lesson-001")
        for needle in ("Concepts explained", "hint-1", "confuses a with b", "edge case?", "Next action: Independent challenge", "NOT assessed"):
            self.assertIn(needle, rec)
        self.assertEqual(self.mastery_of("a"), "unseen")
        self.ok("validate", "--strict")

    def mastery_of(self, cid):
        return miniyaml.loads(self.file("state/mastery.yaml").read_text("utf-8"))["competencies"][cid]["status"]

    def test_assessment_references_point_at_existing_events(self):
        self.ok("log", "demo", "--lesson", "1", "--competency", "a", "--kind", "quiz", "--score", "0.8", "--ts", "2026-02-01T10:00:00Z")
        self.ok("lesson", "await-assessment", "demo")
        self.finish()
        cl = self.session()["closure"]["assessment"]
        self.assertEqual(cl, {"status": "logged", "refs": ["logs/assessments.jsonl:1"]})
        self.assertEqual(self.mastery_of("a"), "learning")  # one event: still not proficient

    def test_closure_rejects_unknown_fields_and_incomplete_data(self):
        self.fail("lesson", "complete", "demo", "--file", "-", data=self.closure(mastery="mastered"), expect="Mastery is never set here")
        self.fail("lesson", "complete", "demo", "--file", "-", data={"summary": "s"}, expect="needs `handoff`")
        self.fail("lesson", "complete", "demo", "--file", "-", data=self.closure(next_focus=["nope"]), expect="unknown competencies")
        self.assertEqual(self.session()["status"], "active")
        self.assertEqual(list(self.file("lessons").glob("0*.md")), [])

    def test_partial_outcome(self):
        self.ok("lesson", "complete", "demo", "--outcome", "partial", "--file", "-", data=self.closure())
        meta, _ = miniyaml.split_frontmatter(next(self.file("lessons").glob("001-*.md")).read_text("utf-8"))
        self.assertEqual(meta["outcome"], "partial")
        self.assertEqual(meta["competencies_covered"], [])
        self.assertIn("`a:o1` (new)", self.ok("lesson", "next", "demo"))  # partial does not count as covered


class RecoveryTests(Pinned):
    def test_interrupted_close_is_detected_and_finished_by_rerun(self):
        self.ok("lesson", "start", "demo")
        with mock.patch.object(lifecycle.model, "rebuild", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                lifecycle.complete_lesson(self.root, "demo", self.closure())
        self.assertEqual(self.session()["status"], "active")           # not yet terminal
        self.assertTrue(next(self.file("lessons").glob("001-*.md")))    # record already written
        c, out, _ = self.r("validate")
        self.assertEqual(c, 1)
        self.assertIn("interrupted close", out)
        self.fail("lesson", "pause", "demo", expect="mid-close")
        text = next(self.file("lessons").glob("001-*.md")).read_text("utf-8")
        self.ok("lesson", "complete", "demo")                           # no closure file needed: it was persisted first
        self.assertEqual(self.session()["status"], "completed")
        self.assertEqual(next(self.file("lessons").glob("001-*.md")).read_text("utf-8"), text)
        self.ok("validate", "--strict")

    def test_foreign_lesson_record_is_never_overwritten(self):
        self.ok("lesson", "start", "demo")
        stray = self.file("lessons/001-stray.md")
        stray.write_text("---\nschema_version: 1\nprogram: demo\nlesson: 1\ndate: 2026-01-09\ntitle: stray\noutcome: completed\n"
                         "competencies_covered: []\nnext_focus: []\n---\n\n## Summary\n\nx\n\n## Handoff\n\nx\n", "utf-8")
        self.fail("lesson", "complete", "demo", "--file", "-", data=self.closure(), expect="does not belong")
        self.assertIn("title: stray", stray.read_text("utf-8"))

    def test_interrupted_write_leaves_no_partial_session(self):
        self.ok("lesson", "start", "demo")
        before = self.file("sessions/001.yaml").read_text("utf-8")
        with mock.patch.object(lifecycle.onboarding.os, "replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                lifecycle.pause_lesson(self.root, "demo")
        self.assertEqual(self.file("sessions/001.yaml").read_text("utf-8"), before)
        self.assertEqual([p.name for p in self.file("sessions").iterdir()], ["001.yaml"])


class ContextTests(Pinned):
    def test_context_contains_the_targeted_selection_with_stable_refs(self):
        self.ok("lesson", "start", "demo")
        out = self.ok("context", "demo", "--today", "2026-02-01")
        for needle in ("program:demo", f"curriculum:demo@r{self.rev}#", "objective:a:o1", "competency:a", "registry:s1",
                       "Open lesson (resume it", "Learner preferences", "Success criterion: a done correctly", "## Rules"):
            self.assertIn(needle, out)
        self.assertIn("1 other competency omitted", out)       # b is irrelevant to lesson 1 on a (a has no prerequisites)
        self.assertNotIn("Competency b", out)
        self.assertIn("Self-reported and interpretation (NOT evidence", out)
        self.assertIn("Observed evidence (assessment log; authoritative)", out)

    def test_context_excludes_other_programs_archive_and_registry_dump(self):
        self.onboard("zeta")
        marker = "UNRELATED-MARKER-QQ"
        self.file("../zeta/program.yaml").write_text(
            self.file("../zeta/program.yaml").read_text("utf-8").replace("Demo", marker), "utf-8")
        (self.root / "archive").mkdir()
        (self.root / "archive/old.md").write_text("ARCHIVED-MARKER", "utf-8")
        self.ok("lesson", "start", "demo")
        out = self.ok("context", "demo")
        self.assertNotIn(marker, out)
        self.assertNotIn("ARCHIVED-MARKER", out)
        self.assertNotIn("s2", out)                          # the unrelated 'discovered' source is not dumped
        self.assertNotIn("Synthetic source", out)

    def test_size_limit_drops_optional_blocks_and_says_so(self):
        self.ok("lesson", "start", "demo")
        mcs = [{"text": f"misconception number {i}", "competency": "a", "status": "open"} for i in range(6)]
        self.ok("lesson", "note", "demo", "--file", "-", data={"misconceptions": mcs})
        full = self.ok("context", "demo")
        self.assertEqual(full.count("misconception number"), lifecycle.MISCONCEPTION_CAP)   # relevance cap
        self.assertIn("3 more open misconception(s) omitted", full)
        small = self.ok("context", "demo", "--max-chars", str(len(full) - 400))
        self.assertIn("Size limit:", small)
        self.assertIn("objective:a:o1", small)
        self.assertIn("## Rules", small)
        self.assertLess(len(small), len(full))

    def test_required_content_is_never_silently_truncated(self):
        self.ok("lesson", "start", "demo")
        out = self.ok("context", "demo", "--max-chars", "300")
        self.assertIn("WARNING: required content", out)
        for needle in ("objective:a:o1", "## Rules", "Open lesson"):
            self.assertIn(needle, out)

    def test_program_level_limit_is_configurable_and_validated(self):
        self.edit_program("review_after_days: 14", "review_after_days: 14\n  context_max_chars: 2000")
        self.ok("lesson", "start", "demo")
        self.assertIn("WARNING: required content", self.ok("context", "demo"))   # budget from program.yaml
        self.ok("validate", "--strict")
        self.edit_program("context_max_chars: 2000", "context_max_chars: 5")
        self.assertEqual(self.r("validate")[0], 1)

    def edit_program(self, old, new):
        p = self.file("program.yaml")
        t = p.read_text("utf-8")
        self.assertIn(old, t)
        p.write_text(t.replace(old, new, 1), "utf-8")

    def test_uninspected_resources_are_flagged_not_trusted(self):
        self.ok("lesson", "start", "demo")
        reg = self.file("design/research/registry.yaml")
        t = reg.read_text("utf-8")
        i = t.index("id: s1")
        reg.write_text(t[:i] + t[i:].replace("status: inspected", "status: discovered", 1), "utf-8")
        out = self.ok("context", "demo")
        self.assertIn("UNINSPECTED/discovered", out)
        self.assertIn("No inspected resource is attached", out)

    def test_previous_handoff_and_next_action_carry_over(self):
        self.ok("lesson", "start", "demo")
        self.finish(handoff="Pick up at the second worked example.", next_action="Run an independent challenge on a")
        self.ok("lesson", "start", "demo")
        out = self.ok("context", "demo")
        self.assertIn("Pick up at the second worked example.", out)
        self.assertIn("Run an independent challenge on a", out)
        self.assertIn("consolidate", out)

    def test_open_misconceptions_for_prerequisites_are_relevant(self):
        self.ok("lesson", "start", "demo"); 
        self.ok("lesson", "note", "demo", "--file", "-", data={"misconceptions": [{"text": "A-LEVEL-MISCONCEPTION", "competency": "a", "status": "open"}]})
        self.finish()
        self.demonstrate("a", 1)   # a is now mastered, misconception stays open (never independently re-tested in a note)
        self.ok("lesson", "start", "demo")          # b:o1
        out = self.ok("context", "demo")
        self.assertIn("objective:b:o1", out)
        self.assertIn("A-LEVEL-MISCONCEPTION", out)
        self.assertIn("interpretation", out)

    def test_fresh_conversation_needs_only_persisted_files(self):
        self.ok("lesson", "start", "demo", "--provider", "claude", "--thread", "chat-1")
        self.ok("lesson", "note", "demo", "--file", "-", data={"concepts_explained": ["concept-xyz"]})
        self.ok("lesson", "pause", "demo")
        with tempfile.TemporaryDirectory() as tmp:       # a different machine/conversation: only the files travel
            clone = Path(tmp) / "root"
            shutil.copytree(self.root, clone, ignore=shutil.ignore_patterns("__pycache__"))
            from test_onboarding import run
            code, out, err = run(clone, "lesson", "status", "demo")
            self.assertEqual(code, 0, err)
            self.assertIn("paused", out)
            code, out, err = run(clone, "lesson", "resume", "demo", "--provider", "codex", "--thread", "chat-9")
            self.assertEqual(code, 0, err)
            code, brief, err = run(clone, "lesson", "brief", "demo")
            self.assertEqual(code, 0, err)
            self.assertIn("concept-xyz", brief)
            self.assertIn("objective:a:o1", brief)

    def test_brief_requires_an_open_lesson(self):
        self.fail("lesson", "brief", "demo", expect="no open lesson")


class EndToEndTests(Pinned):
    def test_two_lessons_across_fresh_conversations(self):
        # --- conversation 1: plan, teach, assess independently, complete -------------------------------------------
        self.assertIn("`a:o1`", self.ok("lesson", "next", "demo"))
        self.ok("lesson", "start", "demo", "--provider", "claude", "--thread", "conv-1")
        brief = self.ok("lesson", "brief", "demo")
        self.assertIn("Open lesson", brief)
        self.ok("lesson", "note", "demo", "--file", "-", data={
            "concepts_explained": ["core idea of a"],
            "attempts": [{"objective": "a:o1", "task": "guided item", "assistance": "hint-1", "result": "partial"},
                         {"objective": "a:o1", "task": "independent challenge", "assistance": "none", "result": "correct"}]})
        for i, score in enumerate(("0.9", "1.0"), 1):   # the Tutor logs the independent items
            self.ok("log", "demo", "--lesson", "1", "--competency", "a", "--kind", "quiz", "--score", score,
                    "--ts", f"2026-02-01T10:0{i}:00Z")
        self.ok("lesson", "complete", "demo", "--file", "-", data={
            "summary": "Taught a; independent challenge passed.", "handoff": "a is solid; start b.",
            "next_action": "Open b with a retrieval question on a", "next_focus": ["b"]})
        s1 = self.session(1)
        self.assertEqual(s1["closure"]["assessment"]["status"], "logged")
        self.assertEqual(self.mastery_status("a"), "mastered")   # from the log, not from completing the lesson
        # --- conversation 2 (nothing carried over): resumes from files only -----------------------------------------
        out = self.ok("lesson", "next", "demo")
        self.assertIn("`b:o1` (new)", out)
        self.assertIn("previous lesson recommended this competency", out)
        self.ok("lesson", "start", "demo", "--provider", "codex", "--thread", "conv-2")
        brief = self.ok("lesson", "brief", "demo")
        self.assertIn("a is solid; start b.", brief)
        self.assertIn("objective:b:o1", brief)
        self.ok("lesson", "pause", "demo", "--note", "end of day")
        # --- conversation 3 -----------------------------------------------------------------------------------------
        self.ok("lesson", "resume", "demo", "--provider", "claude", "--thread", "conv-3")
        self.ok("lesson", "complete", "demo", "--outcome", "partial", "--file", "-", data=self.closure())
        self.assertEqual([s["status"] for s in lifecycle.all_sessions(self.root, "demo")], ["completed", "completed"])
        self.assertEqual(self.mastery_status("b"), "unseen")
        progress = miniyaml.loads(self.file("state/progress.yaml").read_text("utf-8"))
        self.assertEqual(progress["lessons_completed"], 2)
        self.assertIn("lesson-001", self.ok("lesson", "status", "demo"))
        self.assertIn("demo:", self.ok("programs"))
        self.ok("validate", "--strict")

    def mastery_status(self, cid):
        return miniyaml.loads(self.file("state/mastery.yaml").read_text("utf-8"))["competencies"][cid]["status"]


class LegacyProgramTests(TmpRootCase):
    """Programs without a curriculum pipeline keep working at competency level."""

    def test_legacy_flow_and_context_isolation(self):
        from test_onboarding import run
        c, out, err = run(self.root, "lesson", "next", PID)
        self.assertEqual(c, 0, err)
        self.assertIn("`fixture-b:overall`", out)
        self.assertIn("legacy", out)
        before = (self.pdir / "logs/assessments.jsonl").read_bytes()
        self.assertEqual(run(self.root, "lesson", "start", PID)[0], 0)
        c, brief, _ = run(self.root, "context", PID)
        self.assertIn("fixture-b", brief)
        self.assertNotIn("old-chat", brief)
        c, out, err = run(self.root, "lesson", "complete", PID, "--file", "-",
                          stdin="summary: s\nhandoff: h\nnext_action: assess b\n")
        self.assertEqual(c, 0, err)
        self.assertEqual((self.pdir / "logs/assessments.jsonl").read_bytes(), before)
        self.assertEqual(run(self.root, "validate", "--strict")[0], 0)
        c, out, _ = run(self.root, "lesson", "next", PID)
        self.assertIn("`fixture-b:overall` (consolidate)", out)   # taught, never assessed


class EntryPointTests(unittest.TestCase):
    """File-level checks only. They prove the entry points exist and name the real commands,
    not that Claude Desktop or Codex Desktop actually runs them."""

    def test_entry_points_exist_for_both_agents(self):
        for name in ("lesson", "pause-lesson", "close-lesson"):
            self.assertTrue((REPO / ".claude/commands" / f"{name}.md").is_file(), name)
            self.assertTrue((REPO / "adapters/codex/prompts" / f"{name}.md").is_file(), name)

    def test_entry_points_use_only_real_cli_commands(self):
        import re
        parser_help = lifecycle  # noqa: F841  (keeps import used)
        from learning_os import cli
        known = {a for a in cli.build_parser()._subparsers._group_actions[0].choices["lesson"]._subparsers._group_actions[0].choices}
        for path in list((REPO / ".claude/commands").glob("*lesson*.md")) + list((REPO / "adapters/codex/prompts").glob("*lesson*.md")):
            for sub in re.findall(r"los\.py lesson ([a-z-]+)", path.read_text("utf-8")):
                self.assertIn(sub, known, f"{path.name}: unknown subcommand {sub}")

    def test_protocol_is_indexed_and_declares_study_mode_flow(self):
        index = (REPO / "engine/protocol/README.md").read_text("utf-8")
        self.assertIn("08-lesson-lifecycle.md", index)
        flow = (REPO / "engine/protocol/02-lesson-flow.md").read_text("utf-8")
        for step in ("Active recall", "Diagnostic", "Guided practice", "Independent challenge", "Reflection", "Summary and handoff"):
            self.assertIn(step, flow)
        self.assertIn("not an integration with ChatGPT", " ".join((REPO / "docs/lessons.md").read_text("utf-8").split()))


if __name__ == "__main__":
    unittest.main()
