#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SideStore localization helper: extract localizable strings and render .strings files.

This script is intentionally dependency-free (stdlib only) and Windows-friendly.
It exists because the SideStore checkout is developed on machines where Xcode's
``genstrings`` / ``ibtool`` are not available.

Two sub-commands:

    python extract_strings.py extract   # write scripts/i18n/extracted.json
    python extract_strings.py render    # write AltStore/zh-Hans.lproj/Localizable.strings

Design notes
------------
* Swift sources are scanned with a real tokenizer instead of regexes so that
  nested parentheses, multi-line calls and escaped/interpolated string literals
  are handled correctly (``NSLocalizedString("Version %@%@", comment: "...")``
  inside a larger expression must not confuse the extractor).
* Comments are stripped by the tokenizer, so commented-out code can never
  produce entries.
* Only the three App target folders are scanned: ``AltStore``, ``SideStore`` and
  ``Shared``. ``Dependencies`` is deliberately excluded.

All output is UTF-8 without BOM.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
SCRIPT_DIR: Path = Path(__file__).resolve().parent

EXTRACTED_JSON: Path = SCRIPT_DIR / "extracted.json"
TRANSLATIONS_TSV: Path = SCRIPT_DIR / "translations_zh_Hans.tsv"
KEEP_ENGLISH_TXT: Path = SCRIPT_DIR / "keep_english.txt"

ZH_HANS_LPROJ: Path = REPO_ROOT / "AltStore" / "zh-Hans.lproj"
LOCALIZABLE_STRINGS: Path = ZH_HANS_LPROJ / "Localizable.strings"

#: Directories that are compiled into the SideStore app target and are in scope
#: for this localization pass. ``Dependencies`` is intentionally absent.
SCAN_DIRS: tuple[str, ...] = ("AltStore", "SideStore", "Shared")

#: Values that Interface Builder writes as design-time placeholders. They never
#: reach the screen (the owning view replaces them in code) and must never be
#: mistaken for translatable copy.
XIB_PLACEHOLDER_VALUES: frozenset[str] = frozenset(
    {
        "Label",
        "Subtitle",
        "Source Name",
        "App Name",
        "Developer",
        "Delta",
        "SideTeam",
        "YES",
        "https://rileytestut.com",
    }
)

#: SwiftUI views whose *first* (unlabelled) argument is a ``LocalizedStringKey``.
#: A string literal passed here is implicitly looked up in Localizable.strings.
SWIFTUI_FIRST_ARG_VIEWS: frozenset[str] = frozenset(
    {
        "Text",
        "Button",
        "NavigationLink",
        "Label",
        "Toggle",
        "TextField",
        "SecureField",
        "Picker",
        "Section",
        "Menu",
        "DisclosureGroup",
        "Link",
        "alert",
        "confirmationDialog",
    }
)

#: Objective-C / UIKit style calls whose *labelled* arguments are user facing.
LABELLED_ARG_CALLS: dict[str, frozenset[str]] = {
    "UIAlertController": frozenset({"title", "message"}),
    "UIAlertAction": frozenset({"title"}),
    "navigationTitle": frozenset(),  # handled as positional-first-arg below
}

#: `navigationTitle` takes the title as its first positional argument.
FUNCTIONAL_MODIFIERS: frozenset[str] = frozenset({"navigationTitle", "navigationBarTitle"})

#: A format placeholder such as %@, %1$@, %.2f, %lld ...
PLACEHOLDER_RE: re.Pattern[str] = re.compile(
    r"%"
    r"(?:(?P<argnum>\d+)\$)?"
    r"(?P<flags>[-+0#]*)"
    r"(?P<width>\d+|\*)?"
    r"(?:\.(?P<precision>\d+|\*))?"
    r"(?P<length>ll|l|hh|h|q|L|z|j|t)?"
    r"(?P<conversion>[@diouxXeEfFgGcCsSpaA%])"
)


# --------------------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    """A single lexical unit produced by :class:`SwiftLexer`."""

    kind: str  # "string" | "ident" | "op"
    value: str  # decoded string value / identifier name / punctuation
    line: int
    interpolated: bool = False


@dataclass
class Entry:
    """One extracted localizable string."""

    key: str
    comment: str = ""
    kind: str = "unknown"  # nslocalizedstring | string_formatted | swiftui | uikit | xib
    origin: str = ""  # relative path of the source file
    line: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "comment": self.comment,
            "kind": self.kind,
            "origin": self.origin,
            "line": self.line,
        }


