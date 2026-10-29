import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

FIXTURE_ROOT = REPO / "tests" / "fixtures" / "root"
PID = "sample-program"


class TmpRootCase(unittest.TestCase):
    """Each test gets a private copy of the fixture root to mutate."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "root"
        shutil.copytree(FIXTURE_ROOT, self.root)
        self.pdir = self.root / "programs" / PID

    def edit(self, rel, old, new):
        p = self.pdir / rel
        text = p.read_text("utf-8")
        assert old in text, f"{old!r} not in {rel}"
        p.write_text(text.replace(old, new, 1), "utf-8")
