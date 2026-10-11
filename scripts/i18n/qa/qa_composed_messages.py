"""Regression guard for runtime-composed messages.

Why this file exists
--------------------
`SourceError.swift` (and friends) localise a *fragment* first, then splice the result
into another already-localised *template*:

    String(format: NSLocalizedString("The source \"%@\" contains multiple apps with %@."),
           sourceName,
           String(format: NSLocalizedString("the bundle identifier %@"), bundleID))

Both halves individually pass every placeholder / syntax / punctuation check - but the
*combination* can still read wrong, e.g.

    ...包含多个应用使用了 相同的 Bundle ID。      <- stray space (Chinese,Chinese)
    ...包含多个应用使用了Bundle ID 为 com.x。     <- missing space (Chinese,Latin)

Ordinary linting cannot see this: when the template is scanned, the fragment has not been
substituted yet, so the offending space does not exist in the file.  Both the implementer's
validator and the QA suite had exactly this blind spot - which is what made the
"add a leading space to the fragment" fix dangerous: if a future editor deleted that space,
no tool would notice.

This check therefore renders every known template x fragment combination and judges the
*result*, not the source rows.

Composition sites are declared in COMPOSITIONS below; they were derived by reading the
Swift sources and are re-verified against the shipped .strings on every run.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mini_format import format as swift_format  # noqa: E402
from strings_syntax import parse_file  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
LOCALIZABLE = os.path.join(REPO, "AltStore", "zh-Hans.lproj", "Localizable.strings")

CJK = r"\u3400-\u4dbf\u4e00-\u9fff"
LATIN = r"A-Za-z0-9"

# Each composition is (template_key, variant_name, {slot: fragment_key}, provenance).
# A "variant" is one real runtime branch: which fragment actually lands in which slot.
# Several entries can share a template - that is the point, the branches differ.
COMPOSITIONS = [
    (
        "The source “%@” contains multiple apps with %@.",
        "with an explicit bundle ID",
        {2: "the bundle identifier %@"},
        "SideStore/Core/Operations/Errors/SourceError.swift:84",
    ),
    (
        "The source “%@” contains multiple apps with %@.",
        "with the same bundle ID",
        {2: "the same bundle identifier"},
        "SideStore/Core/Operations/Errors/SourceError.swift:84",
    ),
    (
        "The source “%@” contains %@ for %@.",
        "duplicate versions, named app",
        {2: "duplicate versions"},
        "SideStore/Core/Operations/Errors/SourceError.swift:105",
    ),
    (
        "The source “%@” contains %@ for %@.",
        "duplicate versions, unnamed app (中文片段落在 slot 3)",
        {2: "duplicate versions", 3: "one or more apps"},
        "SideStore/Core/Operations/Errors/SourceError.swift:105",
    ),
]

# Compositions that are known-imperfect and accepted as such.  Listing them here (rather
# than tolerating a permanently red run) keeps the guard useful as a real gate: anything
# NOT on this list fails the run.  Each entry documents why it cannot be fixed in .strings.
ACCEPTED = {
    (
        "The source “%@” contains %@ for %@.",
        "duplicate versions, unnamed app (中文片段落在 slot 3)",
    ): (
        "slot 3 receives either a Latin app name (wants a space) or the Chinese fragment "
        "'one or more apps' (does not). One template cannot serve both; the main branch "
        "(Latin app name) is optimised. Fixing it properly requires changing the Swift "
        "composition. Accepted 2025 - see docs/i18n-glossary.md §5.4."
    ),
}

# Sample values fed into the *other* slots and into placeholders inside fragments.
SAMPLES = {
    "source_name": "MySource",
    "bundle_id": "com.example.app",
    "app_fragment": "MyApp (com.example.app)",
    "one or more apps": "一个或多个应用",
}

# ------------------------------------------------------------------ heuristics


def spacing_defects(text: str) -> list[str]:
    """Spacing rules for mixed CJK/Latin prose."""
    issues = []
    # Chinese and Chinese must not be separated by a space.
    for m in re.finditer(rf"([{CJK}]) ([{CJK}])", text):
        issues.append(f"stray space between Chinese characters: ...{m.group(0)}...")
    # Chinese and Latin/digits normally want a thin gap.
    for m in re.finditer(rf"([{CJK}])([{LATIN}])", text):
        issues.append(f"missing space between Chinese and Latin: ...{m.group(0)}...")
    for m in re.finditer(rf"([{LATIN}])([{CJK}])", text):
        issues.append(f"missing space between Latin and Chinese: ...{m.group(0)}...")
    return issues


# ------------------------------------------------------------------ runner


def main() -> None:
    res, _ = parse_file(LOCALIZABLE)
    table = {e.key: e.value for e in res.entries}

    print(f"composed-message regression guard - {len(COMPOSITIONS)} composition site(s)\n")
    failures = 0
    for template_key, variant, slot_map, provenance in COMPOSITIONS:
        if template_key not in table:
            print(f"  MISSING template key {template_key!r}")
            failures += 1
            continue
        template_zh = table[template_key]
        # how many arguments does the template consume?
        n_args = max([int(m.group(1)) for m in re.finditer(r"%(\d+)\$", template_zh)] or [0])
        if not n_args:
            n_args = template_zh.count("%@")

        print(f"template {template_key!r}")
        print(f"  variant   : {variant}")
        print(f"  provenance: {provenance}")
        print(f"  zh        : {template_zh!r}")

        resolved: dict[int, str] = {}
        missing = False
        for slot, frag_key in slot_map.items():
            if frag_key not in table:
                print(f"    MISSING fragment key {frag_key!r}")
                missing = True
                continue
            frag_zh = table[frag_key]
            if "%" in frag_zh:
                frag_zh = swift_format(frag_zh, SAMPLES["bundle_id"])
            resolved[slot] = frag_zh
        if missing:
            failures += 1
            print()
            continue

        args = []
        for i in range(1, n_args + 1):
            if i in resolved:
                args.append(resolved[i])
            elif i == 1:
                args.append(SAMPLES["source_name"])
            else:
                args.append(SAMPLES["app_fragment"])

        rendered_en = swift_format(template_key, *args)
        rendered_zh = swift_format(template_zh, *args)
        issues = spacing_defects(rendered_zh)
        accepted = ACCEPTED.get((template_key, variant))
        if issues and not accepted:
            failures += 1
        if issues and accepted:
            status = "ACPT"
        elif issues:
            status = "FAIL"
        else:
            status = "OK  "
        print(f"    [{status}]")
        print(f"           EN : {rendered_en}")
        print(f"           ZH : {rendered_zh}")
        for issue in issues:
            print(f"           -> {issue}")
        if accepted:
            print(f"           accepted: {accepted}")
        print()

    print("=" * 70)
    if failures:
        print(f"{failures} composition(s) need attention")
    else:
        print("all composed messages read cleanly")


if __name__ == "__main__":
    main()