@dataclass
class ScanReport:
    """Counters describing what the extraction pass saw."""

    files_scanned: int = 0
    skipped_interpolated: list[dict[str, Any]] = field(default_factory=list)
    skipped_dynamic: list[dict[str, Any]] = field(default_factory=list)
    xib_candidates: list[dict[str, Any]] = field(default_factory=list)
    xib_placeholders_dropped: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "files_scanned": self.files_scanned,
            "skipped_interpolated_count": len(self.skipped_interpolated),
            "skipped_interpolated": self.skipped_interpolated,
            "skipped_dynamic_count": len(self.skipped_dynamic),
            "skipped_dynamic": self.skipped_dynamic,
            "xib_candidate_count": len(self.xib_candidates),
            "xib_candidates": self.xib_candidates,
            "xib_placeholders_dropped": self.xib_placeholders_dropped,
        }


# --------------------------------------------------------------------------------------
# Swift tokenizer
# --------------------------------------------------------------------------------------

IDENT_START: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_$"
IDENT_BODY: str = IDENT_START + "0123456789"

#: Simple escape sequences understood inside Swift string literals.
SIMPLE_ESCAPES: dict[str, str] = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "0": "\0",
    "\\": "\\",
    '"': '"',
    "'": "'",
}


class SwiftLexer:
    """Converts Swift source text into a flat list of :class:`Token`.

    The lexer knows just enough about Swift to be trustworthy for our purpose:
    comments (including nested block comments), single-line string literals,
    multi-line string literals and interpolation segments.
    """

    def __init__(self, text: str) -> None:
        self._text: str = text
        self._i: int = 0
        self._n: int = len(text)
        self._line: int = 1
        self._tokens: list[Token] = []

    # -- public API ---------------------------------------------------------------
    def tokens(self) -> list[Token]:
        """Tokenize the whole input and return the token list."""
        while self._i < self._n:
            char: str = self._text[self._i]
            if char in " \t\r\n":
                self._advance(char == "\n")
            elif char == "/" and self._peek(1) == "/":
                self._skip_line_comment()
            elif char == "/" and self._peek(1) == "*":
                self._skip_block_comment()
            elif char == '"':
                self._read_string_literal()
            elif char in IDENT_START:
                self._read_identifier()
            else:
                self._tokens.append(Token("op", char, self._line))
                self._advance(char == "\n")
        return self._tokens

    # -- navigation helpers -------------------------------------------------------
    def _peek(self, offset: int) -> str:
        index: int = self._i + offset
        return self._text[index] if index < self._n else ""

    def _advance(self, newline: bool = False) -> None:
        self._i += 1
        if newline:
            self._line += 1

    # -- comment handling ---------------------------------------------------------
    def _skip_line_comment(self) -> None:
        while self._i < self._n and self._text[self._i] != "\n":
            self._advance()
        if self._i < self._n:
            self._advance(newline=True)

    def _skip_block_comment(self) -> None:
        depth: int = 0
        while self._i < self._n:
            if self._text[self._i] == "/" and self._peek(1) == "*":
                depth += 1
                self._i += 2
                continue
            if self._text[self._i] == "*" and self._peek(1) == "/":
                depth -= 1
                self._i += 2
                if depth == 0:
                    return
                continue
            if self._text[self._i] == "\n":
                self._line += 1
            self._i += 1
        raise ValueError(f"Unterminated block comment starting on line {self._line}")

    # -- string literals ----------------------------------------------------------
    def _read_string_literal(self) -> None:
        start_line: int = self._line
        multiline: bool = self._text[self._i : self._i + 3] == '"""'
        if multiline:
            raw, end = self._read_multiline_body(self._i + 3)
        else:
            raw, end = self._read_single_line_body(self._i + 1)

        decoded, interpolated = decode_swift_interpolations(raw)
        if multiline:
            decoded = normalize_multiline_indentation(decoded)
        self._i = end
        self._line = self._text.count("\n", 0, end) + 1
        self._tokens.append(Token("string", decoded, start_line, interpolated))

    def _read_single_line_body(self, start: int) -> tuple[str, int]:
        """Return (raw body, index just past the closing quote)."""
        i: int = start
        n: int = self._n
        out: list[str] = []
        while i < n:
            char: str = self._text[i]
            if char == "\\":
                if i + 1 < n and self._text[i + 1] == "(":
                    group, i = balanced_paren_segment(self._text, i + 1)
                    # Keep the backslash so decode_swift_interpolations() can
                    # recognise this segment as an interpolation later on.
                    out.append("\\" + group)
                    continue
                out.append(self._text[i : i + 2])
                if self._text[i + 1] == "\n":
                    self._line += 1
                i += 2
                continue
            if char == '"':
                return "".join(out), i + 1
            if char == "\n":
                # Unterminated literal; bail out so one bad file cannot hang the run.
                return "".join(out), i
            out.append(char)
            i += 1
        return "".join(out), i

    def _read_multiline_body(self, start: int) -> tuple[str, int]:
        i: int = start
        n: int = self._n
        out: list[str] = []
        while i < n:
            if self._text.startswith('"""', i):
                return "".join(out), i + 3
            char: str = self._text[i]
            if char == "\\":
                if i + 1 < n and self._text[i + 1] == "(":
                    group, i = balanced_paren_segment(self._text, i + 1)
                    # Keep the backslash so decode_swift_interpolations() can
                    # recognise this segment as an interpolation later on.
                    out.append("\\" + group)
                    continue
                out.append(self._text[i : i + 2])
                if self._text[i + 1] == "\n":
                    self._line += 1
                i += 2
                continue
            if char == "\n":
                self._line += 1
            out.append(char)
            i += 1
        return "".join(out), i

    def _read_identifier(self) -> None:
        start: int = self._i
        while self._i < self._n and self._text[self._i] in IDENT_BODY:
            self._i += 1
        self._tokens.append(Token("ident", self._text[start : self._i], self._line))


