"""Strict YAML-subset reader/writer using only the standard library.

Learning OS keeps YAML files simple on purpose so no third-party parser is
needed. Supported:

  * block mappings and block sequences (space indentation only)
  * scalars: null, true/false, integers, floats, plain / "double" / 'single' strings
  * flow sequences of scalars: [a, b, "c d"] and the empty forms [] and {}
  * literal blocks (| and |-) for multi-line text
  * full-line and trailing "# comments"

Everything else (anchors, tags, merge keys, nested flow collections, folded
blocks, multi-document streams, tab indentation) is rejected with a YamlError
rather than silently misread. Dates stay strings; schemas validate their format.
"""

from __future__ import annotations

import json
import re
from typing import Any

__all__ = ["YamlError", "loads", "dumps", "split_frontmatter"]


class YamlError(ValueError):
    pass


_INT_RE = re.compile(r"^-?(0|[1-9][0-9]*)$")
_FLOAT_RE = re.compile(r"^-?[0-9]+(\.[0-9]+([eE][-+]?[0-9]+)?|[eE][-+]?[0-9]+)$")
_KEY_RE = re.compile(
    r"""^(?P<key>"(?:[^"\\]|\\.)*"|'[^']*'|[^\s:#'"\[\]{}\-?&*!|>%@`,][^:#]*?)"""
    r"""\s*:(?:\s+(?P<rest>.*))?$"""
)
_PLAIN_DUMP_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./ +()=-]*$")
_PLAIN_KEY_DUMP_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
_UNSUPPORTED_START = "&*!%@`|>"


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def _strip_comment(s: str) -> str:
    quote = None
    i = 0
    while i < len(s):
        ch = s[i]
        if quote:
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'" and (i == 0 or s[i - 1] in " [,"):
            quote = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
        i += 1
    return s.rstrip()


def _flow_items(inner: str) -> list[str]:
    items: list[str] = []
    cur = ""
    quote = None
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            cur += ch
            if quote == '"' and ch == "\\" and i + 1 < len(inner):
                cur += inner[i + 1]
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'" and cur.strip() == "":
            quote = ch
            cur += ch
        elif ch in "[{":
            raise YamlError("nested flow collections are not supported")
        elif ch == ",":
            items.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    if quote:
        raise YamlError("unterminated quoted string in flow sequence")
    if cur.strip():
        items.append(cur)
    return [x.strip() for x in items]


def _scalar(s: str) -> Any:
    if s in ("", "~", "null"):
        return None
    c = s[0]
    if c == '"':
        if len(s) < 2 or s[-1] != '"':
            raise YamlError(f"bad double-quoted string: {s}")
        try:
            return json.loads(s)
        except json.JSONDecodeError as exc:
            raise YamlError(f"bad double-quoted string: {s} ({exc.msg})") from None
    if c == "'":
        if len(s) < 2 or s[-1] != "'":
            raise YamlError(f"bad single-quoted string: {s}")
        inner = s[1:-1]
        if re.search(r"(?<!')'(?!')", inner.replace("''", "")):
            raise YamlError(f"bad single-quoted string: {s}")
        return inner.replace("''", "'")
    if c == "[":
        if s[-1] != "]":
            raise YamlError(f"unterminated flow sequence: {s}")
        out = []
        for item in _flow_items(s[1:-1]):
            if item == "":
                raise YamlError(f"empty item in flow sequence: {s}")
            out.append(_scalar(item))
        return out
    if c == "{":
        if s.replace(" ", "") == "{}":
            return {}
        raise YamlError("flow mappings other than {} are not supported")
    if c in _UNSUPPORTED_START:
        raise YamlError(f"unsupported YAML construct: {s}")
    if s == "true":
        return True
    if s == "false":
        return False
    if _INT_RE.match(s):
        return int(s)
    if _FLOAT_RE.match(s):
        return float(s)
    return s


def _unquote_key(k: str) -> str:
    if k[0] in "\"'":
        return _scalar(k)
    return k.strip()


