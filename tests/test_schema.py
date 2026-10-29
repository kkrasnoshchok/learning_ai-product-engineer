import unittest

import helpers  # noqa: F401
from learning_os import miniyaml, model, schema as s


class SchemaTests(unittest.TestCase):
    def errs(self, inst, sch):
        return s.validate(inst, sch)

    def test_types_distinguish_bool_and_int(self):
        self.assertTrue(self.errs(True, {"type": "integer"}))
        self.assertTrue(self.errs(True, {"type": "number"}))
        self.assertFalse(self.errs(3, {"type": "number"}))
        self.assertFalse(self.errs(None, {"type": ["string", "null"]}))

    def test_object_rules(self):
        sch = {"type": "object", "required": ["a"], "additionalProperties": False,
               "properties": {"a": {"type": "integer", "minimum": 1}}}
        self.assertEqual(self.errs({"a": 1}, sch), [])
        self.assertTrue(self.errs({}, sch))
        self.assertTrue(self.errs({"a": 0}, sch))
        self.assertTrue(self.errs({"a": 1, "b": 2}, sch))

    def test_array_enum_pattern_format(self):
        self.assertTrue(self.errs([1, 1], {"type": "array", "uniqueItems": True}))
        self.assertTrue(self.errs([], {"type": "array", "minItems": 1}))
        self.assertTrue(self.errs("x", {"enum": ["a"]}))
        self.assertTrue(self.errs("Bad", {"pattern": "^[a-z]+$"}))
        self.assertTrue(self.errs("2026-02-30", {"format": "date"}))
        self.assertFalse(self.errs("2026-02-28", {"format": "date"}))
        self.assertTrue(self.errs("2026-01-01T00:00:00", {"format": "date-time"}))
        self.assertFalse(self.errs("2026-01-01T00:00:00Z", {"format": "date-time"}))

    def test_const_is_type_strict(self):
        self.assertTrue(self.errs(True, {"const": 1}))
        self.assertFalse(self.errs(1, {"const": 1}))

    def test_ref_and_property_names(self):
        sch = {"$defs": {"id": {"pattern": "^[a-z]+$"}}, "type": "object",
               "propertyNames": {"$ref": "#/$defs/id"}, "additionalProperties": {"type": "integer"}}
        self.assertEqual(self.errs({"ok": 1}, sch), [])
        self.assertTrue(self.errs({"BAD": 1}, sch))
        self.assertTrue(self.errs({"ok": "x"}, sch))

    def test_unknown_keyword_is_an_error(self):
        with self.assertRaises(s.SchemaError):
            self.errs(1, {"typo_keyword": 1})

    def test_every_shipped_schema_loads_and_runs(self):
        for path in sorted((model.ENGINE_DIR / "schemas").glob("*.schema.yaml")):
            with self.subTest(schema=path.name):
                sch = miniyaml.loads(path.read_text("utf-8"))
                self.assertEqual(sch["type"], "object")
                s.validate({}, sch)  # must not raise SchemaError


if __name__ == "__main__":
    unittest.main()