def balanced_paren_segment(text: str, open_index: int) -> tuple[str, int]:
    """Return the interpolation group starting at ``text[open_index] == '('``.

    The returned segment includes *all* characters from the opening parenthesis
    up to (and including) its matching closing parenthesis. Nested literals are
    honoured so that ``\\("a)b")`` is not truncated.
    """
    depth: int = 0
    i: int = open_index
    n: int = len(text)
    start: int = open_index
    while i < n:
        char: str = text[i]
        if char == '"':
            i = skip_string_literal(text, i)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1], i + 1
        i += 1
    return text[start:], n


def skip_string_literal(text: str, start: int) -> int:
    """Return the index just past the string literal starting at ``start``."""
    if text.startswith('"""', start):
        i: int = start + 3
        while i < len(text) and not text.startswith('"""', i):
            i += 1
        return min(i + 3, len(text))
    i = start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i + 1
        i += 1
    return len(text)


def decode_swift_interpolations(raw: str) -> tuple[str, bool]:
    """Decode Swift escape sequences, marking whether interpolation was present.

    Interpolated segments are replaced with a stable marker so downstream code
    can tell "this literal is not a constant" apart from "this literal has an
    interpolated value" without losing the scan position.
    """
    out: list[str] = []
    interpolated: bool = False
    i: int = 0
    n: int = len(raw)
    while i < n:
        char: str = raw[i]
        if char == "\\":
            nxt: str = raw[i + 1] if i + 1 < n else ""
            if nxt == "(":
                segment, consumed = _consume_interpolation(raw, i)
                out.append(segment)
                interpolated = True
                i += consumed
                continue
            if nxt == "u" and i + 2 < n and raw[i + 2] == "{":
                end: int = raw.find("}", i + 2)
                if end != -1:
                    codepoints: list[str] = raw[i + 3 : end].split()
                    try:
                        out.append("".join(chr(int(cp, 16)) for cp in codepoints))
                    except ValueError:
                        out.append("?")
                    i = end + 1
                    continue
            if nxt in SIMPLE_ESCAPES:
                out.append(SIMPLE_ESCAPES[nxt])
                i += 2
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out), interpolated


def _consume_interpolation(raw: str, start: int) -> tuple[str, int]:
    """Replace an ``\\(...)`` segment with a marker, returning (marker, consumed)."""
    depth: int = 0
    i: int = start + 1  # skip the backslash
    n: int = len(raw)
    while i < n:
        char: str = raw[i]
        if char == '"':
            i = skip_string_literal(raw, i)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return "\x00INTERP\x00", i + 1 - start
        i += 1
    return "\x00INTERP\x00", n - start


