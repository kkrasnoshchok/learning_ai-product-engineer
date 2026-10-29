import unittest
from datetime import date

import helpers
from helpers import FIXTURE_ROOT, PID, TmpRootCase
from learning_os import miniyaml, model


class FixtureTests(unittest.TestCase):
    def test_fixture_root_is_clean(self):
        rep = model.validate_root(FIXTURE_ROOT)
        self.assertEqual((rep.errors, rep.warnings), ([], []))

    def test_mastery_derivation(self):
        program = miniyaml.loads((FIXTURE_ROOT / "programs" / PID / "program.yaml").read_text("utf-8"))
        events, _ = model.read_events(FIXTURE_ROOT / "programs" / PID / "logs" / "assessments.jsonl")
        m = model.derive_mastery(program, events)["competencies"]
        self.assertEqual(m["fixture-a"]["score"], 0.8)  # 0.4 -> 0.6 -> 0.8 with alpha 0.5
        self.assertEqual(m["fixture-a"]["status"], "proficient")
        self.assertEqual(m["fixture-b"]["status"], "unseen")

    def test_status_needs_min_evidence(self):
        program = miniyaml.loads((FIXTURE_ROOT / "programs" / PID / "program.yaml").read_text("utf-8"))
        ev = {"competency": "fixture-a", "score": 1.0, "ts": "2026-01-05T10:00:00Z"}
        self.assertEqual(model.derive_mastery(program, [ev])["competencies"]["fixture-a"]["status"], "learning")
        self.assertEqual(model.derive_mastery(program, [ev, ev])["competencies"]["fixture-a"]["status"], "mastered")


class ContextPackTests(unittest.TestCase):
    def pack(self, today):
        return model.build_context(FIXTURE_ROOT, PID, date.fromisoformat(today))

    def test_contains_prefs_state_and_handoff(self):
        out = self.pack("2026-01-06")
        self.assertIn("tone: concise", out)
        self.assertIn("| fixture-a | Fixture competency A | proficient | 0.8 |", out)
        self.assertIn("Start fixture-b next.", out)
        self.assertIn("planned by the previous lesson", out)

    def test_excludes_archive_and_title_only_history(self):
        out = self.pack("2026-01-06")
        self.assertNotIn("SECRET-HISTORY", out)

    def test_focus_gates_on_prerequisites(self):
        out = self.pack("2026-01-06")
        self.assertIn("`fixture-b`", out)
        self.assertNotIn("`fixture-c`", out.split("## Suggested focus")[1].split("## Previous")[0])

    def test_review_due_only_after_interval(self):
        self.assertNotIn("review due", self.pack("2026-01-06"))
        self.assertIn("review due (last assessed 2026-01-05)", self.pack("2026-02-01"))


class ContextHistoryLimit(TmpRootCase):
    def test_zero_history_omits_handoffs(self):
        self.edit("program.yaml", "history_lessons_in_context: 1", "history_lessons_in_context: 0")
        out = model.build_context(self.root, PID, date(2026, 1, 6))
        self.assertNotIn("Start fixture-b next.", out)

    def test_invalid_program_refuses_to_build_context(self):
        self.edit("logs/assessments.jsonl", '"score":0.4', '"score":0.5')
        with self.assertRaises(ValueError):
            model.build_context(self.root, PID, date(2026, 1, 6))


if __name__ == "__main__":
    unittest.main()
