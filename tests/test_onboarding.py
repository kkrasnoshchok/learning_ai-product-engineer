"""Program onboarding: unit tests and an end-to-end flow. Uses only abstract placeholder content."""
import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
from helpers import FIXTURE_ROOT, REPO
from learning_os import cli, miniyaml, model, onboarding

COMPLETE = """
goal:
  statement: Reach the abstract goal
  motivation: A personal reason
  applications: [apply it]
  competency_outcomes: [can do thing a]
  practical_outcomes: [produce artifact b]
  success_criteria: ["pass check c"]
profile:
  prior_experience: []
  knowledge_gaps: [gap one]
constraints:
  hours_per_week: 4
  depth: working
  pace: steady
  deadline: none
"""


def run(root, *args, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        if stdin is not None:
            import sys
            old, sys.stdin = sys.stdin, io.StringIO(stdin)
        try:
            code = cli.main(["--root", str(root), *args])
        except SystemExit as exc:
            code = exc.code
        finally:
            if stdin is not None:
                sys.stdin = old
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "programs").mkdir()
        shutil.copytree(FIXTURE_ROOT / "learner", self.root / "learner")

    def ob(self, *a, stdin=None):
        return run(self.root, "onboarding", *a, stdin=stdin)

    def ready(self, pid="demo"):
        self.assertEqual(self.ob("start", pid, "--title", "Demo", "--created", "2026-01-01")[0], 0)
        self.assertEqual(self.ob("update", pid, "--file", "-", stdin=COMPLETE)[0], 0)

    def state(self, pid="demo"):
        return onboarding.load_state(self.root, pid)


class UnitTests(Base):
    def test_schemas_share_spec_section_shapes(self):
        onb = model.load_schema("onboarding")["properties"]
        spec = model.load_schema("program")["properties"]["spec"]["properties"]
        for k in (*onboarding.SECTIONS, "approval"):
            self.assertEqual(onb[k], spec[k], k)

    def test_missing_lists_gaps_in_order(self):
        s = {"goal": {}, "profile": {}, "constraints": {}, "open_questions": [
            {"id": "q", "text": "t", "blocking": True}, {"id": "n", "text": "t", "blocking": False}]}
        m = onboarding.missing(s)
        self.assertTrue(m[0].startswith("goal.statement"))
        self.assertEqual(sum("open question" in x for x in m), 1)  # non-blocking never blocks
        self.assertIn("constraints.deadline", m)

    def test_update_rejects_unknown_keys_and_bad_values(self):
        self.ob("start", "demo", "--title", "Demo")
        self.assertEqual(self.ob("update", "demo", "--file", "-", stdin="status: approved\n")[0], 2)
        self.assertEqual(self.ob("update", "demo", "--file", "-", stdin="constraints:\n  pace: warp\n")[0], 2)
        self.assertEqual(self.state()["revision"], 1)

    def test_invalid_ids_rejected(self):
        for bad in ("Bad_ID", "../x", "a--b", ""):
            self.assertNotEqual(self.ob("start", bad, "--title", "T")[0], 0, bad)
        self.assertFalse((self.root / "onboarding").exists())

    def test_noop_update_does_not_bump_revision(self):
        self.ready()
        rev = self.state()["revision"]
        self.ob("update", "demo", "--file", "-", stdin="constraints:\n  pace: steady\n")
        self.assertEqual(self.state()["revision"], rev)

    def test_build_program_validates_after_approval_fields(self):
        self.ready()
        st = self.state()
        st.update(status="approved", approval={"revision": 2, "date": "2026-01-02", "statement": "yes"})
        rep = model.Report()
        self.assertTrue(model.validate_program_definition(rep, "p", onboarding.build_program(st)))
        self.assertEqual(rep.errors, [])