def normalize_multiline_indentation(value: str) -> str:
    """Apply Xcode's multi-line string literal indentation rules (best effort)."""
    lines: list[str] = value.split("\n")
    if len(lines) <= 1:
        return value.strip("\n")
    indent: str = lines[-1] if lines[-1].strip() == "" else ""
    cleaned: list[str] = []
    for index, line in enumerate(lines):
        if index == 0:
            cleaned.append(line)
            continue
        if indent and line.startswith(indent):
            cleaned.append(line[len(indent) :])
        else:
            cleaned.append(line)
    result: str = "\n".join(cleaned)
    if result.endswith("\n"):
        result = result[:-1]
    return result.strip("\n")


INTERPOLATION_MARKER: str = "\x00INTERP\x00"


def has_interpolation(value: str) -> bool:
    """True when the decoded literal still carries an interpolation marker."""
    return INTERPOLATION_MARKER in value


# --------------------------------------------------------------------------------------
# Extraction over a token stream
# --------------------------------------------------------------------------------------


def matching_paren(tokens: list[Token], open_index: int) -> int:
    """Index of the ``)`` matching the ``(`` at ``open_index`` (or last index)."""
    depth: int = 0
    for index in range(open_index, len(tokens)):
        token: Token = tokens[index]
        if token.kind == "op" and token.value == "(":
            depth += 1
        elif token.kind == "op" and token.value == ")":
            depth -= 1
            if depth == 0:
                return index
    return len(tokens) - 1


def labelled_string_argument(tokens: list[Token], start: int, end: int, label: str) -> str | None:
    """Find ``label: "literal"`` inside ``tokens[start:end]``. Returns the value."""
    for index in range(start, end):
        token: Token = tokens[index]
        if token.kind != "ident" or token.value != label:
            continue
        if index + 2 >= len(tokens):
            continue
        if tokens[index + 1].kind != "op" or tokens[index + 1].value != ":":
            continue
        candidate: Token = tokens[index + 2]
        if candidate.kind != "string":
            continue
        if index + 3 < len(tokens) and tokens[index + 3].kind == "op" and tokens[index + 3].value == "(":
            continue  # e.g. `comment: NSLocalizedString(` - not a plain literal
        if has_interpolation(candidate.value):
            return INTERPOLATION_MARKER
        return candidate.value
    return None


def has_label(tokens: list[Token], start: int, end: int, label: str) -> bool:
    """True when ``tokens[start:end]`` contains the argument label ``label:``."""
    for index in range(start, end):
        token: Token = tokens[index]
        if token.kind == "ident" and token.value == label:
            if tokens[index + 1].kind == "op" and tokens[index + 1].value == ":":
                return True
    return False


def extract_from_swift(path: Path, relative: str, report: ScanReport) -> list[Entry]:
    """Extract every localizable string from one Swift source file."""
    try:
        text: str = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8-sig", errors="replace")

    tokens: list[Token] = SwiftLexer(text).tokens()
    entries: list[Entry] = []

    for index, token in enumerate(tokens):
        if token.kind != "ident":
            continue

        name: str = token.value
        next_token: Token | None = tokens[index + 1] if index + 1 < len(tokens) else None
        if next_token is None or next_token.kind != "op" or next_token.value != "(":
            continue

        open_index: int = index + 1
        close_index: int = matching_paren(tokens, open_index)

        if name == "NSLocalizedString":
            entry = _handle_nslocalizedstring(tokens, open_index, close_index, relative, report)
            if entry is not None:
                entries.append(entry)
            continue

        if name == "String" and _is_string_formatted(tokens, open_index, close_index):
            entry = _handle_nslocalizedstring(tokens, open_index, close_index, relative, report,
                                              kind="string_formatted")
            if entry is not None:
                entries.append(entry)
            continue

        if name in SWIFTUI_FIRST_ARG_VIEWS or name in FUNCTIONAL_MODIFIERS:
            entry = _handle_positional(tokens, open_index, close_index, name, relative, report)
            if entry is not None:
                entries.append(entry)
            continue

        if name in LABELLED_ARG_CALLS:
            for label in LABELLED_ARG_CALLS[name]:
                value: str | None = labelled_string_argument(tokens, open_index, close_index, label)
                if value is None or value == "":
                    continue
                if value == INTERPOLATION_MARKER:
                    report.skipped_interpolated.append(
                        {
                            "origin": relative,
                            "line": token.line,
                            "preview": f"{name}.{label}",
                            "reason": "argument contains string interpolation",
                        }
                    )
                    continue
                entries.append(Entry(key=value, comment=f"{name} {label}", kind="uikit",
                                     origin=relative, line=token.line))

    return entries


