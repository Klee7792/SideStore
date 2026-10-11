"""QA-owned extractor of localizable string keys straight from the Objective/Swift sources.

Written from scratch for this audit.  Its job is to answer one question that the
implementer's own tooling cannot answer for us: **does every key we shipped actually
appear in the code, verbatim?**  A key that is off by one character silently falls back
to English on device - no crash, no log, just an untranslated screen.

Approach: a single-pass scanner that understands Swift string literals (single-line and
multi-line triple-quoted form, escapes, and backslash-paren interpolation), treats line
and block comments as non-code, and records each literal together with file/line.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

IN_SCOPE_DIRS = ("AltStore", "SideStore", "Shared")
OUT_OF_SCOPE = ("Dependencies", "AltWidget", "SideBackup", ".git", "build")

_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
    "\\": "\\",
    '"': '"',
    "'": "'",
}


@dataclass(frozen=True)
class Literal:
    value: str          # interpolation placeholders replaced by "\u0000<n>\u0000"
    file: str
    line: int
    interpolated: bool


@dataclass(frozen=True)
class Call:
    key: str
    file: str
    line: int
    kind: str           # 'NSLocalizedString' | 'Text' | 'Button' | ...


def _iter_swift_files(roots: Tuple[str, ...]) -> List[str]:
    out: List[str] = []
    for root in roots:
        base = os.path.join(REPO, root)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in OUT_OF_SCOPE]
            for fn in filenames:
                if fn.endswith(".swift"):
                    out.append(os.path.join(dirpath, fn))
    return sorted(out)


class Scanner:
    """Walks a Swift file producing every string literal, comments skipped."""

    def __init__(self, src: str, path: str):
        self.s = src
        self.n = len(src)
        self.i = 0
        self.line = 1
        self.path = path

    def _adv(self, k: int = 1) -> None:
        for _ in range(k):
            if self.i >= self.n:
                return
            if self.s[self.i] == "\n":
                self.line += 1
            self.i += 1

    def _read_multiline(self) -> str:
        """Read a triple-quoted Swift literal applying Swift's indentation rules.

        Swift removes the indentation of the closing delimiter from every line, turns
        whitespace-only lines into empty lines, and drops the newline that precedes the
        closing delimiter.  Getting this wrong would make genuine keys look fabricated,
        so it is implemented here rather than approximated.
        """
        lines: List[str] = []          # escaped-per-line content, indentation still present
        cur: List[str] = []
        interp = 0
        while self.i < self.n:
            c = self.s[self.i]
            if c == "\\":
                self._adv()
                if self.i >= self.n:
                    break
                nxt = self.s[self.i]
                if nxt == "(":
                    cur.append(f"\x00{interp}\x00")
                    interp += 1
                    depth = 1
                    self._adv()
                    while self.i < self.n and depth:
                        ch = self.s[self.i]
                        if ch == "(":
                            depth += 1
                        elif ch == ")":
                            depth -= 1
                            if depth == 0:
                                self._adv()
                                break
                        elif ch == '"':
                            if self.s[self.i: self.i + 3] == '"""':
                                self._adv(3)
                                cur.append(self._read_multiline())
                                continue
                            self._adv()
                            cur.append(self._read_string(False))
                            continue
                        self._adv()
                    continue
                if nxt == "\n":
                    # line continuation inside a multiline literal
                    self._adv()
                    continue
                cur.append(_ESCAPES.get(nxt, "\\" if nxt == "\\" else "\\" + nxt))
                self._adv()
                continue
            if c == '"' and self.s[self.i: self.i + 3] == '"""':
                # closing delimiter: count its indentation from the current line
                line_start = self.s.rfind("\n", 0, self.i) + 1
                closing_line = self.s[line_start: self.i]
                indent = len(closing_line) - len(closing_line.lstrip(" \t"))
                self._adv(3)
                break
            if c == "\n":
                lines.append("".join(cur))
                cur = []
                self._adv()
                continue
            cur.append(c)
            self._adv()
        else:
            indent = 0
        # whatever followed the closing delimiter on that line, plus the last partial line
        # Swift drops the newline that follows the opening delimiter and the newline
        # that precedes the closing delimiter.
        if lines and lines[0] == "":
            lines = lines[1:]
        tail = "".join(cur)
        if tail.strip(" \t") != "":
            lines.append(tail)

        # The newline before the closing delimiter is dropped -> "" join, not "\n".
        out_lines: List[str] = []
        for ln in lines:
            leading = len(ln) - len(ln.lstrip(" \t"))
            strip = min(leading, indent)
            out_lines.append(ln[strip:] if indent else ln)
        # join, but honour explicit \n escapes embedded in the text itself
        return "\n".join(out_lines)

    def _read_string(self, multiline: bool) -> str:
        """self.i is just past the opening quote(s)."""
        buf: List[str] = []
        interp = 0
        start_line = self.line
        while self.i < self.n:
            c = self.s[self.i]
            if c == "\\":
                self._adv()
                if self.i >= self.n:
                    break
                nxt = self.s[self.i]
                if nxt == "(":
                    # interpolation: skip balanced parens, remember it happened
                    buf.append(f"\x00{interp}\x00")
                    interp += 1
                    depth = 1
                    self._adv()
                    while self.i < self.n and depth:
                        if self.s[self.i] == "(":
                            depth += 1
                        elif self.s[self.i] == ")":
                            depth -= 1
                            if depth == 0:
                                self._adv()
                                break
                        elif self.s[self.i] == '"':
                            self._read_string(False)
                            continue
                        self._adv()
                    continue
                if nxt == "\n" and multiline:
                    self._adv()
                    continue
                buf.append(_ESCAPES.get(nxt, "\\" + nxt))
                self._adv()
                continue
            if c == '"':
                self._adv()
                if multiline:
                    # look for the closing triple
                    if self.s[self.i: self.i + 2] == '""':
                        self._adv(2)
                        return "".join(buf)
                    buf.append("\n")
                    continue
                return "".join(buf)
            if c == "\n" and not multiline:
                break  # unterminated single-line literal -> abandon
            buf.append(c)
            self._adv()
        return "".join(buf)

    def scan(self) -> List[Literal]:
        lits: List[Literal] = []
        # remember the last identifier before each literal so we can classify it
        last_ident = ""
        ident_buf: List[str] = []
        while self.i < self.n:
            c = self.s[self.i]
            if c == "/" and self.s[self.i + 1: self.i + 2] == "/":
                while self.i < self.n and self.s[self.i] != "\n":
                    self._adv()
                continue
            if c == "/" and self.s[self.i + 1: self.i + 2] == "*":
                self._adv(2)
                while self.i < self.n and self.s[self.i: self.i + 2] != "*/":
                    self._adv()
                self._adv(2)
                continue
            if c == '"':
                start = self.i
                start_line = self.line
                if self.s[self.i: self.i + 3] == '"""':
                    self._adv(3)
                    val = self._read_multiline()
                else:
                    self._adv()
                    val = self._read_string(False)
                lits.append(
                    Literal(
                        value=val,
                        file=os.path.relpath(self.path, REPO).replace("\\", "/"),
                        line=start_line,
                        interpolated="\x00" in val,
                    )
                )
                # caller trigger name = text immediately preceding the literal
                before = self.s[max(0, start - 40): start].rstrip()
                # (not stored; the audit matches by looking at the raw prefix instead)
                continue
            self._adv()
        return lits