class FlowTests(Base):
    def test_end_to_end(self):
        self.ready()
        c, out, _ = self.ob("status", "demo")
        self.assertIn("global learner preferences", out)
        self.assertIn("socratic", out)  # preferences reused, from learner/preferences.yaml
        self.assertEqual(self.ob("submit", "demo")[0], 0)
        c, out, _ = self.ob("show", "demo")
        self.assertIn("Reach the abstract goal", out)
        rev = self.state()["revision"]
        self.assertEqual(self.ob("approve", "demo", "--revision", str(rev), "--statement", "yes, approved",
                                 "--confirm", "--date", "2026-01-02")[0], 0)
        prog = self.root / "programs" / "demo"
        data = miniyaml.loads((prog / "program.yaml").read_text("utf-8"))
        self.assertEqual(data["goal"], "Reach the abstract goal")
        self.assertEqual(data["spec"]["approval"]["statement"], "yes, approved")
        self.assertEqual(data["competencies"][0]["id"], "todo-first-competency")  # no curriculum generated
        self.assertIn("Reach the abstract goal", (prog / "goals.md").read_text("utf-8"))
        self.assertFalse((self.root / "onboarding/demo/program.draft.yaml").exists())
        self.assertEqual(run(self.root, "validate")[0], 0)
        self.assertEqual(self.state()["status"], "approved")
        self.assertEqual(self.ob("brief", "demo")[0], 0)
        # frozen afterwards
        self.assertEqual(self.ob("update", "demo", "--file", "-", stdin="goal:\n  statement: other\n")[0], 2)
        # derived state of the new program is usable by the normal lesson tooling
        self.assertEqual(run(self.root, "context", "demo")[0], 0)

    def test_incomplete_and_resume(self):
        self.ob("start", "demo", "--title", "Demo")
        self.ob("update", "demo", "--file", "-", stdin="goal:\n  statement: Half done\n")
        code, out, err = self.ob("submit", "demo")
        self.assertEqual(code, 2)
        self.assertIn("goal.competency_outcomes", err)
        # "new conversation": nothing but files on disk, a fresh process-level call
        c, out, _ = self.ob("status", "demo")
        self.assertIn("Half done", out)
        self.assertIn("missing:", out)
        self.assertIn("goal-discovery", out)
        self.assertIn("demo\tdraft", self.ob("list")[1])
        self.ob("update", "demo", "--file", "-", stdin=COMPLETE)
        self.assertEqual(self.ob("submit", "demo")[0], 0)

    def test_blocking_question_gates_submit(self):
        self.ready()
        q = "open_questions:\n  - id: q1\n    text: Which?\n    blocking: true\n"
        self.ob("update", "demo", "--file", "-", stdin=q)
        self.assertEqual(self.ob("submit", "demo")[0], 2)
        self.ob("update", "demo", "--file", "-", stdin=q + "    answer: This one\n")
        self.assertEqual(self.ob("submit", "demo")[0], 0)

    def test_nonblocking_question_and_assumptions_recorded(self):
        self.ready()
        self.ob("update", "demo", "--file", "-",
                stdin="assumptions: [no prior tooling]\nopen_questions:\n  - id: q1\n    text: Later?\n    blocking: false\n")
        self.assertEqual(self.ob("submit", "demo")[0], 0)
        goals = (self.root / "onboarding/demo/goals.md").read_text("utf-8")
        self.assertIn("no prior tooling", goals)
        self.assertIn("Later?", goals)

    def test_revision_before_approval(self):
        self.ready()
        self.ob("submit", "demo")
        reviewed = self.state()["revision"]
        self.ob("update", "demo", "--file", "-", stdin="constraints:\n  pace: intensive\n")
        st = self.state()
        self.assertEqual((st["status"], st["revision"]), ("draft", reviewed + 1))
        self.assertEqual(st["constraints"]["pace"], "intensive")
        # cannot approve a draft, nor an older reviewed revision
        args = ("--statement", "yes", "--confirm")
        self.assertEqual(self.ob("approve", "demo", "--revision", str(reviewed), *args)[0], 2)
        self.ob("submit", "demo")
        self.assertEqual(self.ob("approve", "demo", "--revision", str(reviewed), *args)[0], 2)
        self.assertEqual(self.ob("approve", "demo", "--revision", str(reviewed + 1), *args)[0], 0)
        self.assertEqual(miniyaml.loads((self.root / "programs/demo/program.yaml").read_text("utf-8"))
                         ["lesson_policy"]["target_minutes"], 45)

    def test_approval_requires_confirmation_and_statement(self):
        self.ready()
        self.ob("submit", "demo")
        rev = str(self.state()["revision"])
        for extra in (["--statement", "yes"], ["--statement", "  ", "--confirm"]):
            self.assertEqual(self.ob("approve", "demo", "--revision", rev, *extra)[0], 2)
        self.assertFalse((self.root / "programs/demo").exists())
        self.assertEqual(self.state()["status"], "in_review")

    def test_session_minutes_flow_into_lesson_policy(self):
        self.ready()
        self.ob("update", "demo", "--file", "-", stdin="constraints:\n  session_minutes: 25\n")
        self.ob("submit", "demo")
        self.ob("approve", "demo", "--revision", "3", "--statement", "ok", "--confirm")
        self.assertEqual(miniyaml.loads((self.root / "programs/demo/program.yaml").read_text("utf-8"))
                         ["lesson_policy"]["target_minutes"], 25)