def _is_string_formatted(tokens: list[Token], open_index: int, close_index: int) -> bool:
    """True for the custom helper ``String(formatted: "key", comment: "...")``."""
    return (
        open_index + 1 < len(tokens)
        and tokens[open_index + 1].kind == "ident"
        and tokens[open_index + 1].value == "formatted"
        and has_label(tokens, open_index, close_index, "formatted")
    )


def _handle_nslocalizedstring(
    tokens: list[Token],
    open_index: int,
    close_index: int,
    relative: str,
    report: ScanReport,
    kind: str = "nslocalizedstring",
) -> Entry | None:
    """Common handling for NSLocalizedString and String(formatted: ...)."""
    first: Token | None = tokens[open_index + 1] if open_index + 1 < len(tokens) else None
    if first is None or first.kind != "string":
        # Dynamic key - cannot be localized. Count it for the report.
        if first is not None:
            report.skipped_dynamic.append(
                {"origin": relative, "line": first.line, "reason": "dynamic key passed to NSLocalizedString"}
            )
        return None

    if has_interpolation(first.value):
        report.skipped_interpolated.append(
            {
                "origin": relative,
                "line": first.line,
                "preview": first.value[:80],
                "reason": "key contains string interpolation",
            }
        )
        return None

    if has_label(tokens, open_index, close_index, "bundle"):
        # A custom bundle argument means the string is not read from the app table.
        bundle_tokens: list[Token] = tokens[open_index : close_index + 1]
        for idx, tok in enumerate(bundle_tokens):
            if tok.kind == "ident" and tok.value == "bundle":
                following: list[str] = [
                    t.value for t in bundle_tokens[idx + 1 : idx + 4] if t.kind in ("ident", "op")
                ]
                joined: str = " ".join(following)
                if ".main" not in joined and "Bundle.main" not in joined:
                    report.skipped_dynamic.append(
                        {
                            "origin": relative,
                            "line": first.line,
                            "reason": f"uses a non-main bundle ({joined})",
                        }
                    )
                    return None

    if first.value == "":
        return None

    comment: str = labelled_string_argument(tokens, open_index, close_index, "comment") or ""
    return Entry(key=first.value, comment=comment, kind=kind, origin=relative, line=first.line)


def _handle_positional(
    tokens: list[Token],
    open_index: int,
    close_index: int,
    name: str,
    relative: str,
    report: ScanReport,
) -> Entry | None:
    """Handle calls whose first positional argument is a LocalizedStringKey."""
    first: Token | None = tokens[open_index + 1] if open_index + 1 < len(tokens) else None
    if first is None or first.kind != "string":
        return None  # e.g. Text(app.name) or Button(action: ...) - not a literal

    if has_interpolation(first.value):
        report.skipped_interpolated.append(
            {
                "origin": relative,
                "line": first.line,
                "preview": first.value[:80],
                "reason": f"{name} literal contains interpolation",
            }
        )
        return None

    if first.value == "":
        return None

    if name in FUNCTIONAL_MODIFIERS:
        # Require `.navigationTitle(...)` form (a preceding dot).
        preceding: Token | None = tokens[open_index - 2] if open_index >= 2 else None
        if preceding is None or preceding.kind != "op" or preceding.value != ".":
            return None

    if name == "Section" and open_index + 2 < len(tokens):
        # `Section("Title")` is localized; `Section { ... }` never yields a literal.
        pass

    return Entry(key=first.value, comment=f"SwiftUI {name}", kind="swiftui",
                 origin=relative, line=first.line)


# --------------------------------------------------------------------------------------
# XIB extraction
# --------------------------------------------------------------------------------------

#: xml attributes carrying user visible text for UIButton / UILabel / UITextField.
XIB_TEXT_ATTRIBUTES: tuple[str, ...] = ("text", "title", "placeholder", "prompt")

XIB_ATTRIBUTE_RE: re.Pattern[str] = re.compile(
    r'(?P<attr>' + "|".join(XIB_TEXT_ATTRIBUTES) + r')="(?P<value>.*?)"'
)
XIB_STRING_NODE_RE: re.Pattern[str] = re.compile(
    r'<string\s+key="(?P<key>[A-Za-z]+)">(?P<value>.*?)</string>', re.DOTALL
)