def _callee_before(src: str, start: int) -> str:
    """Identifier that opens the call containing offset `start`."""
    j = start - 1
    depth = 0
    while j >= 0:
        ch = src[j]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                k = j - 1
                ident = []
                while k >= 0 and (src[k].isalnum() or src[k] in "_."):
                    ident.append(src[k])
                    k -= 1
                return "".join(reversed(ident))
            depth -= 1
        j -= 1
    return ""


def swift_literals() -> List[Literal]:
    all_lits: List[Literal] = []
    for path in _iter_swift_files(IN_SCOPE_DIRS):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        all_lits.extend(Scanner(src, path).scan())
    return all_lits


def nslocalizedstring_keys() -> List[Call]:
    """Keys passed to NSLocalizedString(<literal>, ...) - independent of any tooling."""
    calls: List[Call] = []
    for path in _iter_swift_files(IN_SCOPE_DIRS):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        sc = Scanner(src, path)
        # rescan manually so we can grab the literal offsets
        i = 0
        while i < len(src):
            m = src.find("NSLocalizedString(", i)
            if m == -1:
                break
            i = m + len("NSLocalizedString(")
            # expect a string literal right after '('
            if src[i: i + 1] != '"':
                continue
            sc2 = Scanner(src[i:], path)
            sc2.i = 0
            sc2.line = 1
            val = sc2._read_string(False)
            end = sc2.i
            line_no = src.count("\n", 0, m) + 1
            calls.append(
                Call(
                    key=val,
                    file=os.path.relpath(path, REPO).replace("\\", "/"),
                    line=line_no,
                    kind="NSLocalizedString",
                )
            )
            i = i + end
    return calls


def source_string_set() -> Dict[str, List[str]]:
    """value -> [file:line, ...] for every literal found in in-scope Swift sources."""
    out: Dict[str, List[str]] = {}
    for lit in swift_literals():
        loc = f"{lit.file}:{lit.line}"
        out.setdefault(lit.value, []).append(loc)
    return out


def all_source_text() -> str:
    joined: List[str] = []
    for path in _iter_swift_files(IN_SCOPE_DIRS):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            joined.append(fh.read())
    return "\n".join(joined)
