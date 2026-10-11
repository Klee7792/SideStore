"""A miniature, dependency-free re-implementation of Foundation's `String(format:)`.

Purpose: reproduce - deterministically, on Windows - what iOS will print when it feeds
runtime arguments into English and zh-Hans format strings, so that the equivalence claim
in task item D can be *demonstrated* rather than asserted.

Supported: sequential and positional (%N$) specifiers, flags (-, +, space, 0, #),
width, precision, length modifiers, and conversions %@ %d %i %D %u %U %f %e %g %c %s %x %o %p %%.
"""

from __future__ import annotations

import re
from typing import Any, List

from placeholders import _SPEC_RE, Spec, extract


def _format_one(spec: Spec, arg: Any) -> str:
    conv = spec.conv

    if conv == "%":
        return "%"

    if conv in "@":
        out = str(arg)
    elif conv in "dDi":
        out = str(int(arg))
    elif conv in "uU":
        out = str(int(arg) & 0xFFFFFFFFFFFFFFFF if int(arg) >= 0 else int(arg))
    elif conv in "fF":
        out = f"{float(arg):.{int(spec.precision) if spec.precision.isdigit() else 6}f}"
    elif conv in "eE":
        out = f"{float(arg):.{int(spec.precision) if spec.precision.isdigit() else 6}e}"
    elif conv in "gG":
        out = f"{float(arg):.{int(spec.precision) if spec.precision.isdigit() else 6}g}"
    elif conv == "c":
        out = chr(int(arg))
    elif conv in "sS":
        out = str(arg)
    elif conv in "xX":
        digits = f"{int(arg):x}" if conv == "x" else f"{int(arg):X}"
        if spec.flags and "#" in spec.flags and int(arg) != 0:
            digits = ("0x" if conv == "x" else "0X") + digits
        out = digits
    elif conv == "o":
        out = f"{int(arg):o}"
    elif conv in "pP":
        out = f"0x{int(arg):x}"
    elif conv in "aA":
        out = float(arg).hex()
    else:  # pragma: no cover - guarded by regex character class
        raise ValueError(f"unsupported conversion {conv!r}")

    # width / zero padding
    if spec.width.isdigit():
        width = int(spec.width)
        if len(out) < width:
            pad_char = "0" if ("0" in spec.flags and out and out[0] in "+-") else (
                "0" if "0" in spec.flags else " "
            )
            if "-" in spec.flags:
                out = out.ljust(width)
            elif pad_char == "0" and conv not in "@sSc":
                sign = ""
                if out and out[0] in "+-":
                    sign, out = out[0], out[1:]
                out = sign + out.rjust(width - len(sign), "0")
            else:
                out = out.rjust(width)
    elif spec.precision.isdigit() and conv in "@sS":
        out = out[: int(spec.precision)]

    return out


def format(fmt: str, *args: Any) -> str:
    """Apple-compatible `String(format:)` semantics for the subset we care about."""
    report = extract(fmt)
    specs = report.specs

    cursor = 0  # implicit argument pointer for non-positional specs
    out: List[str] = []
    i = 0
    for m in _SPEC_RE.finditer(fmt):
        out.append(fmt[i: m.start()])
        i = m.end()
        spec = specs[len(out) - 1] if False else None  # placeholder, resolved below

    # Re-walk so we can pair each regex match with its parsed Spec in order.
    out = []
    i = 0
    idx = 0
    for m in _SPEC_RE.finditer(fmt):
        out.append(fmt[i: m.start()])
        i = m.end()
        spec = specs[idx]
        idx += 1
        if spec.is_percent_literal:
            out.append("%")
            continue
        if spec.pos is not None:
            # positional: %1$ refers to the FIRST vararg, i.e. index 0
            arg = args[spec.pos - 1]
        else:
            arg = args[cursor]
            cursor += 1
        out.append(_format_one(spec, arg))
    out.append(fmt[i:])
    return "".join(out)