class _Parser:
    def __init__(self, text: str):
        self.lines = text.replace("\r\n", "\n").split("\n")

    def err(self, i: int, msg: str) -> YamlError:
        return YamlError(f"line {i + 1}: {msg}")

    def sig(self, i: int) -> int:
        while i < len(self.lines):
            st = self.lines[i].strip()
            if st and not st.startswith("#"):
                return i
            i += 1
        return len(self.lines)

    def ind(self, i: int) -> int:
        line = self.lines[i]
        n = len(line) - len(line.lstrip(" "))
        if line[n:n + 1] == "\t":
            raise self.err(i, "tab indentation is not allowed")
        return n

    def is_seq(self, i: int, ind: int) -> bool:
        c = self.lines[i][ind:]
        return c == "-" or c.startswith("- ")

    def parse(self) -> Any:
        i = self.sig(0)
        if i >= len(self.lines):
            return None
        if self.ind(i) != 0:
            raise self.err(i, "document must start at column 0")
        value, i = self.block(i, 0)
        j = self.sig(i)
        if j < len(self.lines):
            raise self.err(j, "unexpected content")
        return value

    def block(self, i: int, ind: int):
        return self.seq(i, ind) if self.is_seq(i, ind) else self.map(i, ind)

    def map(self, i: int, ind: int):
        d: dict[str, Any] = {}
        while True:
            i = self.sig(i)
            if i >= len(self.lines) or self.ind(i) < ind:
                return d, i
            if self.ind(i) > ind:
                raise self.err(i, "unexpected indentation")
            if self.is_seq(i, ind):
                return d, i
            m = _KEY_RE.match(self.lines[i][ind:].rstrip())
            if not m:
                raise self.err(i, 'expected "key: value"')
            try:
                key = _unquote_key(m.group("key"))
                rest = _strip_comment(m.group("rest") or "").strip()
                if key in d:
                    raise self.err(i, f"duplicate key {key!r}")
                if rest in ("|", "|-"):
                    val, i = self.literal(i + 1, ind, rest == "|-")
                elif rest == "":
                    j = self.sig(i + 1)
                    if j < len(self.lines) and (
                        self.ind(j) > ind or (self.ind(j) == ind and self.is_seq(j, ind))
                    ):
                        val, i = self.block(j, self.ind(j))
                    else:
                        val, i = None, i + 1
                else:
                    val, i = _scalar(rest), i + 1
            except YamlError as exc:
                if str(exc).startswith("line "):
                    raise
                raise self.err(i, str(exc)) from None
            d[key] = val

    def seq(self, i: int, ind: int):
        out: list[Any] = []
        while True:
            i = self.sig(i)
            if i >= len(self.lines) or self.ind(i) < ind:
                return out, i
            if self.ind(i) > ind:
                raise self.err(i, "unexpected indentation")
            if not self.is_seq(i, ind):
                return out, i
            body = self.lines[i][ind + 1:]
            stripped = body.lstrip(" ")
            k = ind + 1 + (len(body) - len(stripped))
            clean = _strip_comment(stripped)
            try:
                if clean == "":
                    j = self.sig(i + 1)
                    if j < len(self.lines) and self.ind(j) > ind:
                        val, i = self.block(j, self.ind(j))
                    else:
                        val, i = None, i + 1
                elif _KEY_RE.match(clean):
                    self.lines[i] = " " * k + stripped
                    val, i = self.map(i, k)
                else:
                    val, i = _scalar(clean), i + 1
            except YamlError as exc:
                if str(exc).startswith("line "):
                    raise
                raise self.err(i, str(exc)) from None
            out.append(val)

    def literal(self, i: int, ind: int, strip: bool):
        buf: list[str] = []
        block_ind = None
        while i < len(self.lines):
            line = self.lines[i]
            if line.strip() == "":
                buf.append("")
                i += 1
                continue
            n = len(line) - len(line.lstrip(" "))
            if n <= ind:
                break
            if block_ind is None:
                block_ind = n
            if n < block_ind:
                raise self.err(i, "inconsistent literal block indentation")
            buf.append(line[block_ind:])
            i += 1
        while buf and buf[-1] == "":
            buf.pop()
        text = "\n".join(buf)
        if strip or not buf:
            return text, i
        return text + "\n", i


def loads(text: str) -> Any:
    return _Parser(text).parse()


def split_frontmatter(text: str) -> tuple[Any, str]:
    """Split a Markdown file into (parsed YAML frontmatter, body)."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise YamlError("missing YAML frontmatter (file must start with '---')")
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return loads("\n".join(lines[1:idx])), "\n".join(lines[idx + 1:])
    raise YamlError("unterminated YAML frontmatter (no closing '---')")


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------

def _dump_scalar(v: Any) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise YamlError("cannot dump NaN/inf")
        return repr(v)
    if isinstance(v, str):
        if v and v == v.strip() and _PLAIN_DUMP_RE.match(v):
            try:
                if _scalar(v) == v:
                    return v
            except YamlError:
                pass
        return json.dumps(v, ensure_ascii=False)
    raise YamlError(f"cannot dump value of type {type(v).__name__}")


def _dump_inline(v: Any) -> str:
    if isinstance(v, dict) and not v:
        return "{}"
    if isinstance(v, list) and not v:
        return "[]"
    return _dump_scalar(v)


def _dump_key(k: Any) -> str:
    if not isinstance(k, str):
        raise YamlError("mapping keys must be strings")
    if _PLAIN_KEY_DUMP_RE.match(k) and k not in ("null", "true", "false", "~"):
        return k
    return json.dumps(k, ensure_ascii=False)


def _dump(v: Any, ind: int, out: list[str]) -> None:
    pad = " " * ind
    if isinstance(v, dict):
        for k, val in v.items():
            key = _dump_key(k)
            if isinstance(val, (dict, list)) and val:
                out.append(f"{pad}{key}:")
                _dump(val, ind + 2, out)
            else:
                out.append(f"{pad}{key}: {_dump_inline(val)}")
    else:
        for item in v:
            if isinstance(item, dict) and item:
                sub: list[str] = []
                _dump(item, ind + 2, sub)
                sub[0] = f"{pad}- {sub[0][ind + 2:]}"
                out.extend(sub)
            elif isinstance(item, list) and item:
                raise YamlError("nested non-empty lists are not supported")
            else:
                out.append(f"{pad}- {_dump_inline(item)}")


def dumps(value: Any) -> str:
    if not isinstance(value, (dict, list)) or not value:
        raise YamlError("top-level value must be a non-empty mapping or list")
    out: list[str] = []
    _dump(value, 0, out)
    return "\n".join(out) + "\n"