class SafetyTests(Base):
    def test_duplicate_onboarding_id(self):
        self.ready()
        before = (self.root / "onboarding/demo/state.yaml").read_text("utf-8")
        self.assertEqual(self.ob("start", "demo", "--title", "Other")[0], 2)
        self.assertEqual((self.root / "onboarding/demo/state.yaml").read_text("utf-8"), before)

    def test_start_refuses_existing_program_and_leaves_it_untouched(self):
        shutil.copytree(FIXTURE_ROOT / "programs" / "sample-program", self.root / "programs" / "sample-program")
        snap = {p: p.read_bytes() for p in (self.root / "programs").rglob("*") if p.is_file()}
        code, _, err = self.ob("start", "sample-program", "--title", "Clash")
        self.assertEqual(code, 2)
        self.assertIn("already exists", err)
        self.assertFalse((self.root / "onboarding").exists())
        self.assertEqual({p: p.read_bytes() for p in (self.root / "programs").rglob("*") if p.is_file()}, snap)

    def test_approve_never_overwrites_program_created_meanwhile(self):
        self.ready()
        self.ob("submit", "demo")
        run(self.root, "new-program", "demo", "--title", "Raced")
        snap = (self.root / "programs/demo/program.yaml").read_bytes()
        self.assertEqual(self.ob("approve", "demo", "--revision", "2", "--statement", "y", "--confirm")[0], 2)
        self.assertEqual((self.root / "programs/demo/program.yaml").read_bytes(), snap)
        self.assertEqual(self.state()["status"], "in_review")
        self.assertEqual(run(self.root, "validate")[0], 1)  # collision is reported

    def test_other_programs_and_progress_untouched_by_approval(self):
        shutil.copytree(FIXTURE_ROOT / "programs" / "sample-program", self.root / "programs" / "sample-program")
        snap = {p: p.read_bytes() for p in (self.root / "programs" / "sample-program").rglob("*") if p.is_file()}
        self.ready()
        self.ob("submit", "demo")
        self.ob("approve", "demo", "--revision", "2", "--statement", "y", "--confirm")
        self.assertEqual({p: p.read_bytes() for p in (self.root / "programs" / "sample-program").rglob("*") if p.is_file()}, snap)

    def test_curriculum_brief_blocked_until_approved(self):
        self.assertEqual(self.ob("brief", "missing")[0], 2)
        self.ready()
        for _ in range(2):  # draft, then in_review
            code, _, err = self.ob("brief", "demo")
            self.assertEqual(code, 2)
            self.assertIn("approval", err)
            self.ob("submit", "demo")
        self.assertFalse((self.root / "programs/demo").exists())
        self.ob("approve", "demo", "--revision", "2", "--statement", "y", "--confirm")
        self.assertEqual(self.ob("brief", "demo")[0], 0)

    def test_no_program_exists_until_approval(self):
        self.ready()
        self.assertEqual(model.list_programs(self.root), [])
        self.ob("submit", "demo")
        self.assertEqual(model.list_programs(self.root), [])


class ValidationTests(Base):
    def test_validate_detects_preview_drift_and_bad_state(self):
        self.ready()
        self.assertEqual(run(self.root, "validate")[0], 0)
        (self.root / "onboarding/demo/goals.md").write_text("tampered")
        self.assertEqual(run(self.root, "validate")[0], 1)
        self.ob("render", "demo")
        self.assertEqual(run(self.root, "validate")[0], 0)
        (self.root / "onboarding/demo/state.yaml").write_text("schema_version: 1\n")
        self.assertEqual(run(self.root, "validate")[0], 1)

    def test_approved_without_program_is_an_error(self):
        self.ready()
        self.ob("submit", "demo")
        self.ob("approve", "demo", "--revision", "2", "--statement", "y", "--confirm")
        shutil.rmtree(self.root / "programs/demo")
        self.assertEqual(run(self.root, "validate")[0], 1)


class RepoTests(unittest.TestCase):
    def test_repo_ships_no_onboarding_or_subject_program(self):
        left = [p.name for p in (REPO / "onboarding").iterdir() if p.name not in (".gitkeep", "README.md")]
        self.assertEqual(left, [])
        left = [p.name for p in (REPO / "programs").iterdir() if p.name not in (".gitkeep", "README.md")]
        self.assertEqual(left, [])

    def test_protocol_commands_and_docs_exist(self):
        self.assertTrue((REPO / "engine/protocol/06-program-onboarding.md").is_file())
        self.assertTrue((REPO / ".claude/commands/onboard.md").is_file())
        self.assertTrue((REPO / "adapters/codex/prompts/onboard.md").is_file())
        self.assertIn("06-program-onboarding.md", (REPO / "AGENTS.md").read_text("utf-8"))
        self.assertIn("06-program-onboarding.md", (REPO / "engine/protocol/README.md").read_text("utf-8"))

    def test_onboarding_module_is_subject_agnostic(self):
        text = (REPO / "scripts/learning_os/onboarding.py").read_text("utf-8")
        text += (REPO / "engine/protocol/06-program-onboarding.md").read_text("utf-8")
        self.assertNotRegex(text, r"(?i)\b(python programming|calculus|spanish|biology|machine learning)\b")


if __name__ == "__main__":
    unittest.main()
