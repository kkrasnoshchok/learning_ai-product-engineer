import contextlib
import io
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

import helpers
from helpers import FIXTURE_ROOT, REPO, TmpRootCase
from learning_os import cli, model


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(args))
        except SystemExit as exc:  # argparse usage errors
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class WorkflowTests(unittest.TestCase):
    """End-to-end: scaffold -> author -> log -> lesson record -> close -> context."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "programs").mkdir()
        shutil.copytree(FIXTURE_ROOT / "learner", self.root / "learner")
        self.r = ["--root", str(self.root)]

    def test_full_lesson_cycle(self):
        code, out, _ = run(*self.r, "new-program", "demo", "--title", "Demo: a \"quoted\" title", "--created", "2026-03-01")
        self.assertEqual(code, 0, out)

        # fresh scaffold validates with warnings; strict mode rejects the TODO stubs
        self.assertEqual(run(*self.r, "validate")[0], 0)
        self.assertEqual(run(*self.r, "validate", "--strict")[0], 1)

        # author a real (abstract) competency set
        pf = self.root / "programs" / "demo" / "program.yaml"
        text = pf.read_text("utf-8")
        text = text.replace("todo-first-competency", "step-one").replace("TODO: name the first competency", "Step one")
        text = text.replace("TODO: observable description of what mastery looks like.", "Does step one.")
        text = text.replace("TODO: one or two sentences describing what the learner will be able to do.", "Reach the goal.")
        pf.write_text(text, "utf-8")
        self.assertEqual(run(*self.r, "rebuild", "demo")[0], 0)
        self.assertEqual(run(*self.r, "validate", "--strict")[0], 0)

        # log events (mastery refreshes automatically)
        for i, score in enumerate(["0.9", "0.95"]):
            code, out, _ = run(*self.r, "log", "demo", "--lesson", "1", "--competency", "step-one", "--kind", "quiz",
                               "--score", score, "--ts", f"2026-03-02T09:0{i}:00Z")
            self.assertEqual(code, 0, out)
        mastery = (self.root / "programs/demo/state/mastery.yaml").read_text("utf-8")
        self.assertIn("status: mastered", mastery)  # EWMA 0.925 >= 0.9 with 2 events

        # write the lesson record from the template and close
        rec = (REPO / "engine/templates/lesson-record.md").read_text("utf-8")
        rec = (rec.replace("__PROGRAM_ID__", "demo").replace("__LESSON_NUMBER__", "1")
                  .replace("__DATE__", "2026-03-02").replace("__TITLE__", "First lesson"))
        (self.root / "programs/demo/lessons/001-first-lesson.md").write_text(rec, "utf-8")
        code, out, _ = run(*self.r, "close", "demo", "--lesson", "1")
        self.assertEqual(code, 0, out)
        self.assertIn("lessons_completed: 1", (self.root / "programs/demo/state/progress.yaml").read_text("utf-8"))

        code, out, _ = run(*self.r, "context", "demo", "--today", "2026-03-03")
        self.assertEqual(code, 0)
        self.assertIn("Lesson context pack: Demo: a \"quoted\" title", out)
        self.assertIn("Lesson 1: First lesson", out)

    def test_new_program_rejects_bad_or_duplicate_ids(self):
        for bad in ["Has Caps", "../escape", "a/b", "", "x" * 49, "-lead"]:
            with self.subTest(bad=bad):
                self.assertEqual(run(*self.r, "new-program", bad, "--title", "t")[0], 2)
        self.assertEqual(run(*self.r, "new-program", "ok", "--title", "t")[0], 0)
        self.assertEqual(run(*self.r, "new-program", "ok", "--title", "t")[0], 2)

    def test_two_programs_stay_independent(self):
        run(*self.r, "new-program", "one", "--title", "One")
        run(*self.r, "new-program", "two", "--title", "Two")
        pf = self.root / "programs/one/program.yaml"
        pf.write_text(pf.read_text("utf-8").replace("todo-first-competency", "only-in-one"), "utf-8")
        run(*self.r, "rebuild", "one")
        self.assertNotIn("only-in-one", (self.root / "programs/two/program.yaml").read_text("utf-8"))
        self.assertNotIn("only-in-one", (self.root / "programs/two/state/mastery.yaml").read_text("utf-8"))


class LogGuardTests(TmpRootCase):
    def setUp(self):
        super().setUp()
        self.r = ["--root", str(self.root)]

    def test_log_rejects_bad_input_without_touching_file(self):
        log = self.pdir / "logs" / "assessments.jsonl"
        before = log.read_text("utf-8")
        cases = [
            ["--competency", "ghost", "--kind", "quiz", "--score", "0.5"],
            ["--competency", "fixture-a", "--kind", "vibes", "--score", "0.5"],
            ["--competency", "fixture-a", "--kind", "quiz", "--score", "1.2"],
            ["--competency", "fixture-a", "--kind", "quiz", "--score", "0.5", "--ts", "2025-01-01T00:00:00Z"],
        ]
        for c in cases:
            with self.subTest(case=c):
                self.assertEqual(run(*self.r, "log", "sample-program", "--lesson", "1", *c)[0], 2)
        self.assertEqual(log.read_text("utf-8"), before)

    def test_log_appends_exactly_one_line_and_keeps_prefix(self):
        log = self.pdir / "logs" / "assessments.jsonl"
        before = log.read_text("utf-8")
        code, out, _ = run(*self.r, "log", "sample-program", "--lesson", "2", "--competency", "fixture-b",
                           "--kind", "practice", "--score", "0.6", "--ts", "2026-01-10T10:00:00Z")
        self.assertEqual(code, 0, out)
        after = log.read_text("utf-8")
        self.assertTrue(after.startswith(before))
        self.assertEqual(len(after[len(before):].strip().split("\n")), 1)
        json.loads(after.strip().split("\n")[-1])
        self.assertEqual(run(*self.r, "validate")[0], 0)

    def test_close_requires_lesson_record(self):
        self.assertEqual(run(*self.r, "close", "sample-program", "--lesson", "2")[0], 2)

    def test_cli_validate_reports_failure_exit_code(self):
        self.edit("state/mastery.yaml", "status: proficient", "status: unseen")
        self.assertEqual(run(*self.r, "validate")[0], 1)
        self.assertEqual(run(*self.r, "rebuild", "sample-program")[0], 0)
        self.assertEqual(run(*self.r, "validate")[0], 0)


if __name__ == "__main__":
    unittest.main()
