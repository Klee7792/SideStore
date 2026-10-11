"""QA-owned placeholder (format-specifier) extractor and comparator.

Implemented from the IEEE printf / NSString `String(format:)` grammar rather than a
naive "count the percent signs" approach:

    spec        := '%' [ argnum '$' ] [ flags ] [ width ] [ '.' precision ] [ length ] conv
    argnum      := DIGIT+                       (positional / iOS 5+ style: %1$@)
    flags       := one or more of  - + space # 0 ' (also accepts '*' width)
    width       := DIGIT+  |  '*'
    precision   := DIGIT+  |  '*'
    length      := h | hh | l | ll | q | L | z | j | t
    conv        := @ | d | D | i | u | U | x | X | o | O | f | e | E | g | G | c | C |
                   s | S | p | a | A | %

`%%` consumes no argument and is tracked separately: it must still match between the
English key and the zh-Hans value, but it never participates in the positional
permutation / arity checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

# Named groups so the same regex drives extraction, recording and comparison.
_SPEC_RE = re.compile(
    r"""
    %
    (?P<pos>\d+\$)?
    (?P<flags>[-+ #0']*)
    (?P<width>\d+|\*)?
    (?:\.(?P<precision>\d+|\*))?
    (?P<length>hh|h|ll|l|q|L|z|j|t)?
    (?P<conv>[@dDiUuXxOofFeEgGcCsSpAa%])
    """,
    re.VERBOSE,
)

# Objective-C / CoreFoundation accepts these conversions; @ and % are Apple extensions.
_CONVERSIONS = set("@dDiUuXxOofFeEgGcCsSpAa%")


@dataclass(frozen=True)
class Spec:
    raw: str
    pos: Optional[int]      # 1-based positional index, or None for sequential specs
    conv: str
    flags: str
    width: str
    precision: str
    length: str

    @property
    def is_percent_literal(self) -> bool:
        return self.conv == "%"

    @property
    def signature(self) -> Tuple[Optional[int], str]:
        """Identity used when comparing key side vs value side."""
        return (self.pos, self.conv)


@dataclass
class PlaceholderReport:
    specs: List[Spec]
    stray_percent: List[int]     # indices of '%' that did not start a valid spec

    @property
    def args(self) -> List[Spec]:
        return [s for s in self.specs if not s.is_percent_literal]

    @property
    def percent_literals(self) -> int:
        return sum(1 for s in self.specs if s.is_percent_literal)

    @property
    def arg_signature(self) -> List[Tuple[Optional[int], str]]:
        return [s.signature for s in self.args]

    @property
    def all_signature(self) -> List[Tuple[Optional[int], str]]:
        return [s.signature for s in self.specs]


def extract(text: str) -> PlaceholderReport:
    specs: List[Spec] = []
    stray: List[int] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "%":
            i += 1
            continue
        m = _SPEC_RE.match(text, i)
        if not m:
            stray.append(i)
            i += 1
            continue
        pos_raw = m.group("pos")
        specs.append(
            Spec(
                raw=m.group(0),
                pos=int(pos_raw[:-1]) if pos_raw else None,
                conv=m.group("conv"),
                flags=m.group("flags") or "",
                width=m.group("width") or "",
                precision=m.group("precision") or "",
                length=m.group("length") or "",
            )
        )
        i = m.end()
    return PlaceholderReport(specs=specs, stray_percent=stray)


# ------------------------------------------------------------------ validation


def _validate_positional_usage(report: PlaceholderReport, label: str) -> List[str]:
    """Positional-argument invariants that must hold within a single format string."""
    problems: List[str] = []
    args = report.args
    if not args:
        return problems

    used = [a.pos for a in args if a.pos is not None]
    nonpositional = [a for a in args if a.pos is None]

    # Rule: never mix "%1$@"-style with bare "%@" in one format string.  Foundation's
    # cursor behaviour for that case is documented as undefined; in practice the
    # sequential specs keep counting from wherever the cursor was left, silently
    # shifting every subsequent argument.
    if used and nonpositional:
        problems.append(
            f"{label}: mixes positional specifier(s) "
            f"({', '.join(a.raw for a in args if a.pos is not None)}) with non-positional "
            f"({', '.join(a.raw for a in nonpositional)}) in one format string "
            "- runtime argument misalignment"
        )
        return problems

    if used:
        # Indices must be a *complete permutation* of 1..n.  Re-ordering is legitimate
        # (that is what positional specifiers are for); gaps or repeats are not.
        n = len(used)
        missing = sorted(set(range(1, n + 1)) - set(used))
        repeated = sorted({p for p in used if used.count(p) > 1})
        out_of_range = sorted({p for p in used if p < 1 or p > n})
        if missing or repeated or out_of_range:
            problems.append(
                f"{label}: positional indices {used} do not form a permutation of 1..{n}"
                + (f" - missing {missing}" if missing else "")
                + (f" - repeated {repeated}" if repeated else "")
                + (f" - out of range {out_of_range}" if out_of_range else "")
            )
    return problems


@dataclass
class CompareResult:
    key_text: str
    value_text: str
    errors: List[str]          # will break at runtime / lose arguments
    warnings: List[str]        # legal but requires a human to confirm intent

    @property
    def ok(self) -> bool:
        return not self.errors


def effective_order(report: PlaceholderReport) -> List[int]:
    """The order in which varargs are consumed, resolving implicit positions.

    `%@ %@`               -> [1, 2]
    `%2$@ %1$@`           -> [2, 1]
    `%@ %% %@`            -> [1, 2]   (%% consumes nothing)
    """
    order: List[int] = []
    cursor = 1
    for spec in report.args:
        if spec.pos is None:
            order.append(cursor)
            cursor += 1
        else:
            order.append(spec.pos)
            if spec.pos >= cursor:
                cursor = spec.pos + 1
    return order


def analyze(key_text: str, value_text: str) -> CompareResult:
    """Compare an English `NSLocalizedString` key against its zh-Hans value.

    Severity model
    --------------
    error   = arguments would be dropped, duplicated, or reinterpreted at runtime
    warning = legal printf, but differs from the English key in a way a human must bless
              (deliberate reordering, or a percent sign that is/isn't a specifier)
    """
    errors: List[str] = []
    warnings: List[str] = []

    krep = extract(key_text)
    vrep = extract(value_text)
    kargs, vargs = krep.args, vrep.args

    # 1. arity: number of consumed arguments must match exactly
    if len(kargs) != len(vargs):
        errors.append(
            f"arity mismatch: key consumes {len(kargs)} argument(s) "
            f"([{', '.join(a.raw for a in kargs)}]), value consumes {len(vargs)} "
            f"([{', '.join(a.raw for a in vargs)}])"
        )
        return CompareResult(key_text, value_text, errors, warnings)

    if krep.stray_percent or vrep.stray_percent:
        warnings.append(
            f"stray '%' present: key has {len(krep.stray_percent)}, "
            f"value has {len(vrep.stray_percent)}; key-side specs="
            f"{[a.raw for a in kargs]}, value-side specs={[a.raw for a in vargs]}"
        )

    # 2. per-argument conversion must be identical (re-indexed by consumed argument)
    korder = effective_order(krep)
    vorder = effective_order(vrep)
    k_by_arg = dict(zip(korder, kargs))
    v_by_arg = dict(zip(vorder, vargs))
    for arg_no in sorted(set(korder) | set(vorder)):
        kspec = k_by_arg.get(arg_no)
        vspec = v_by_arg.get(arg_no)
        if kspec is None or vspec is None:
            errors.append(
                f"argument #{arg_no} is consumed on one side only "
                f"(key order {korder}, value order {vorder})"
            )
            continue
        if kspec.conv != vspec.conv:
            errors.append(
                f"argument #{arg_no} conversion differs: key {kspec.raw!r} vs value {vspec.raw!r} "
                "(e.g. %%@ vs %%d will crash or print garbage)"
            )
        elif (kspec.width, kspec.precision, kspec.flags) != (
            vspec.width,
            vspec.precision,
            vspec.flags,
        ):
            warnings.append(
                f"argument #{arg_no} uses the same conversion but different width/precision/"
                f"flags: key {kspec.raw!r} vs value {vspec.raw!r}"
            )

    # 3. percent literals should appear equally often
    if krep.percent_literals != vrep.percent_literals:
        warnings.append(
            f"number of '%%' literals differs: key={krep.percent_literals}, "
            f"value={vrep.percent_literals}"
        )

    # 4. per-string invariants (positional hygiene)
    errors.extend(_validate_positional_usage(krep, "key"))
    errors.extend(_validate_positional_usage(vrep, "value"))

    # 5. reordering is legal - but surface it so a human confirms it was intentional
    if korder != vorder and not errors:
        warnings.append(
            f"argument order changed vs English: key order {korder} vs value order {vorder} "
            "- intentional reordering is fine, please confirm it reads correctly"
        )

    return CompareResult(key_text, value_text, errors, warnings)


# Backwards-compatible thin wrapper used by older scripts.
def compare(key_text: str, value_text: str) -> CompareResult:
    return analyze(key_text, value_text)
