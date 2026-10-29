"""Guards for the architectural rules in the brief."""
import re
import unittest

import helpers
from helpers import REPO
from learning_os import model

FORBIDDEN_IMPORTS = {"urllib", "http", "https", "requests", "httpx", "socket", "ssl", "aiohttp",
                     "anthropic", "openai", "ftplib", "smtplib", "websockets"}


class PolicyTests(unittest.TestCase):
    def test_repo_root_validates(self):
        rep = model.validate_root(REPO)
        self.assertEqual(rep.errors, [])

    def test_no_network_or_api_code(self):
        for path in (REPO / "scripts").rglob("*.py"):
            text = path.read_text("utf-8")
            for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_][\w]*)", text, re.M):
                self.assertNotIn(m.group(1), FORBIDDEN_IMPORTS, f"{path.name} imports {m.group(1)}")
            self.assertNotRegex(text, r"(?i)api[_-]?key|ANTHROPIC_|OPENAI_")

    def test_no_third_party_dependency_files(self):
        for name in ("requirements.txt", "pyproject.toml", "package.json", "Pipfile"):
            self.assertFalse((REPO / name).exists(), f"{name}: engine must stay stdlib-only")

    def test_no_web_ui_or_backend(self):
        for pattern in ("**/index.html", "**/server.py", "**/app.py", "**/package.json"):
            hits = [p for p in REPO.glob(pattern) if ".git" not in p.parts]
            self.assertEqual(hits, [], pattern)

    def test_archive_is_gitignored_and_forbidden_to_agents(self):
        gi = (REPO / ".gitignore").read_text("utf-8")
        self.assertIn("archive/*", gi)
        for entry in ("AGENTS.md", "engine/protocol/01-session-start.md"):
            self.assertIn("archive/", (REPO / entry).read_text("utf-8"), entry)

    def test_both_agents_have_entry_points_and_docs(self):
        self.assertIn("engine/protocol", (REPO / "AGENTS.md").read_text("utf-8"))
        self.assertIn("@AGENTS.md", (REPO / "CLAUDE.md").read_text("utf-8"))
        for doc in ("docs/claude.md", "docs/codex.md", "docs/architecture.md", "docs/data-formats.md"):
            self.assertTrue((REPO / doc).is_file(), doc)
        for cmd in ("lesson", "new-program", "close-lesson"):
            self.assertTrue((REPO / ".claude" / "commands" / f"{cmd}.md").is_file(), cmd)

    def test_template_has_only_a_placeholder_competency(self):
        tpl = (REPO / "engine/templates/program/program.yaml").read_text("utf-8")
        self.assertIn("todo-first-competency", tpl)
        self.assertEqual(tpl.count("- id:"), 1)

    def test_protocol_docs_referenced_by_readme_exist(self):
        index = (REPO / "engine/protocol/README.md").read_text("utf-8")
        for name in re.findall(r"\((0\d-[\w-]+\.md)\)", index):
            self.assertTrue((REPO / "engine/protocol" / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
