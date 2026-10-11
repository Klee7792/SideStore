"""QA-owned, independent lexer/recursive-descent parser for old-style (NeXTSTEP / OpenStep)
`.strings` files.

Deliberately NOT derived from `scripts/i18n/validate_strings.py` (the implementer's own
self-checker).  The grammar implemented here is the one `plutil` / `NSStringsFileFormat`
accepts:

    file    := ( pair )* EOF
    pair    := STRING '=' STRING ';'
    STRING  := '"' ( escape | <any char except '"' and raw LF> )* '"'
    escape  := '\\' ( '"' '\\' 'n' 't' 'r' 'a' 'b' 'f' 'v' '0' '\'' 'U' hex{4} 'u' hex{4} octal{1,3} )
    comment := '/*' ( comment | <any> )* '*/'      <- nestable
             | '//' <any>* (LF|EOF)

Every token carries (line, col) so the QA report can point at exact positions.
Surfaced-as-error conditions that matter on iOS:
  * unterminated string / comment
  * raw newline inside a quoted string
  * unescaped double quote inside a quoted string (impossible here - would terminate the
    string - so it is reported as "string ends then unexpected token", still an error)
  * missing ';' terminator
  * duplicate keys (plutil either errors or silently keeps one -> fatal for us)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# --------------------------------------------------------------------------- tokens

TK_STRING = "STRING"
TK_EQUALS = "="
TK_SEMI = ";"
TK_BANG = "!"          # tolerated: some .strings dialects use  key = value; with no quotes
TK_EOF = "EOF"
TK_IDENT = "IDENT"     # bare (unquoted) token


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int
    col: int
    raw: str = ""


class StringsSyntaxError(Exception):
    def __init__(self, msg: str, line: int, col: int):
        super().__init__(f"{msg} at line {line}, col {col}")
        self.msg = msg
        self.line = line
        self.col = col


_OCTAL = set("01234567")
_HEX = set("0123456789abcdefABCDEF")

_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "0": "\0",
    "'": "'",
    "\n": "",
}


class _Lexer:
    """Character-by-character scanner.  No regex substitution anywhere."""

    def __init__(self, text: str, allow_bare: bool = False):
        self.src = text
        self.i = 0
        self.line = 1
        self.col = 1
        self.n = len(text)
        self.allow_bare = allow_bare

    # -- position helpers ---------------------------------------------------
    def _advance(self, count: int = 1) -> None:
        for _ in range(count):
            if self.i >= self.n:
                return
            if self.src[self.i] == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
            self.i += 1

    def _peek(self, offset: int = 0) -> str:
        j = self.i + offset
        return self.src[j] if j < self.n else ""

    def _skip_insignificant(self) -> None:
        while self.i < self.n:
            c = self.src[self.i]
            if c in " \t\r\n\f\v":
                self._advance()
            elif c == "/" and self._peek(1) == "/":
                self._line_comment()
            elif c == "/" and self._peek(1) == "*":
                self._block_comment(depth_line=0)
            else:
                return

    # -- comments -----------------------------------------------------------
    def _line_comment(self) -> None:
        start_line, start_col = self.line, self.col
        self._advance(2)
        while self.i < self.n and self.src[self.i] not in "\r\n":
            self._advance()
        if self.i >= self.n:
            return  # fine: EOF terminates a // comment

    def _block_comment(self, depth_line: int) -> None:
        """Recursive; C-style block comments nest, and so do those in NSStringsFileFormat."""
        start_line, start_col = self.line, self.col
        self._advance(2)  # consume /*
        while self.i < self.n:
            c = self.src[self.i]
            if c == "*" and self._peek(1) == "/":
                self._advance(2)
                return
            if c == "/" and self._peek(1) == "*":
                self._block_comment(depth_line + 1)  # nested
                continue
            self._advance()
        raise StringsSyntaxError("unterminated block comment", start_line, start_col)

    # -- strings ------------------------------------------------------------
    def _quoted_string(self) -> Token:
        start_line, start_col = self.line, self.col
        self._advance()  # opening quote
        out: List[str] = []
        raw: List[str] = ['"']
        while True:
            c = self._peek()
            if c == "":
                raise StringsSyntaxError(
                    "unterminated string literal (reached EOF)", start_line, start_col
                )
            if c == '"':
                self._advance()
                raw.append('"')
                break
            if c == "\n":
                # A raw LF inside quotes is a hard error for shipping .strings files.
                raise StringsSyntaxError(
                    "raw newline inside quoted string (LF must be escaped as \\n)",
                    self.line,
                    self.col,
                )
            if c == "\\":
                line, col = self.line, self.col
                self._advance()
                e = self._peek()
                if e == "":
                    raise StringsSyntaxError("trailing backslash in string", line, col)
                ch, consumed = self._decode_escape(line, col)
                out.append(ch)
                raw.append(consumed)
                continue
            out.append(c)
            raw.append(c)
            self._advance()
        return Token(TK_STRING, "".join(out), start_line, start_col, "".join(raw))

    def _decode_escape(self, line: int, col: int) -> Tuple[str, str]:
        # self.i points at the character right after the backslash
        e = self.src[self.i]
        if e in _SIMPLE_ESCAPES:
            self._advance()
            return _SIMPLE_ESCAPES[e], "\\" + e
        if e in ("U", "u"):
            digits = self.src[self.i + 1: self.i + 5]
            if len(digits) != 4 or any(d not in _HEX for d in digits):
                raise StringsSyntaxError(
                    rf"invalid \U escape (expected 4 hex digits, got {digits!r})", line, col
                )
            self._advance(5)
            return chr(int(digits, 16)), "\\" + e + digits
        if e in _OCTAL:
            digits = ""
            while len(digits) < 3 and (self._peek(len(digits)) in _OCTAL):
                digits += self._peek(len(digits))
            self._advance(len(digits))
            return chr(int(digits, 8) & 0xFF), "\\" + digits
        raise StringsSyntaxError(rf"unrecognized escape sequence \{e}", line, col)

    def _bare_token(self) -> Token:
        start_line, start_col = self.line, self.col
        buf: List[str] = []
        while self.i < self.n and self.src[self.i] not in ' \t\r\n=";/':
            buf.append(self.src[self.i])
            self._advance()
        return Token(TK_IDENT, "".join(buf), start_line, start_col)

    # -- public -------------------------------------------------------------
    def tokenize(self) -> List[Token]:
        toks: List[Token] = []
        while True:
            self._skip_insignificant()
            if self.i >= self.n:
                toks.append(Token(TK_EOF, "", self.line, self.col))
                return toks
            c = self.src[self.i]
            if c == '"':
                toks.append(self._quoted_string())
            elif c == "=":
                line, col = self.line, self.col
                self._advance()
                toks.append(Token(TK_EQUALS, "=", line, col))
            elif c == ";":
                line, col = self.line, self.col
                self._advance()
                toks.append(Token(TK_SEMI, ";", line, col))
            else:
                if not self.allow_bare:
                    raise StringsSyntaxError(
                        f"unexpected character {c!r} outside of a quoted string "
                        "(only \"strings\", '=' and ';' are legal here)",
                        self.line,
                        self.col,
                    )
                toks.append(self._bare_token())


# --------------------------------------------------------------------------- parser


@dataclass
class Entry:
    key: str
    value: str
    line: int
    col: int
    key_raw: str = ""
    value_raw: str = ""


@dataclass
class ParseResult:
    entries: List[Entry] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    duplicate_keys: List[Tuple[str, int, int]] = field(default_factory=list)
    # key -> [line numbers where it appears]
    key_lines: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.duplicate_keys


class StringsParser:
    """Recursive-descent parser over the token stream produced by _Lexer."""

    def __init__(self, text: str, allow_bare: bool = False):
        self.text = text
        self.allow_bare = allow_bare
        self.tokens: List[Token] = []
        self.pos = 0

    # -- helpers ------------------------------------------------------------
    def _cur(self) -> Token:
        return self.tokens[self.pos]

    def _expect(self, kind: str) -> Token:
        tok = self._cur()
        if tok.kind != kind:
            got = "EOF" if tok.kind == TK_EOF else f"{tok.kind} {tok.raw or tok.value!r}"
            raise StringsSyntaxError(
                f"expected {kind}, found {got}", tok.line, tok.col
            )
        self.pos += 1
        return tok

    # -- grammar ------------------------------------------------------------
    def parse(self) -> ParseResult:
        result = ParseResult()
        try:
            self.tokens = _Lexer(self.text, allow_bare=self.allow_bare).tokenize()
        except StringsSyntaxError as exc:
            result.errors.append(str(exc))
            return result

        while self._cur().kind != TK_EOF:
            start = self._cur()
            try:
                key_tok = self._expect(TK_STRING)
                self._expect(TK_EQUALS)
                val_tok = self._expect(TK_STRING)
                self._expect(TK_SEMI)
            except StringsSyntaxError as exc:
                result.errors.append(
                    f"{exc} (statement starting at line {start.line}, col {start.col})"
                )
                # recover: skip forward to the next ';' at top level, or EOF
                while self._cur().kind not in (TK_SEMI, TK_EOF):
                    self.pos += 1
                if self._cur().kind == TK_SEMI:
                    self.pos += 1
                continue

            entry = Entry(
                key=key_tok.value,
                value=val_tok.value,
                line=key_tok.line,
                col=key_tok.col,
                key_raw=key_tok.raw,
                value_raw=val_tok.raw,
            )
            result.entries.append(entry)
            result.key_lines.setdefault(entry.key, []).append(entry.line)

        result.duplicate_keys = [
            (key, lines[0], lines[1])
            for key, lines in result.key_lines.items()
            if len(lines) > 1
        ]
        return result


def parse_file(path: str, allow_bare: bool = False) -> Tuple[ParseResult, bytes]:
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8-sig")  # tolerate BOM for parsing; encoding is checked separately
    return StringsParser(text, allow_bare=allow_bare).parse(), raw
