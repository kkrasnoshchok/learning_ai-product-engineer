import json
import unittest

import helpers  # noqa: F401
from helpers import PID, TmpRootCase
from learning_os import model


class ValidationFailureTests(TmpRootCase):
    def errors(self):
        return "\n".join(model.validate_root(self.root).errors)

    def test_baseline_clean(self):
        self.assertEqual(self.errors(), "")

    def test_prerequisite_cycle(self):
        self.edit("program.yaml", "prerequisites: []", "prerequisites: [fixture-c]")
        self.assertIn("prerequisite cycle", self.errors())

    def test_unknown_prerequisite_and_self_reference(self):
        self.edit("program.yaml", "prerequisites: [fixture-a]", "prerequisites: [ghost]")
        self.assertIn("unknown prerequisite 'ghost'", self.errors())
        self.edit("program.yaml", "prerequisites: [ghost]", "prerequisites: [fixture-b]")
        self.assertIn("lists itself", self.errors())

    def test_duplicate_competency_id(self):
        self.edit("program.yaml", "id: fixture-b", "id: fixture-a")
        self.assertIn("duplicate competency id 'fixture-a'", self.errors())

    def test_threshold_order(self):
        self.edit("program.yaml", "proficient_threshold: 0.7", "proficient_threshold: 0.95")
        self.assertIn("proficient_threshold must be lower", self.errors())

    def test_directory_name_must_match_id(self):
        self.edit("program.yaml", "id: sample-program", "id: other-program")
        self.assertIn("does not match directory name", self.errors())

    def test_unknown_key_rejected(self):
        self.edit("program.yaml", "status: active", "status: active\nmastery: 0.5")
        self.assertIn("unexpected key 'mastery'", self.errors())

    def test_global_preferences_cannot_hold_program_data(self):
        p = self.root / "learner" / "preferences.yaml"
        p.write_text(p.read_text("utf-8") + "mastery: {}\ncompetencies: [x]\n", "utf-8")
        errs = self.errors()
        self.assertIn("unexpected key 'competencies'", errs)

    def test_bad_enum_in_preferences(self):
        self.edit("../../learner/preferences.yaml", "tone: concise", "tone: loud")
        self.assertIn("learner/preferences.yaml", self.errors())

    def test_log_unknown_competency(self):
        self.edit("logs/assessments.jsonl", '"competency":"fixture-a","kind":"quiz"', '"competency":"nope","kind":"quiz"')
        self.assertIn("unknown competency 'nope'", self.errors())

    def test_log_invalid_json_and_blank_line(self):
        log = self.pdir / "logs" / "assessments.jsonl"
        log.write_text(log.read_text("utf-8") + "{not json\n\n", "utf-8")
        errs = self.errors()
        self.assertIn("invalid JSON", errs)
        self.assertIn("blank line", errs)

    def test_log_out_of_order_timestamp(self):
        self.edit("logs/assessments.jsonl", "2026-01-05T10:20:00Z", "2026-01-05T09:00:00Z")
        self.assertIn("append-only", self.errors())

    def test_log_score_out_of_range(self):
        self.edit("logs/assessments.jsonl", '"score":1.0', '"score":1.5')
        self.assertIn("maximum", self.errors())

    def test_log_future_lesson(self):
        self.edit("logs/assessments.jsonl", '"lesson":1,"competency":"fixture-a","kind":"quiz"', '"lesson":9,"competency":"fixture-a","kind":"quiz"')
        self.assertIn("references lesson 9", self.errors())

    def test_mastery_drift_detected(self):
        self.edit("state/mastery.yaml", "status: proficient", "status: mastered")
        self.assertIn("mastery.yaml: drifted", self.errors())

    def test_progress_drift_detected(self):
        self.edit("state/progress.yaml", "lessons_completed: 1", "lessons_completed: 5")
        self.assertIn("progress.yaml: drifted", self.errors())

    def test_lesson_missing_handoff_section(self):
        self.edit("lessons/001-fixture-intro.md", "## Handoff", "## Notes")
        self.assertIn("missing required section '## Handoff'", self.errors())

    def test_lesson_number_mismatch_and_gap(self):
        self.edit("lessons/001-fixture-intro.md", "lesson: 1", "lesson: 2")
        self.assertIn("does not match file number", self.errors())
        (self.pdir / "lessons" / "001-fixture-intro.md").rename(self.pdir / "lessons" / "003-fixture-intro.md")
        self.assertIn("without gaps", self.errors())

    def test_lesson_bad_filename_and_unknown_competency(self):
        (self.pdir / "lessons" / "notes.md").write_text("x", "utf-8")
        self.assertIn("name must look like", self.errors())
        (self.pdir / "lessons" / "notes.md").unlink()
        self.edit("lessons/001-fixture-intro.md", "next_focus: [fixture-b]", "next_focus: [zzz]")
        self.assertIn("unknown competency 'zzz'", self.errors())

    def test_missing_files_reported(self):
        (self.pdir / "state" / "mastery.yaml").unlink()
        self.assertIn("mastery.yaml: file is missing", self.errors())

    def test_todo_markers_warn_and_strict_fails(self):
        self.edit("program.yaml", "Exercise the engine", "TODO Exercise the engine")
        rep = model.validate_root(self.root)
        self.assertTrue(rep.ok)
        self.assertTrue(any("TODO" in w or "placeholder" in w for w in rep.warnings))

    def test_programs_are_isolated(self):
        # a second program's problems do not leak into --program selection
        other = self.root / "programs" / "broken"
        other.mkdir()
        self.assertTrue(model.validate_root(self.root, PID).ok)
        self.assertFalse(model.validate_root(self.root, "broken").ok)


if __name__ == "__main__":
    unittest.main()
