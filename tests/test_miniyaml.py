import unittest

import helpers  # noqa: F401  (sets sys.path)
from learning_os import miniyaml as y


class ParseTests(unittest.TestCase):
    def test_scalars(self):
        d = y.loads('a: 1\nb: 1.5\nc: true\nd: null\ne: ~\nf: plain text\ng: "q: #x"\nh: \'it\'\'s\'\ni: 2026-01-05\nj: 007\nk:\n')
        self.assertEqual(d, {"a": 1, "b": 1.5, "c": True, "d": None, "e": None, "f": "plain text",
                             "g": "q: #x", "h": "it's", "i": "2026-01-05", "j": "007", "k": None})

    def test_nested_and_lists(self):
        d = y.loads("x:\n  y:\n    - 1\n    - k: v\n      m: [a, \"b, c\", 3]\n  z: []\nw:\n- p\n- q\n")
        self.assertEqual(d, {"x": {"y": [1, {"k": "v", "m": ["a", "b, c", 3]}], "z": []}, "w": ["p", "q"]})

    def test_comments(self):
        d = y.loads("# top\na: 1  # trailing\nb: \"has # inside\"\nc: x#notcomment\n")
        self.assertEqual(d, {"a": 1, "b": "has # inside", "c": "x#notcomment"})

    def test_literal_block(self):
        d = y.loads("t: |\n  line1\n  line2\nu: |-\n  solo\nv: 1\n")
        self.assertEqual(d, {"t": "line1\nline2\n", "u": "solo", "v": 1})

    def test_empty_document(self):
        self.assertIsNone(y.loads("# only a comment\n"))

    def test_rejects_unsupported(self):
        for bad in ["a: &x 1", "a: *x", "a: !!str x", "a: >\n  folded", "a: {b: 1}", "a: [[1]]",
                    "\ta: 1", "a: 1\na: 2", "a: 1\n b: 2", "just text", "a: \"unterminated",
                    "a: [1, ,2]"]:
            with self.subTest(bad=bad):
                with self.assertRaises(y.YamlError):
                    y.loads(bad)

    def test_error_mentions_line(self):
        with self.assertRaises(y.YamlError) as cm:
            y.loads("a: 1\nb: &anchor 2\n")
        self.assertIn("line 2", str(cm.exception))

    def test_frontmatter(self):
        meta, body = y.split_frontmatter("---\nk: v\n---\n# Body\n")
        self.assertEqual((meta, body.strip()), ({"k": "v"}, "# Body"))
        with self.assertRaises(y.YamlError):
            y.split_frontmatter("# no frontmatter")
        with self.assertRaises(y.YamlError):
            y.split_frontmatter("---\nk: v\n")


class RoundTripTests(unittest.TestCase):
    def test_roundtrip(self):
        samples = [
            {"a": 1, "b": 0.25, "c": None, "d": True, "e": "text with spaces", "f": "needs: quoting",
             "g": "true", "h": "123", "i": "", "j": " padded ", "k": "line\nbreak", "l": "ünïcode"},
            {"list": [1, "two", {"k": "v", "n": [1, 2]}, None, {}], "empty": [], "map": {"x": {"y": {"z": 1}}}},
            {"ts": "2026-01-05T10:00:00Z", "d": "2026-01-05", "1e5": "x", "null": 1, "key with space": 2},
            [1, {"a": 2}, "s"],
        ]
        for s in samples:
            with self.subTest(sample=s):
                self.assertEqual(y.loads(y.dumps(s)), s)

    def test_dump_rejects_exotic(self):
        for bad in [{"a": float("nan")}, {"a": object()}, {1: "x"}, {"a": [[1]]}, {}]:
            with self.subTest(bad=bad):
                with self.assertRaises(y.YamlError):
                    y.dumps(bad)


if __name__ == "__main__":
    unittest.main()
