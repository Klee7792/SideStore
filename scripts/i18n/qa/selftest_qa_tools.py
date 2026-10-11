"""Self-tests for the QA tooling itself.

A checker that has never been tested cannot be trusted to pass judgement on someone
else's code - so the first thing we do is prove the parser, the placeholder comparator
and the mini String(format:) agree with hand-verified expectations.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mini_format import format as swift_format  # noqa: E402
from placeholders import compare, extract  # noqa: E402
from strings_syntax import StringsParser  # noqa: E402

FAILURES: list[str] = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILURES.append(f"{name}\n     got  {got!r}\n     want {want!r}")
        print(f"  FAIL {name}\n     got  {got!r}\n     want {want!r}")
    else:
        print(f"  ok   {name}")


def p(text: str):
    return StringsParser(text).parse()


# --------------------------------------------------------------- parser tests

print("\n-- parser: happy paths --")
r = p('"a" = "b";')
check("simple pair count", len(r.entries), 1)
check("simple pair value", (r.entries[0].key, r.entries[0].value), ("a", "b"))
check("simple pair ok", r.ok, True)

r = p('/* c */\n// line\n"k"="v";/* trailing */')
check("comments + no spaces", (r.entries[0].key, r.entries[0].value), ("k", "v"))

r = p('"outer /* nested */ still comment" = "v";')
check("comment inside string is literal", r.entries[0].key, "outer /* nested */ still comment")

r = p('/* level1 /* level2 */ still comment */ "a" = "b";')
check("nested block comment", (r.ok, len(r.entries)), (True, 1))

r = p('"a" = "say \\"hi\\"";')
check("escaped quote", r.entries[0].value, 'say "hi"')

r = p('"a" = "line\\nbreak\\tTab\\\\back";')
check("escapes", r.entries[0].value, "line\nbreak\tTab\\back")

r = p('"\\U00e9" = "v";')
check("unicode escape", r.entries[0].key, "\u00e9")

r = p('"a" = "";')
check("empty value", r.entries[0].value, "")

print("\n-- parser: must-error inputs --")
r = p('"a" = "b"')                      # no semicolon
check("missing semicolon errors", (r.ok, bool(r.errors)), (False, True))

r = p('"a" "b";')                       # missing '='
check("missing equals errors", bool(r.errors), True)

r = p('"a" = "unterminated;')
check("unterminated string errors", bool(r.errors), True)

r = p('"a" = "multi\nline";')
check("raw newline in string errors", bool(r.errors), True)

r = p('"dup" = "1";\n"dup" = "2";')
check("duplicate key detected", (r.duplicate_keys[0][0], len(r.duplicate_keys)), ("dup", 1))
check("duplicate makes !ok", r.ok, False)

r = p('/* unterminated comment\n"a" = "b";')
check("unterminated comment errors", bool(r.errors), True)

r = p('"a" = "v\\q";')
check("bad escape errors", bool(r.errors), True)

r = p('bare = "v";')
check("bare token rejected (strict mode)", bool(r.errors), True)

print("\n-- parser: real file smoke --")
pairs, _ = __import__("strings_syntax").parse_file(
    os.path.join(HERE, "..", "..", "..", "AltStore", "zh-Hans.lproj", "Localizable.strings")
)
check("Localizable.strings parses clean", (pairs.ok, len(pairs.entries)), (True, 1151))

# ------------------------------------------------------- placeholder extractor

print("\n-- placeholder extraction --")
check("%@", extract("%@").arg_signature, [(None, "@")])
check("%@ %@", extract("%@ %@").arg_signature, [(None, "@"), (None, "@")])
check("%1$@ %2$@", extract("%1$@ %2$@").arg_signature, [(1, "@"), (2, "@")])
check("%ld", extract("%ld").arg_signature, [(None, "d")])
check("%lld", extract("%lld").arg_signature, [(None, "d")])
check("%.2f", extract("%.2f").arg_signature, [(None, "f")])
check("%@ %%", extract("%@ %%").percent_literals, 1)
check("%% not an arg", extract("%%").args, [])
check("half-width percent dashed", extract("40% — x").stray_percent, [2])
check("%@ no stray", extract("%@").stray_percent, [])
check("order preserved", extract("a %d b %@ c").arg_signature, [(None, "d"), (None, "@")])
check("positional reorder", extract("%2$@ %1$@").arg_signature, [(2, "@"), (1, "@")])

print("\n-- placeholder comparison: ERROR level (must break) --")


def errs(k, v):
    return compare(k, v).errors


def warns(k, v):
    return compare(k, v).warnings


check("identical", errs("%@ %@", "%@ %@"), [])
check("missing one", bool(errs("%@ %@", "%@")), True)
check("wrong conversion", bool(errs("%@ %d", "%@ %@")), True)
check("reordered non-positional", bool(errs("%@ %d", "%d %@")), True)
check("mix detected", bool(errs("%@ %@", "%1$@ %@")), True)
check("repeat detected", bool(errs("%@ %@ %@", "%1$@ %1$@ %2$@")), True)
check("index jump out of range", bool(errs("%@ %@ %@", "%1$@ %4$@ %2$@")), True)
check("arity mismatch", bool(errs("%@ %@", "%@ %@ %@")), True)
check("%@ vs %d single", bool(errs("%@ left", "%d 剩余")), True)
check("huge-key arity", bool(errs("%@/%@", "%1$@/")), True)

print("\n-- placeholder comparison: WARN level (legal, needs human bless) --")
check("positional reorder -> warning only", errs("%@ %@", "%2$@ %1$@"), [])
check("  ...and it is warned", bool(warns("%@ %@", "%2$@ %1$@")), True)
check("1,3,2 permutation -> clean", errs("%@ %@ %@", "%1$@ %3$@ %2$@"), [])
check("  ...and it is warned", bool(warns("%@ %@ %@", "%1$@ %3$@ %2$@")), True)
check("adding indices 1,2 -> clean", errs("%@ %@", "%1$@ %2$@"), [])
check("  ...no reorder warning", bool(warns("%@ %@", "%1$@ %2$@")), False)
check("%% count differs -> warning", bool(warns("50%% off", "五折优惠")), True)

# --------------------------------------------------------- mini String(format:)

print("\n-- mini String(format:) --")
check("two objects", swift_format("Version %@%@", "0.6.4", " (123)"), "Version 0.6.4 (123)")
check("positional", swift_format("Version %1$@%2$@", "0.6.4", " (123)"), "Version 0.6.4 (123)")
check("zh positional", swift_format("版本 %1$@%2$@", "0.6.4", " (123)"), "版本 0.6.4 (123)")
check("reorder", swift_format("版本 %2$@ %1$@", "A", "B"), "版本 B A")
check("literal percent", swift_format("100%% sure", ), "100% sure")
check("int", swift_format("%d items", 5), "5 items")
check("float precision", swift_format("%.1f MB", 12.34), "12.3 MB")
check("float default", swift_format("%f", 1.5), "1.500000")
check("zero pad", swift_format("%02d", 7), "07")
check("percent with @ arg", swift_format("~40%% done %@", "x"), "~40% done x")

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} SELF-TEST FAILURE(S) - the QA tooling is unreliable:")
    for f in FAILURES:
        print("  * " + f)
    sys.exit(1)
print("ALL SELF-TESTS PASSED")
