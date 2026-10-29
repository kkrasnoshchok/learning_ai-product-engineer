"""Phase 4: research planning, source registry, competency map, curriculum, approval, activation.
All content is abstract and synthetic; no external research is performed or simulated as real."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
from helpers import FIXTURE_ROOT
from learning_os import design, miniyaml, model
from test_onboarding import COMPLETE, run


def dump(x):
    return miniyaml.dumps(x)


def plan_patch():
    return {
        "questions": [
            {"id": "q1", "text": "What must a practitioner do for thing a?", "outcomes": ["outcome-1"], "priority": "high"},
            {"id": "q2", "text": "How is artifact b built and judged?", "outcomes": ["outcome-2"], "priority": "medium"}],
        "source_categories": [{"id": "cat-docs", "type": "official-docs", "purpose": "authoritative definitions", "min_sources": 1}],
        "gaps": [{"id": "gap-1", "text": "Typical depth is unknown"}],
        "tasks": [{"id": "t1", "question": "q1", "category": "cat-docs", "description": "Find definitions"},
                  {"id": "t2", "question": "q2", "category": "cat-docs", "description": "Find practice guidance"}]}


def src(sid, status="inspected", q="q1", **kw):
    s = {"id": sid, "title": f"Synthetic source {sid}", "url": f"https://example.invalid/{sid}", "type": "official-docs",
         "status": status, "relevance": {"questions": [q], "note": "bears on the question"},
         "quality": {"rating": "high" if status in ("inspected", "verified") else "unrated", "rationale": "synthetic"},
         "limitations": "synthetic fixture"}
    if status in ("inspected", "verified"):
        s.update(accessed="2026-01-05", inspection="learner-provided")
    s.update(kw)
    return s


def research_patch():
    return {"browsing": "unavailable", "sources": [src("s1"), src("s2", "discovered", q="q2")],
            "findings": [{"id": "f1", "kind": "claim", "text": "A synthetic claim", "status": "verified",
                          "sources": ["s1"], "questions": ["q1"], "confidence": "medium"},
                         {"id": "f2", "kind": "hypothesis", "text": "A model guess", "status": "unverified",
                          "sources": [], "questions": ["q2"], "confidence": "low"}],
            "tasks": [{"id": "t1", "status": "done"}],
            "limitations": ["No web tools in this session"]}


def comp(cid, prereqs=(), sources=("s1",), **kw):
    c = {"id": cid, "name": f"Competency {cid}", "description": f"Can do {cid}",
         "objectives": [{"id": "o1", "text": f"Do {cid} unaided"}], "prerequisites": list(prereqs),
         "priority": "core", "level": "working", "sources": list(sources),
         "assessment_criteria": [{"objective": "o1", "criterion": f"{cid} done correctly"}],
         "applications": ["synthetic use"]}
    c.update(kw)
    return c


def map_patch():
    return {"competencies": [comp("a"), comp("b", ["a"]), comp("c", ["b"])]}


def module(mid, cid, prereqs=(), hours=8, purpose="mastery", **kw):
    m = {"id": mid, "title": f"Module {mid}", "competencies": [cid], "objectives": [f"{cid}:o1"],
         "prerequisites": list(prereqs), "resources": [{"source": "s1", "use": "primary"}],
         "exercises": [{"id": f"ex-{mid}", "title": "practice", "objectives": [f"{cid}:o1"], "est_hours": 2}],
         "assessments": [{"id": f"as-{mid}", "title": "check", "objectives": [f"{cid}:o1"], "purpose": purpose,
                          "independent": True}],
         "completion_criteria": ["passes the independent assessment"], "est_hours": hours}
    m.update(kw)
    return m


def curriculum_patch():
    return {"personalization": {
        "decisions": [
            {"competency": "a", "disposition": "verify", "rationale": "claims experience; unproven",
             "evidence": [{"kind": "self_reported", "ref": "profile.prior_experience"}]},
            {"competency": "b", "disposition": "study", "rationale": "core to the goal",
             "evidence": [{"kind": "goal", "ref": "goal.competency_outcomes"}]},
            {"competency": "c", "disposition": "deprioritize", "rationale": "outside stated outcomes",
             "evidence": [{"kind": "goal", "ref": "goal.success_criteria"}]}],
        "sequence": ["a", "b"]},
        "modules": [module("m1", "a", purpose="diagnostic", hours=6), module("m2", "b", ["m1"])],
        "checkpoints": [{"id": "cp1", "title": "Review a and b", "after_module": "m2", "reviews": ["a", "b"]}]}


def tweak(patch, fn):
    p = copy.deepcopy(patch)
    fn(p)
    return p


class Base(unittest.TestCase):
    pid = "demo"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "programs").mkdir()
        shutil.copytree(FIXTURE_ROOT / "learner", self.root / "learner")

    def onboard(self, pid=None, deadline=None):
        pid = pid or self.pid
        run(self.root, "onboarding", "start", pid, "--title", "Demo", "--created", "2026-01-01")
        run(self.root, "onboarding", "update", pid, "--file", "-", stdin=COMPLETE.replace("deadline: none", f"deadline: {deadline}") if deadline else COMPLETE)
        run(self.root, "onboarding", "submit", pid)
        rev = onboarding_rev(self.root, pid)
        c = run(self.root, "onboarding", "approve", pid, "--revision", str(rev), "--statement", "yes", "--confirm", "--date", "2026-01-02")
        self.assertEqual(c[0], 0, c)

    def r(self, *a, data=None):
        return run(self.root, *a, stdin=None if data is None else dump(data))

    def ok(self, *a, data=None):
        c = self.r(*a, data=data)
        self.assertEqual(c[0], 0, c)
        return c[1]

    def fail(self, *a, data=None, expect=""):
        c, out, err = self.r(*a, data=data)
        self.assertNotEqual(c, 0, out)
        self.assertIn(expect, err + out)

    def approve_plan(self, pid=None):
        pid = pid or self.pid
        self.ok("research", "init", pid, "--today", "2026-01-03")
        self.ok("research", "plan-update", pid, "--file", "-", data=plan_patch())
        self.ok("research", "plan-submit", pid)
        self.ok("research", "plan-approve", pid, "--revision", "2", "--statement", "approve plan", "--confirm", "--today", "2026-01-03")

    def to_review(self, patch=None, pid=None):
        pid = pid or self.pid
        self.approve_plan(pid)
        self.ok("research", "add", pid, "--file", "-", data=research_patch())
        self.ok("curriculum", "competencies-set", pid, "--file", "-", "--today", "2026-01-04", data=map_patch())
        self.ok("curriculum", "update", pid, "--file", "-", data=patch or curriculum_patch())
        self.ok("curriculum", "submit", pid, "--today", "2026-01-05")

    def cur(self):
        return design.load_curriculum(self.root, self.pid)

    def design_bytes(self, pid):
        d = self.root / "programs" / pid
        return {str(p.relative_to(d)): p.read_bytes() for p in d.rglob("*") if p.is_file()}


def onboarding_rev(root, pid):
    from learning_os import onboarding
    return onboarding.load_state(root, pid)["revision"]


class GateTests(Base):
    def test_requires_approved_onboarding(self):
        run(self.root, "onboarding", "start", "demo", "--title", "Demo")
        self.fail("research", "init", "demo", expect="approved")
        self.fail("research", "init", "ghost", expect="does not exist")

    def test_existing_programs_without_onboarding_are_untouched(self):
        shutil.copytree(FIXTURE_ROOT / "programs" / "sample-program", self.root / "programs" / "sample-program")
        before = self.design_bytes("sample-program")
        self.fail("research", "init", "sample-program", expect="onboarding")
        self.fail("curriculum", "update", "sample-program", "--file", "-", data=curriculum_patch(), expect="")
        self.assertEqual(before, self.design_bytes("sample-program"))
        self.assertEqual(run(self.root, "validate", "--strict")[0], 0)


class PlanTests(Base):
    def test_plan_is_seeded_from_spec_and_has_no_findings(self):
        self.onboard()
        self.ok("research", "init", "demo")
        plan = design.load_plan(self.root, "demo")
        self.assertEqual([o["text"] for o in plan["outcomes"]], ["can do thing a", "produce artifact b"])
        self.assertTrue(plan["quality_criteria"])
        self.assertFalse((self.root / "programs/demo/design/research/registry.yaml").exists())  # planning != research
        self.fail("research", "add", "demo", "--file", "-", data={"sources": [src("s1")]}, expect="not approved")

    def test_incomplete_plan_cannot_be_submitted(self):
        self.onboard()
        self.ok("research", "init", "demo")
        self.fail("research", "plan-submit", "demo", expect="no research questions")
        bad = tweak(plan_patch(), lambda p: p["tasks"].pop())
        self.ok("research", "plan-update", "demo", "--file", "-", data=bad)
        self.fail("research", "plan-submit", "demo", expect="has no research task")

    def test_plan_reference_errors(self):
        self.onboard()
        self.ok("research", "init", "demo")
        bad = tweak(plan_patch(), lambda p: p["tasks"][0].update(category="nope"))
        self.ok("research", "plan-update", "demo", "--file", "-", data=bad)
        self.fail("research", "plan-submit", "demo", expect="unknown source category")

    def test_approval_rules_and_registry_creation(self):
        self.onboard()
        self.ok("research", "init", "demo")
        self.ok("research", "plan-update", "demo", "--file", "-", data=plan_patch())
        self.fail("research", "plan-approve", "demo", "--revision", "2", "--statement", "y", "--confirm", expect="in_review")
        self.ok("research", "plan-submit", "demo")
        self.fail("research", "plan-approve", "demo", "--revision", "2", "--statement", "y", expect="--confirm")
        self.fail("research", "plan-approve", "demo", "--revision", "1", "--statement", "y", "--confirm", expect="reviewed revision 1")
        self.ok("research", "plan-approve", "demo", "--revision", "2", "--statement", "y", "--confirm")
        reg = design.load_registry(self.root, "demo")
        self.assertEqual([t["status"] for t in reg["tasks"]], ["pending", "pending"])
        # editing re-opens the plan; the approved snapshot is preserved and research pauses
        gap = {"gaps": [{"id": "gap-2", "text": "new"}]}
        self.ok("research", "plan-update", "demo", "--file", "-", data=gap)
        plan = design.load_plan(self.root, "demo")
        self.assertEqual((plan["status"], plan["revision"]), ("draft", 3))
        self.assertNotIn("approval", plan)
        self.assertTrue((self.root / "programs/demo/design/research/versions/plan-r002.yaml").is_file())
        self.fail("research", "add", "demo", "--file", "-", data={"sources": [src("s1")]}, expect="not approved")
        self.fail("research", "plan-approve", "demo", "--revision", "2", "--statement", "y", "--confirm", expect="draft")


class RegistryTests(Base):
    def setUp(self):
        super().setUp()
        self.onboard()
        self.approve_plan()

    def add(self, patch):
        return self.r("research", "add", "demo", "--file", "-", data=patch)

    def test_valid_registry_keeps_pending_tasks_and_limitations(self):
        self.ok("research", "add", "demo", "--file", "-", data=research_patch())
        reg = design.load_registry(self.root, "demo")
        self.assertEqual({t["id"]: t["status"] for t in reg["tasks"]}, {"t1": "done", "t2": "pending"})
        self.assertEqual(reg["browsing"], "unavailable")
        self.assertEqual(reg["limitations"][0]["text"], "No web tools in this session")
        self.assertEqual(run(self.root, "validate")[0], 0)  # not --strict: the placeholder curriculum still warns

    def test_source_metadata_rules(self):
        cases = {
            "url or a bibliographic": src("x", url=None),
            "date accessed": tweak(src("x"), lambda s: s.pop("accessed")),
            "inspection": tweak(src("x"), lambda s: s.pop("inspection")),
            "cannot claim an inspection": src("x", "discovered", inspection="browsed"),
            "quality-rated": src("x", "verified", quality={"rating": "unrated", "rationale": "r"}),
            "unknown question": src("x", q="q9"),
            "no research question": src("x", relevance={"questions": [], "note": "n"}),
        }
        for expect, s in cases.items():
            if s.get("url", 1) is None:
                s = {k: v for k, v in s.items() if k != "url"}
            c, _, err = self.add({"sources": [s]})
            self.assertEqual(c, 2, expect)
            self.assertIn(expect, err)
        self.assertEqual(design.load_registry(self.root, "demo")["sources"], [])  # nothing half-written

    def test_fabrication_guards(self):
        self.ok("research", "add", "demo", "--file", "-", data={"browsing": "unavailable"})
        c, _, err = self.add({"sources": [src("x", inspection="browsed")]})
        self.assertIn("unavailable", err)
        self.assertEqual(self.add({"sources": [src("s2", "discovered")]})[0], 0)
        claim = {"id": "f", "kind": "claim", "text": "t", "status": "verified", "sources": ["s2"], "questions": ["q1"], "confidence": "low"}
        self.assertIn("at least one inspected source", self.add({"findings": [claim]})[2])
        self.assertIn("unknown source", self.add({"findings": [dict(claim, sources=["ghost"])]})[2])
        hyp = dict(claim, kind="hypothesis")
        self.assertIn("can never be 'verified'", self.add({"findings": [hyp]})[2])
        self.assertEqual(self.add({"findings": [dict(hyp, status="unverified")]})[0], 0)

    def test_blocked_tasks_need_a_reason_and_unknown_fields_fail(self):
        self.assertIn("note", self.add({"tasks": [{"id": "t1", "status": "blocked"}]})[2])
        self.assertEqual(self.add({"tasks": [{"id": "t1", "status": "blocked", "note": "no browsing"}]})[0], 0)
        self.assertNotEqual(self.add({"sources": [dict(src("x"), quote="verbatim text")]})[0], 0)  # no quote field exists

    def test_upsert_replaces_by_id(self):
        self.add({"sources": [src("s1")]})
        self.add({"sources": [src("s1", "verified")]})
        reg = design.load_registry(self.root, "demo")
        self.assertEqual([s["status"] for s in reg["sources"]], ["verified"])

    def test_targeted_brief(self):
        self.ok("research", "add", "demo", "--file", "-", data=research_patch())
        out = self.ok("research", "brief", "demo", "--question", "q1")
        self.assertIn("s1", out)
        self.assertNotIn("Synthetic source s2", out)  # q2's source is not loaded
        self.assertIn("browsing: unavailable", self.ok("research", "brief", "demo"))
        full = self.ok("research", "brief", "demo", "--source", "s1")
        self.assertIn("https://example.invalid/s1", full)
        self.assertIn("f1", full)
        self.fail("research", "brief", "demo", "--question", "zz", expect="unknown question")


class MapTests(Base):
    def setUp(self):
        super().setUp()
        self.onboard()
        self.approve_plan()
        self.ok("research", "add", "demo", "--file", "-", data=research_patch())

    def put(self, patch):
        return self.r("curriculum", "competencies-set", "demo", "--file", "-", data=patch)

    def test_valid_map_and_revisions_preserved(self):
        self.assertEqual(self.put(map_patch())[0], 0)
        m2 = map_patch()
        m2["competencies"][2]["priority"] = "supplementary"
        self.assertEqual(self.put(m2)[0], 0)
        self.assertEqual(design.load_map(self.root, "demo")["revision"], 2)
        self.assertTrue((self.root / "programs/demo/design/versions/competencies-r001.yaml").is_file())
        self.assertEqual(self.put(m2)[0], 0)  # no-op
        self.assertEqual(design.load_map(self.root, "demo")["revision"], 2)

    def test_graph_integrity(self):
        base = map_patch()
        cases = {
            "duplicate competency id": tweak(base, lambda p: p["competencies"].append(comp("a"))),
            "missing prerequisite": tweak(base, lambda p: p["competencies"][1].update(prerequisites=["zzz"])),
            "itself as a prerequisite": tweak(base, lambda p: p["competencies"][0].update(prerequisites=["a"])),
            "prerequisite cycle": tweak(base, lambda p: p["competencies"][0].update(prerequisites=["c"])),
            "nonexistent source": tweak(base, lambda p: p["competencies"][0].update(sources=["ghost"])),
            "invalid objective": tweak(base, lambda p: p["competencies"][0]["assessment_criteria"].append({"objective": "o9", "criterion": "x"})),
            "no assessment criterion": tweak(base, lambda p: p["competencies"][0]["objectives"].append({"id": "o2", "text": "more"})),
            "duplicate objective": tweak(base, lambda p: p["competencies"][0]["objectives"].append({"id": "o1", "text": "again"})),
        }
        for expect, patch in cases.items():
            c, _, err = self.put(patch)
            self.assertEqual(c, 2, expect)
            self.assertIn(expect, err)
        self.assertFalse((self.root / "programs/demo/design/competencies.yaml").exists())

    def test_requires_evidence_fields(self):
        p = tweak(map_patch(), lambda x: x["competencies"][0].update(sources=[]))
        self.assertEqual(self.put(p)[0], 2)

    def test_domain_map_has_no_learner_data(self):
        self.put(map_patch())
        text = (self.root / "programs/demo/design/competencies.yaml").read_text("utf-8")
        for word in ("prior_experience", "hours_per_week", "deprioritize", "self_reported"):
            self.assertNotIn(word, text)


class CurriculumTests(Base):
    def setUp(self):
        super().setUp()
        self.onboard()
        self.approve_plan()
        self.ok("research", "add", "demo", "--file", "-", data=research_patch())
        self.ok("curriculum", "competencies-set", "demo", "--file", "-", data=map_patch())

    def draft(self, patch):
        self.ok("curriculum", "update", "demo", "--file", "-", data=patch)
        return self.r("curriculum", "check", "demo", "--today", "2026-01-05")

    def test_valid_draft_passes_check(self):
        c, out, err = self.draft(curriculum_patch())
        self.assertEqual(c, 0, out + err)

    def test_empty_draft_is_incomplete(self):
        self.ok("curriculum", "update", "demo", "--file", "-", data={"checkpoints": []})
        c, out, _ = self.r("curriculum", "check", "demo")
        self.assertEqual(c, 1)
        self.assertIn("no decision for competency", out)

    def test_self_reported_experience_is_not_mastery(self):
        p = tweak(curriculum_patch(), lambda x: x["personalization"]["decisions"][0].update(
            disposition="deprioritize", evidence=[{"kind": "self_reported", "ref": "profile.prior_experience"}]))
        p["personalization"]["sequence"] = ["b"]
        p["modules"] = [p["modules"][1]]
        p["modules"][0]["prerequisites"] = []
        p["checkpoints"][0]["reviews"] = ["b"]
        c, out, _ = self.draft(p)
        self.assertEqual(c, 1)
        self.assertIn("self-report is not mastery", out)
        # with diagnostic evidence the same decision is acceptable
        p["personalization"]["decisions"][0]["evidence"] = [{"kind": "diagnostic", "ref": "diagnostics[0]"}]
        self.assertEqual(self.draft(p)[0], 0)

    def test_prerequisite_assumed_without_diagnostic(self):
        p = tweak(curriculum_patch(), lambda x: x["personalization"]["decisions"][0].update(
            disposition="deprioritize", evidence=[{"kind": "goal", "ref": "out of scope"}]))
        p["personalization"]["sequence"] = ["b"]
        p["modules"] = [tweak({"m": p["modules"][1]}, lambda y: y["m"].update(prerequisites=[]))["m"]]
        p["checkpoints"][0]["reviews"] = ["b"]
        self.assertIn("prerequisite gap", self.draft(p)[1])

    def test_structural_errors(self):
        base = curriculum_patch()
        cases = {
            "not covered by any module": tweak(base, lambda p: p.update(modules=[p["modules"][0]], checkpoints=[])),
            "invalid objective reference": tweak(base, lambda p: p["modules"][0]["objectives"].append("a:zzz")),
            "must be listed earlier": tweak(base, lambda p: p["modules"][0].update(prerequisites=["m2"])),
            "unknown prerequisite module": tweak(base, lambda p: p["modules"][1].update(prerequisites=["mx"])),
            "never inspected": tweak(base, lambda p: p["modules"][0]["resources"].append({"source": "s2", "use": "supplementary"})),
            "nonexistent source": tweak(base, lambda p: p["modules"][0]["resources"].append({"source": "ghost", "use": "primary"})),
            "independent assessment": tweak(base, lambda p: p["modules"][1]["assessments"][0].update(independent=False)),
            "measurable completion": tweak(base, lambda p: p["modules"][1].update(completion_criteria=[])),
            "no diagnostic assessment": tweak(base, lambda p: p["modules"][0]["assessments"][0].update(purpose="mastery")),
            "less than its exercises": tweak(base, lambda p: p["modules"][1].update(est_hours=1)),
            "review checkpoint": tweak(base, lambda p: p.update(checkpoints=[])),
            "unknown module": tweak(base, lambda p: p["checkpoints"][0].update(after_module="nope")),
            "must come before": tweak(base, lambda p: p["personalization"].update(sequence=["b", "a"])),
            "exactly once": tweak(base, lambda p: p["personalization"].update(sequence=["a"])),
            "deprioritized competency": tweak(base, lambda p: p["modules"][1]["competencies"].append("c")),
            "teaches 'b' before": tweak(base, lambda p: p.update(modules=[p["modules"][1], p["modules"][0]])),
        }
        for expect, patch in cases.items():
            c, out, err = self.draft(patch)
            self.assertEqual(c, 1, expect)
            self.assertIn(expect, out, expect)

    def test_uninspected_evidence_blocks(self):
        m = map_patch()
        m["competencies"][1]["sources"] = ["s2"]
        self.ok("curriculum", "competencies-set", "demo", "--file", "-", data=m)
        c, out, _ = self.draft(curriculum_patch())
        self.assertIn("rests only on sources nobody inspected", out)

    def test_effort_must_fit_available_time(self):
        # 14 h of modules at 4 h/week = 3.5 weeks
        self.onboard("tight", deadline="2026-01-12")
        self.approve_plan("tight")
        self.ok("research", "add", "tight", "--file", "-", data=research_patch())
        self.ok("curriculum", "competencies-set", "tight", "--file", "-", data=map_patch())
        self.ok("curriculum", "update", "tight", "--file", "-", data=curriculum_patch())
        c, out, _ = self.r("curriculum", "check", "tight", "--today", "2026-01-05")
        self.assertEqual(c, 1)
        self.assertIn("needs 3.5 weeks but only 1.0 remain", out)
        self.assertEqual(self.r("curriculum", "check", "tight", "--today", "2025-12-01")[0], 0)
        self.fail("curriculum", "submit", "tight", "--today", "2026-01-05", expect="weeks")

    def test_stale_basis_requires_rebase(self):
        self.ok("curriculum", "update", "demo", "--file", "-", data=curriculum_patch())
        m = map_patch()
        m["competencies"][0]["level"] = "expert"
        self.ok("curriculum", "competencies-set", "demo", "--file", "-", data=m)
        self.fail("curriculum", "submit", "demo", "--today", "2026-01-05", expect="stale")
        self.ok("curriculum", "rebase", "demo")
        self.ok("curriculum", "submit", "demo", "--today", "2026-01-05")


class ApprovalTests(Base):
    def setUp(self):
        super().setUp()
        self.onboard()
        self.to_review()

    def approve(self, rev, confirm=True, stmt="approved"):
        a = ["curriculum", "approve", "demo", "--revision", str(rev), "--statement", stmt, "--today", "2026-01-06"]
        return self.r(*a, *(["--confirm"] if confirm else []))

    def test_needs_explicit_confirmation_and_matching_revision(self):
        rev = self.cur()["revision"]
        self.assertIn("--confirm", self.approve(rev, confirm=False)[2])
        self.assertIn("reviewed revision", self.approve(rev - 1)[2])
        self.assertIn("quoting", self.approve(rev, stmt=" ")[2])
        self.assertEqual(self.cur()["status"], "in_review")

    def test_old_approval_cannot_authorize_modified_draft(self):
        rev = self.cur()["revision"]
        self.assertEqual(self.approve(rev)[0], 0)
        changed = tweak(curriculum_patch(), lambda p: p["modules"][1].update(title="Reworded"))
        self.ok("curriculum", "update", "demo", "--file", "-", data=changed)
        cur = self.cur()
        self.assertEqual((cur["status"], cur["revision"]), ("draft", rev + 1))
        self.assertNotIn("approval", cur)
        self.assertIn("draft", self.approve(rev)[2])
        self.assertIn("draft", self.approve(rev + 1)[2])
        self.ok("curriculum", "submit", "demo", "--today", "2026-01-05")
        self.assertIn("reviewed revision", self.approve(rev)[2])  # stale approval of the old revision
        self.assertEqual(self.approve(rev + 1)[0], 0)
        self.assertEqual(self.ok("curriculum", "versions", "demo").count("curriculum/versions/r"), 2)

    def test_edit_while_in_review_reopens_draft(self):
        rev = self.cur()["revision"]
        self.ok("curriculum", "update", "demo", "--file", "-", data={"capstone": {
            "title": "Build it", "description": "end to end", "competencies": ["b"],
            "completion_criteria": ["works"], "est_hours": 2}})
        self.assertEqual(self.cur()["status"], "draft")
        self.assertIn("draft", self.approve(rev)[2])

    def test_tampering_with_an_approved_document_is_detected(self):
        self.assertEqual(self.approve(self.cur()["revision"])[0], 0)
        self.assertEqual(run(self.root, "validate")[0], 0)
        path = self.root / "programs/demo/design/curriculum/draft.yaml"
        path.write_text(path.read_text("utf-8").replace("Module m1", "Module sneaky"), "utf-8")
        c, out, _ = run(self.root, "validate")
        self.assertEqual(c, 1)
        self.assertIn("differs from its approval record", out)

    def test_review_view_shows_everything(self):
        out = self.ok("curriculum", "show", "demo")
        for needle in ("Personalization decisions", "claims experience", "m1", "m2", "Review checkpoints",
                       "Estimated effort: 14 h", "about 3.5 weeks", "independent", "Synthetic source s1"):
            self.assertIn(needle, out)


class ActivationTests(Base):
    def setUp(self):
        super().setUp()
        self.onboard()
        self.to_review()
        self.rev = self.cur()["revision"]

    def approve(self, rev):
        return self.ok("curriculum", "approve", "demo", "--revision", str(rev), "--statement", "yes", "--confirm", "--today", "2026-01-06")

    def activate(self, rev):
        return self.r("curriculum", "activate", "demo", "--revision", str(rev), "--today", "2026-01-07")

    def test_unapproved_cannot_become_active(self):
        c, _, err = self.activate(self.rev)
        self.assertEqual(c, 2)
        self.assertIn("only approved", err)
        prog = miniyaml.loads((self.root / "programs/demo/program.yaml").read_text("utf-8"))
        self.assertEqual(prog["competencies"][0]["id"], "todo-first-competency")
        self.assertNotIn("curriculum", prog)

    def test_activation_preserves_history_and_is_recoverable(self):
        pdir = self.root / "programs/demo"
        lesson = pdir / "lessons" / "001-intro.md"
        lesson.parent.mkdir(exist_ok=True)
        lesson.write_text("---\nschema_version: 1\nprogram: demo\nlesson: 1\ndate: 2026-01-05\ntitle: Intro\noutcome: completed\ncompetencies_covered: []\nnext_focus: []\n---\n\n# Lesson 1\n\n## Summary\nx\n\n## Handoff\ny\n", "utf-8")
        logs_before = (pdir / "logs/assessments.jsonl").read_bytes()
        lesson_before = lesson.read_bytes()
        self.approve(self.rev)
        self.assertEqual(self.activate(self.rev)[0], 0)
        prog = miniyaml.loads((pdir / "program.yaml").read_text("utf-8"))
        self.assertEqual([c["id"] for c in prog["competencies"]], ["a", "b"])
        self.assertEqual(prog["competencies"][1]["prerequisites"], ["a"])
        self.assertEqual(prog["curriculum"]["revision"], self.rev)
        self.assertEqual((pdir / "logs/assessments.jsonl").read_bytes(), logs_before)
        self.assertEqual(lesson.read_bytes(), lesson_before)
        self.assertEqual(prog["spec"]["approval"]["statement"], "yes")  # approved onboarding spec intact
        self.assertTrue((pdir / ("design/curriculum/versions/program-before-r%03d.yaml" % self.rev)).is_file())
        self.assertEqual(run(self.root, "validate", "--strict")[0], 0)
        self.assertEqual(self.ok("curriculum", "status", "demo").splitlines()[0], "demo: stage active")
        # a second approved revision supersedes; the first can be re-activated (recovery)
        self.ok("curriculum", "update", "demo", "--file", "-", data=tweak(curriculum_patch(), lambda p: p["personalization"]["decisions"][2].update(
            disposition="study", evidence=[{"kind": "domain_research", "ref": "f1"}])) | {
            "personalization": {"decisions": [dict(d, disposition="study") if d["competency"] == "c" else d for d in curriculum_patch()["personalization"]["decisions"]],
                                "sequence": ["a", "b", "c"]},
            "modules": curriculum_patch()["modules"] + [module("m3", "c", ["m2"])]})
        self.ok("curriculum", "submit", "demo", "--today", "2026-01-05")
        rev2 = self.cur()["revision"]
        self.approve(rev2)
        self.assertEqual(self.activate(rev2)[0], 0)
        self.assertEqual(len(miniyaml.loads((pdir / "program.yaml").read_text("utf-8"))["competencies"]), 3)
        self.assertEqual(self.activate(self.rev)[0], 0)
        self.assertEqual([c["id"] for c in miniyaml.loads((pdir / "program.yaml").read_text("utf-8"))["competencies"]], ["a", "b"])
        self.assertEqual((pdir / "logs/assessments.jsonl").read_bytes(), logs_before)
        self.assertEqual(run(self.root, "validate", "--strict")[0], 0)

    def test_activation_never_orphans_learner_evidence(self):
        self.approve(self.rev)
        pdir = self.root / "programs/demo"
        run(self.root, "log", "demo", "--lesson", "1", "--competency", "todo-first-competency", "--kind", "quiz", "--score", "0.5")
        before = (pdir / "program.yaml").read_bytes()
        c, _, err = self.activate(self.rev)
        self.assertEqual(c, 2)
        self.assertIn("orphan", err)
        self.assertEqual((pdir / "program.yaml").read_bytes(), before)

    def test_activation_detects_drift_and_tampered_snapshot(self):
        self.approve(self.rev)
        self.activate(self.rev)
        pdir = self.root / "programs/demo"
        p = pdir / "program.yaml"
        p.write_text(p.read_text("utf-8").replace("Can do b", "Can do something else"), "utf-8")
        self.assertIn("drifted", run(self.root, "validate")[1])
        snap = pdir / ("design/curriculum/versions/r%03d.yaml" % self.rev)
        snap.write_text(snap.read_text("utf-8").replace("Module m1", "Module zz"), "utf-8")
        self.assertIn("does not match its approval record", self.activate(self.rev)[2])


class ResumeAndIsolationTests(Base):
    def test_every_stage_resumes_from_files_alone(self):
        self.onboard()
        seen = []

        def stage():
            out = self.ok("curriculum", "status", "demo")  # a brand-new CLI invocation: no chat state
            seen.append(out.splitlines()[0].split("stage ")[1])

        stage()
        self.ok("research", "init", "demo"); stage()
        self.ok("research", "plan-update", "demo", "--file", "-", data=plan_patch()); self.ok("research", "plan-submit", "demo"); stage()
        self.ok("research", "plan-approve", "demo", "--revision", "2", "--statement", "y", "--confirm"); stage()
        self.ok("research", "add", "demo", "--file", "-", data=research_patch()); stage()
        self.ok("research", "add", "demo", "--file", "-", data={"tasks": [{"id": "t2", "status": "blocked", "note": "no browsing"}]})
        self.ok("curriculum", "competencies-set", "demo", "--file", "-", data=map_patch()); stage()
        self.ok("curriculum", "update", "demo", "--file", "-", data=curriculum_patch()); stage()
        self.ok("curriculum", "submit", "demo", "--today", "2026-01-05"); stage()
        self.ok("curriculum", "approve", "demo", "--revision", "2", "--statement", "y", "--confirm"); stage()
        self.ok("curriculum", "activate", "demo", "--revision", "2"); stage()
        self.assertEqual(seen[0], "research-planning")
        self.assertEqual(seen[2], "research-plan-review")
        self.assertEqual(seen[3], "source-research")
        self.assertIn("personalization", seen)
        self.assertEqual(seen[-3:], ["curriculum-review", "approved-not-active", "active"])

    def test_briefs_are_bounded_and_exclude_other_programs_and_archive(self):
        self.onboard()
        self.to_review()
        (self.root / "archive").mkdir()
        (self.root / "archive" / "old-chat.md").write_text("SECRET-TRANSCRIPT", "utf-8")
        for args in (("research", "brief", "demo"), ("curriculum", "brief", "demo")):
            out = self.ok(*args)
            self.assertNotIn("SECRET-TRANSCRIPT", out)
            self.assertLess(len(out.splitlines()), 120)
        self.assertIn("evidence inspected", self.ok("curriculum", "brief", "demo"))
        self.assertIn("Check: 0 error(s)", self.ok("curriculum", "brief", "demo"))

    def test_programs_are_isolated(self):
        self.onboard("one")
        self.onboard("two")
        self.approve_plan("one")
        before_two = self.design_bytes("two")
        self.ok("research", "add", "one", "--file", "-", data=research_patch())
        self.ok("curriculum", "competencies-set", "one", "--file", "-", data=map_patch())
        self.assertEqual(before_two, self.design_bytes("two"))
        self.fail("research", "add", "two", "--file", "-", data=research_patch(), expect="not approved")
        self.approve_plan("two")
        out = self.ok("research", "brief", "two")
        self.assertNotIn("Synthetic source s1", out)
        self.assertEqual(design.stage(self.root, "two")[0], "source-research")
        self.assertEqual(run(self.root, "validate")[0], 0)
        # a sibling program's registry cannot satisfy this program's references
        self.fail("curriculum", "competencies-set", "two", "--file", "-", data=map_patch(), expect="nonexistent source")


class EndToEndTests(Base):
    def test_full_synthetic_workflow(self):
        self.onboard()
        self.to_review()
        self.ok("curriculum", "approve", "demo", "--revision", "2", "--statement", "looks right, approve", "--confirm", "--today", "2026-01-06")
        self.ok("curriculum", "activate", "demo", "--revision", "2")
        self.assertEqual(run(self.root, "validate", "--strict")[0], 0)
        self.assertEqual(run(self.root, "context", "demo")[0], 0)  # the normal lesson tooling still works
        out = self.ok("curriculum", "versions", "demo")
        self.assertIn("research/versions/plan-r002.yaml", out)
        self.assertIn("curriculum/versions/r002.yaml", out)


class RepoContractTests(unittest.TestCase):
    def test_entry_points_and_protocol_exist(self):
        R = helpers.REPO
        for rel in ("engine/protocol/07-research-and-curriculum.md", ".claude/commands/research.md",
                    ".claude/commands/curriculum.md", "adapters/codex/prompts/research.md",
                    "adapters/codex/prompts/curriculum.md", "scripts/learning_os/design.py"):
            self.assertTrue((R / rel).is_file(), rel)
        self.assertIn("07-research-and-curriculum", (R / "AGENTS.md").read_text("utf-8"))
        self.assertIn("Single writer", (R / "engine/protocol/07-research-and-curriculum.md").read_text("utf-8"))

    def test_no_real_program_and_no_network_in_engine(self):
        R = helpers.REPO
        self.assertEqual([p.name for p in (R / "programs").iterdir() if p.name not in (".gitkeep", "README.md")], [])
        self.assertEqual([p.name for p in (R / "onboarding").iterdir() if p.name not in (".gitkeep", "README.md")], [])
        text = (R / "scripts/learning_os/design.py").read_text("utf-8")
        for bad in ("urllib", "requests", "socket", "subprocess"):
            self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()
