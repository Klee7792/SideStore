"""Lead final re-verification after the post-QA spacing fix and full re-render.

Independent of both the engineer's validate_strings.py and QA's scripts:
a minimal .strings lexer + placeholder check written from scratch.

Usage:
  C:/Users/Yun/.workbuddy/binaries/python/versions/3.13.12/python.exe lead_final_check.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TARGETS = [
    ROOT / "AltStore" / "zh-Hans.lproj" / "Localizable.strings",
    ROOT / "AltStore" / "zh-Hans.lproj" / "InfoPlist.strings",
]

PLACEHOLDER = re.compile(
    r"""(?<!%)%                 # leading %, not preceded by another %
        (?:(\d+)\$)?            # optional positional index
        ([-+0#']*)              # flags
        (\d+|\*)?               # width
        (?:\.(\d+|\*))?         # precision
        (@|d|D|i|u|U|x|X|o|O|f|e|E|g|G|c|C|s|S|p|a|A|F)  # conversion
    """,
    re.VERBOSE,
)


def lex(text: str):
    """Yield (key, value, line) triples. Raises ValueError on syntax errors."""
    i, n, line = 0, len(text), 1
    out = []
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if text.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if text.startswith("/*", j):
                    depth += 1
                    j += 2
                elif text.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    if text[j] == "\n":
                        line += 1
                    j += 1
            if depth:
                raise ValueError(f"line {line}: unterminated block comment")
            i = j
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue

        def read_string(pos):
            if pos >= n or text[pos] != '"':
                raise ValueError(f"line {line}: expected string literal")
            pos += 1
            buf = []
            while True:
                if pos >= n:
                    raise ValueError(f"line {line}: unterminated string")
                ch = text[pos]
                if ch == "\n":
                    raise ValueError(f"line {line}: raw newline inside string")
                if ch == "\\":
                    if pos + 1 >= n:
                        raise ValueError(f"line {line}: dangling backslash")
                    nxt = text[pos + 1]
                    if nxt not in '"\\ntr':
                        raise ValueError(f"line {line}: bad escape \\{nxt}")
                    buf.append(nxt)
                    pos += 2
                    continue
                if ch == '"':
                    pos += 1
                    break
                buf.append(ch)
                pos += 1
            return "".join(buf), pos

        key, i = read_string(i)
        while i < n and text[i] in " \t":
            i += 1
        if i >= n or text[i] != "=":
            raise ValueError(f"line {line}: expected '=' after key {key!r}")
        i += 1
        while i < n and text[i] in " \t":
            i += 1
        value, i = read_string(i)
        while i < n and text[i] in " \t":
            i += 1
        if i >= n or text[i] != ";":
            raise ValueError(f"line {line}: expected ';' after value of {key!r}")
        i += 1
        out.append((key, value, line))
    return out


def signature(s: str):
    """Ordered list of (index_or_None, conversion) for real printf placeholders."""
    sig = []
    for m in PLACEHOLDER.finditer(s):
        if m.group(5) == "%":
            continue
        sig.append((int(m.group(1)) if m.group(1) else None, m.group(5)))
    return sig


def normalized(s: str):
    """Conversion sequence in argument order.

    The KEY must stay a verbatim copy of the source literal (usually plain `%@`).
    The VALUE may legitimately rewrite it as `%1$@` / `%2$@` (and reorder), so
    compare conversions after sorting the value's placeholders by their index.
    """
    sig = signature(s)
    if sig and all(idx is not None for idx, _ in sig):
        return [conv for _, conv in sorted(sig, key=lambda p: p[0])], sorted(
            idx for idx, _ in sig
        )
    return [conv for _, conv in sig], None


def main() -> int:
    failures, warnings = [], []

    for path in TARGETS:
        if not path.exists():
            failures.append(f"{path}: MISSING")
            continue
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            failures.append(f"{path.name}: has UTF-8 BOM")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{path.name}: not valid UTF-8 ({exc})")
            continue

        try:
            entries = lex(text)
        except ValueError as exc:
            failures.append(f"{path.name}: syntax error {exc}")
            continue

        seen = {}
        for key, value, line in entries:
            if key in seen:
                failures.append(f"{path.name}: duplicate key {key!r} (lines {seen[key]}, {line})")
            seen[key] = line

            k_conv, _ = normalized(key)
            v_conv, v_idx = normalized(value)
            if k_conv != v_conv:
                failures.append(
                    f"{path.name}:{line} placeholder mismatch {key!r} -> {value!r} "
                    f"(key={k_conv} value={v_conv})"
                )
            if v_idx is not None:
                if v_idx != list(range(1, len(v_idx) + 1)):
                    failures.append(
                        f"{path.name}:{line} bad positional indices {v_idx} in {key!r}"
                    )
            elif [i for i, _ in signature(value) if i is not None]:
                failures.append(
                    f"{path.name}:{line} mixed positional/non-positional in {key!r}"
                )

        print(f"[OK] {path.name}: {len(entries)} entries, 0 syntax errors, 0 duplicate keys")

    # The two entries touched by the post-QA spacing fix.
    loc = ROOT / "AltStore" / "zh-Hans.lproj" / "Localizable.strings"
    text = loc.read_text(encoding="utf-8")
    entries = lex(text)
    by_key = {k: v for k, v, _ in entries}
    checks = [
        ("The source “%@” contains multiple apps with %@.", "（%2$@）"),
        ("The source “%@” contains %@ for %@.", "存在%2$@"),
        ("the bundle identifier %@", "Bundle ID 为 %@"),
        ("the same bundle identifier", "相同的 Bundle ID"),
        ("YES", "是"),
        ("NO", "否"),
        ("ANISETTE", "ANISETTE"),
        ("SIDESIGN", "SIDESIGN"),
        ("Version %1$@%2$@", "版本 %1$@%2$@"),
    ]
    for key, expect in checks:
        value = by_key.get(key)
        if value is None:
            failures.append(f"missing key {key!r}")
        elif expect not in value:
            failures.append(f"key {key!r} = {value!r}, expected to contain {expect!r}")

    print(f"[OK] spot-checked {len(checks)} keys touched in the final fix round")

    for w in warnings:
        print(f"[WARN] {w}")

    if failures:
        print("\n=== FAILURES ===")
        for f in failures:
            print(f"  {f}")
        return 1

    print("\nRESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
