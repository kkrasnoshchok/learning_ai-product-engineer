"""Contracts for the multi-agent layer: config validity, parity, policies, single-writer rule."""
import re
import tomllib
import unittest

from helpers import REPO

ROLES = {"curriculum-designer": "curriculum_designer", "researcher": "researcher", "examiner": "examiner"}
CLAUDE_KEYS = {"name", "description", "tools", "disallowedTools", "model", "permissionMode", "maxTurns",
               "skills", "mcpServers", "hooks", "memory", "background", "effort", "isolation", "color"}
CODEX_KEYS = {"name", "description", "developer_instructions", "model", "model_reasoning_effort",
              "model_reasoning_summary", "model_verbosity", "features", "skills"}
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "Bash"}


def claude_agent(name):
    text = (REPO / ".claude/agents" / f"{name}.md").read_text("utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    assert m, f"{name}: no frontmatter"
    fm = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()
    return fm, m.group(2)


def codex_agent(name):
    return tomllib.loads((REPO / ".codex/agents" / f"{name}.toml").read_text("utf-8"))


class AgentConfigTests(unittest.TestCase):
    def test_exactly_three_subagents_per_tool(self):
        self.assertEqual({p.stem for p in (REPO / ".claude/agents").glob("*.md")}, set(ROLES))
        self.assertEqual({p.stem for p in (REPO / ".codex/agents").glob("*.toml")}, set(ROLES.values()))

    def test_claude_frontmatter_is_valid(self):
        for name in ROLES:
            fm, body = claude_agent(name)
            self.assertEqual(fm["name"], name)
            self.assertTrue(fm["description"])
            self.assertLessEqual(set(fm), CLAUDE_KEYS, name)
            self.assertTrue(body.strip())

    def test_claude_subagents_have_no_write_tools(self):
        for name in ROLES:
            tools = {t.strip() for t in claude_agent(name)[0]["tools"].split(",")}
            self.assertFalse(tools & WRITE_TOOLS, name)
            self.assertTrue(tools, name)

    def test_only_researcher_has_web_tools(self):
        for name in ROLES:
            tools = claude_agent(name)[0]["tools"]
            self.assertEqual("Web" in tools, name == "researcher", name)

    def test_codex_toml_is_valid(self):
        for name, cname in ROLES.items():
            d = codex_agent(cname)
            self.assertEqual(d["name"], cname)
            for key in ("name", "description", "developer_instructions"):
                self.assertTrue(d[key].strip(), key)
            self.assertLessEqual(set(d), CODEX_KEYS, cname)
            for ignored in ("sandbox_mode", "approval_policy", "mcp_servers"):
                self.assertNotIn(ignored, d, f"{cname}: {ignored} is ignored by Codex")

    def test_codex_config_parses(self):
        cfg = tomllib.loads((REPO / ".codex/config.toml").read_text("utf-8"))
        self.assertGreaterEqual(cfg["agents"]["max_concurrent_threads_per_session"], 1)

    def test_codex_instructions_forbid_writes_and_logging(self):
        for cname in ROLES.values():
            text = codex_agent(cname)["developer_instructions"]
            self.assertRegex(text, r"Never write or edit any file")
            self.assertIn("los.py log", text)

    def test_wrappers_point_at_existing_role_files(self):
        for name, cname in ROLES.items():
            self.assertTrue((REPO / "engine/roles" / f"{name}.md").is_file())
            self.assertIn(f"engine/roles/{name}.md", claude_agent(name)[1])
            self.assertIn(f"engine/roles/{name}.md", codex_agent(cname)["developer_instructions"])
        self.assertTrue((REPO / "engine/roles/tutor.md").is_file())

    def test_descriptions_match_across_tools(self):
        for name, cname in ROLES.items():
            self.assertEqual(claude_agent(name)[0]["description"], codex_agent(cname)["description"])

    def test_entry_files_stay_concise_and_mention_roles(self):
        for f, limit in (("AGENTS.md", 60), ("CLAUDE.md", 20)):
            self.assertLessEqual(len((REPO / f).read_text("utf-8").splitlines()), limit, f)
        self.assertIn("engine/policies", (REPO / "AGENTS.md").read_text("utf-8"))


class PolicyContractTests(unittest.TestCase):
    def read(self, rel):
        return (REPO / rel).read_text("utf-8").lower()

    def test_required_policies_are_documented(self):
        topics = {
            "engine/policies/teaching.md": ["adaptive teaching", "socratic", "active recall",
                                            "deliberate practice", "progressive hints"],
            "engine/policies/assessment.md": ["independent assessment", "evidence-based mastery",
                                              "misconception tracking", "spaced repetition", "assisted"],
            "engine/policies/delegation.md": ["single-writer", "minimal context", "session context isolation"],
        }
        for rel, words in topics.items():
            text = self.read(rel)
            for w in words:
                self.assertIn(w, text, f"{rel}: {w}")

    def test_assisted_work_cannot_reach_top_band(self):
        self.assertIn("below 0.9", self.read("engine/policies/assessment.md"))
        self.assertIn("never scores 0.9 or above", self.read("engine/roles/examiner.md"))

    def test_only_tutor_writes_state(self):
        self.assertIn("only writer", self.read("AGENTS.md"))
        self.assertIn("only agent that writes", self.read("engine/policies/delegation.md"))
        for role in ROLES:
            self.assertRegex(self.read(f"engine/roles/{role}.md"), r"not (log|write)|do not|never")

    def test_policies_are_subject_agnostic_and_no_program_created(self):
        programs = [p for p in (REPO / "programs").iterdir() if p.name not in (".gitkeep", "README.md")]
        self.assertEqual(programs, [])
        for path in list((REPO / "engine/policies").glob("*.md")) + list((REPO / "engine/roles").glob("*.md")):
            self.assertNotRegex(path.read_text("utf-8"), r"(?i)\b(python programming|calculus|spanish|biology)\b")


if __name__ == "__main__":
    unittest.main()
