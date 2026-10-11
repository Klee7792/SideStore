"""Mutation test for qa_composed_messages.py.

A guard that always prints OK is worthless, so we feed it known-bad inputs and assert it
actually complains.  Each case below is a *real* historical or hypothetical edit.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mini_format import format as swift_format  # noqa: E402
import qa_composed_messages as guard  # noqa: E402

TEMPLATE = "软件源“%1$@”中包含多个应用%s。"  # %s patched per case

CASES = [
    (
        "round-1 shipped form: template keeps a space, Chinese fragment",
        "软件源“%1$@”中包含多个应用使用了 %2$@。",
        "相同的 Bundle ID",
        True,
    ),
    (
        "round-1 shipped form: template keeps a space, Latin fragment",
        "软件源“%1$@”中包含多个应用使用了 %2$@。",
        "Bundle ID 为 com.example.app",
        False,
    ),
    (
        "my rejected proposal: no space in template, leading space in fragment",
        "软件源“%1$@”中包含多个应用使用了%2$@。",
        " Bundle ID 为 com.example.app",
        False,
    ),
    (
        "  ...after a future editor deletes that leading space (silent degradation)",
        "软件源“%1$@”中包含多个应用使用了%2$@。",
        "Bundle ID 为 com.example.app",
        True,
    ),
    (
        "current shipped form: full-width parentheses, Latin fragment",
        "软件源“%1$@”中包含多个应用（%2$@）。",
        "Bundle ID 为 com.example.app",
        False,
    ),
    (
        "current shipped form: full-width parentheses, Chinese fragment",
        "软件源“%1$@”中包含多个应用（%2$@）。",
        "相同的 Bundle ID",
        False,
    ),
]

print("mutation test - does the composed-message guard actually catch regressions?\n")
failures = 0
for label, template, fragment, should_warn in CASES:
    rendered = swift_format(template, "MySource", fragment)
    issues = guard.spacing_defects(rendered)
    caught = bool(issues)
    verdict = "OK" if caught == should_warn else "GUARD MISSED IT"
    if caught != should_warn:
        failures += 1
    print(f"[{verdict}] expected_warn={should_warn!s:5s} caught={caught!s:5s}  {label.strip()}")
    print(f"          {rendered}")
    for issue in issues:
        print(f"          -> {issue}")
    print()

print("=" * 70)
if failures:
    print(f"{failures} mutation(s) behaved unexpectedly - THE GUARD IS UNRELIABLE")
    sys.exit(1)
print("guard behaves correctly on all mutations (detects every seeded defect,")
print("stays quiet on every legitimate form)")