def looks_like_sentence(value: str) -> bool:
    """Heuristic: treat only plausible English copy as translatable.

    Interface Builder writes plenty of technical identifiers into these
    attributes (colour spaces, image names, "YES", single words used as
    placeholders). Anything that is not clearly human copy is rejected.
    """
    value = value.strip()
    if len(value) < 2:
        return False
    if not re.search(r"[A-Za-z]", value):
        return False
    if value in XIB_PLACEHOLDER_VALUES:
        return False
    if value.startswith(("http://", "https://", "com.", "group.")):
        return False
    if re.fullmatch(r"[A-Za-z0-9_.\-]+", value) and " " not in value:
        # Single technical token such as "systemBlue" or "YES".
        return False
    if value.isupper() and " " not in value:
        return False
    return True


def extract_from_xib(path: Path, relative: str, report: ScanReport) -> list[Entry]:
    """Conservatively pull visible text out of an Interface Builder document."""
    try:
        text: str = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8-sig", errors="replace")

    entries: list[Entry] = []
    seen: set[str] = set()

    candidates: list[tuple[str, int]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for attr_match in XIB_ATTRIBUTE_RE.finditer(line):
            candidates.append((attr_match.group("value"), line_no))
        for node_match in XIB_STRING_NODE_RE.finditer(line):
            candidates.append((node_match.group("value"), line_no))

    for raw_value, line_no in candidates:
        value: str = xml_unescape(raw_value)
        report.xib_candidates.append(
            {"origin": relative, "line": line_no, "value": value,
             "kept": looks_like_sentence(value)}
        )
        if not looks_like_sentence(value):
            report.xib_placeholders_dropped += 1
            continue
        if value in seen:
            continue
        seen.add(value)
        entries.append(Entry(key=value, comment=f"Interface Builder text ({path.stem}.xib)",
                             kind="xib", origin=relative, line=line_no))

    return entries


def xml_unescape(value: str) -> str:
    """Decode the small set of XML entities used by Interface Builder documents."""
    return (
        value.replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------


def iterate_sources() -> list[tuple[Path, str]]:
    """Yield every Swift file and XIB inside the in-scope directories."""
    sources: list[tuple[Path, str]] = []
    for directory in SCAN_DIRS:
        root: Path = REPO_ROOT / directory
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix not in (".swift", ".xib"):
                continue
            relative: str = path.relative_to(REPO_ROOT).as_posix()
            sources.append((path, relative))
    return sources


def extract_all() -> tuple[list[Entry], ScanReport]:
    """Scan the whole project and return (unique entries, report)."""
    report: ScanReport = ScanReport()
    collected: list[Entry] = []
    sources: list[tuple[Path, str]] = iterate_sources()
    report.files_scanned = len(sources)

    for path, relative in sources:
        if path.suffix == ".swift":
            collected.extend(extract_from_swift(path, relative, report))
        else:
            collected.extend(extract_from_xib(path, relative, report))

    # De-duplicate preserving the first occurrence (and therefore the first comment).
    unique: dict[str, Entry] = {}
    for entry in collected:
        existing: Entry | None = unique.get(entry.key)
        if existing is None:
            unique[entry.key] = entry
            continue
        if not existing.comment and entry.comment:
            existing.comment = entry.comment

    entries: list[Entry] = sorted(unique.values(), key=lambda e: (e.key.casefold(), e.key))
    return entries, report


def placeholder_signature(value: str) -> tuple[tuple[int, str], ...]:
    """Canonical signature of the placeholders in ``value``.

    Implicit placeholders are numbered by their order of appearance so that a
    translation which switches to explicit ``%1$@`` / ``%2$@`` references (for
    Chinese word ordering) compares equal to its key. Only the (argument index,
    conversion) pairs are compared - which is exactly what has to stay stable.
    """
    signature: list[tuple[int, str]] = []
    explicit_count: int = 0
    implicit_count: int = 0
    for match in PLACEHOLDER_RE.finditer(value):
        conversion: str = match.group("conversion")
        if conversion == "%":
            continue  # a literal percent sign
        argnum: str | None = match.group("argnum")
        if argnum is None:
            implicit_count += 1
            signature.append((implicit_count, conversion))
        else:
            explicit_count += 1
            signature.append((int(argnum), conversion))

    if signature and implicit_count and explicit_count:
        # Mixing positional and non-positional references is a runtime bug.
        return tuple()  # deliberately does not match anything

    return tuple(sorted(signature, key=lambda item: (item[0], item[1])))


def count_placeholders(value: str) -> int:
    """Number of real (non ``%%``) placeholders in ``value``."""
    return sum(1 for match in PLACEHOLDER_RE.finditer(value) if match.group("conversion") != "%")


def comment_box(content: list[str], width: int = 63) -> list[str]:
    """Render a fixed width ``/* ... */`` comment box.

    Building these programmatically keeps the right-hand border aligned even
    when the text is edited later (hand padded boxes always drift).
    """
    rule: str = "/* " + "-" * width + " */"
    lines: list[str] = [rule]
    for line in content:
        body: str = "" if not line else line
        if len(body) > width:
            raise ValueError(f"comment box line too long ({len(body)} > {width}): {body!r}")
        lines.append("/* " + body.ljust(width) + " */")
    lines.append(rule)
    return lines


def escape_strings_value(value: str) -> str:
    """Escape a value for a ``.strings`` file body."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


#: C-style escapes understood in the tab separated translation table.
TSV_ESCAPES: list[tuple[str, str]] = [
    ("\\n", "\n"),
    ("\\t", "\t"),
    ("\\r", "\r"),
    ('\\"', '"'),
    ("\\\\", "\\"),
]


def unescape_tsv_field(value: str) -> str:
    """Decode the small escape vocabulary used by the translation table."""
    for needle, replacement in TSV_ESCAPES:
        value = value.replace(needle, replacement)
    return value


def load_translations() -> tuple[dict[str, str], set[str], list[str]]:
    """Load the Chinese translations and the intentionally-English key set.

    The translation table is a UTF-8, tab separated file (``key <TAB> value``)
    so that translators never have to fight JSON escaping. Rows without a tab
    are reported instead of silently swallowed.
    """
    translations: dict[str, str] = {}
    malformed: list[str] = []
    if not TRANSLATIONS_TSV.exists():
        raise SystemExit(f"Missing translations table: {TRANSLATIONS_TSV}")

    for line_no, raw_line in enumerate(
        TRANSLATIONS_TSV.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line: str = raw_line.rstrip("\r")
        if not line.strip() or line.startswith("#"):
            continue
        if "\t" not in line:
            malformed.append(f"{TRANSLATIONS_TSV.name}:{line_no}: {line[:60]!r}")
            continue
        key, _, value = line.partition("\t")
        translations[unescape_tsv_field(key)] = unescape_tsv_field(value)

    keep_english: set[str] = set()
    if KEEP_ENGLISH_TXT.exists():
        for raw_line in KEEP_ENGLISH_TXT.read_text(encoding="utf-8-sig").splitlines():
            # Leading whitespace is trimmed so comments can be indented, but
            # trailing whitespace is preserved: some keys end with a space.
            candidate: str = raw_line.lstrip().rstrip("\r")
            if not candidate.strip() or candidate.startswith("#"):
                continue
            keep_english.add(unescape_tsv_field(candidate))
    return translations, keep_english, malformed


def render_localizable(entries: list[Entry], destination: Path) -> dict[str, list[str]]:
    """Write the zh-Hans ``Localizable.strings`` file. Returns a stats dict."""
    translations, do_not_translate, malformed = load_translations()

    missing: list[str] = []
    placeholder_mismatches: list[str] = []
    untranslated: list[str] = []
    translated_count: int = 0

    lines: list[str] = [
        "/*",
        "  Localizable.strings (Simplified Chinese)",
        "  SideStore",
        "",
        "  Generated by scripts/i18n/extract_strings.py - do not edit by hand.",
        "  To change a translation edit scripts/i18n/translations_zh_Hans.tsv",
        "  and re-run `python scripts/i18n/extract_strings.py render`.",
        "",
        "  Placeholders (%@, %d, %1$@ ...) are validated against the source key.",
        "",
        "  The Interface Builder entries at the end of this file are NOT live yet:",
        "  nib text is resolved through the per-nib strings table",
        "  (<NibName>.strings), not through Localizable.strings. They are kept as",
        "  translation assets for a follow-up pass and will only take effect once",
        "  Base Internationalization is enabled for the xibs and the keys are",
        "  rebuilt (ibtool keys them by ObjectID, not by text).",
        "*/",
        "",
    ]

    def emit(entry: Entry) -> None:
        nonlocal translated_count
        key: str = entry.key
        key_signature: tuple[tuple[int | None, str], ...] = placeholder_signature(key)

        translated: str | None = translations.get(key)
        if translated is None:
            missing.append(key)
            translated = key
        if key in do_not_translate:
            untranslated.append(key)
            translated = key

        if placeholder_signature(translated) != key_signature:
            placeholder_mismatches.append(f"{key!r} -> {translated!r}")
            translated = key  # fall back to the safe original

        lines.append(f"/* {entry.comment or 'No comment provided by engineer.'} */")
        if key in do_not_translate:
            lines.append("/* DO NOT TRANSLATE */")
        elif translated == key:
            lines.append("/* MISSING TRANSLATION */")
        else:
            translated_count += 1
        lines.append(f'"{escape_strings_value(key)}" = "{escape_strings_value(translated)}";')
        lines.append("")

    xib_entries: list[Entry] = [entry for entry in entries if entry.kind == "xib"]
    app_entries: list[Entry] = [entry for entry in entries if entry.kind != "xib"]

    lines.extend(comment_box(["Code strings (Swift / SwiftUI)"]))
    lines.append("")
    for entry in app_entries:
        emit(entry)

    lines.extend(
        comment_box(
            [
                "Interface Builder text - NOT LIVE IN THIS RELEASE",
                "",
                "These rows are translation assets only. A nib resolves its text",
                "through the per-nib strings table (<NibName>.strings), not",
                "through Localizable.strings, so nothing below is shown yet.",
                "",
                "To make them live: enable Base Internationalization for the",
                "xibs and export their strings files. Note that ibtool keys nib",
                "strings by ObjectID, so the text-based keys below must be",
                "re-mapped before they can be used.",
            ]
        )
    )
    lines.append("")
    for entry in xib_entries:
        emit(entry)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "missing": missing,
        "placeholder_mismatches": placeholder_mismatches,
        "untranslated": untranslated,
        "translated": translated_count,
        "malformed_rows": malformed,
    }


def cmd_extract(_args: argparse.Namespace) -> int:
    """``extract`` sub-command implementation."""
    entries, report = extract_all()
    payload: dict[str, Any] = {
        "total_unique_keys": len(entries),
        "by_kind": {},
        "entries": [entry.as_dict() for entry in entries],
        "report": report.as_dict(),
    }
    for entry in entries:
        payload["by_kind"][entry.kind] = payload["by_kind"].get(entry.kind, 0) + 1

    EXTRACTED_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Scanned files            : {report.files_scanned}")
    print(f"Unique keys              : {len(entries)}")
    for kind, count in sorted(payload["by_kind"].items()):
        print(f"  {kind:<20}: {count}")
    print(f"Skipped (interpolated)   : {len(report.skipped_interpolated)}")
    print(f"Skipped (dynamic/bundle) : {len(report.skipped_dynamic)}")
    print(f"XIB candidates kept      : {len(report.xib_candidates) - report.xib_placeholders_dropped}")
    print(f"Written                  : {EXTRACTED_JSON}")
    return 0


def cmd_render(_args: argparse.Namespace) -> int:
    """``render`` sub-command implementation."""
    entries, _report = extract_all()
    stats: dict[str, Any] = render_localizable(entries, LOCALIZABLE_STRINGS)

    print(f"Rendered keys            : {len(entries)}")
    print(f"Translated               : {stats['translated']}")
    print(f"Kept English on purpose  : {len(stats['untranslated'])}")
    print(f"Missing translations     : {len(stats['missing'])}")
    print(f"Placeholder mismatches   : {len(stats['placeholder_mismatches'])}")
    print(f"Malformed table rows     : {len(stats['malformed_rows'])}")
    for row in stats["malformed_rows"]:
        print(f"  x {row}")
    for problem in stats["placeholder_mismatches"]:
        print(f"  ! {problem}")
    for key in stats["missing"]:
        print(f"  ? missing: {key!r}")
    print(f"Written                  : {LOCALIZABLE_STRINGS}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Create the command line parser."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Extract and render SideStore localization strings."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("extract", help="write scripts/i18n/extracted.json")
    subparsers.add_parser("render", help="write AltStore/zh-Hans.lproj/Localizable.strings")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args: argparse.Namespace = build_parser().parse_args(argv)
    if args.command == "extract":
        return cmd_extract(args)
    return cmd_render(args)


if __name__ == "__main__":
    sys.exit(main())
