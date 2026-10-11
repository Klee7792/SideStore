"""QA acceptance runner for the SideStore zh-Hans localization drop.

Covers report items A (syntax), B (placeholder signature), C (encoding),
D3 (mini String(format:) behaviour), E (Info.plist), F (InfoPlist.strings).

Nothing here imports anything from `scripts/i18n/validate_strings.py` or
`scripts/i18n/extract_strings.py` - those are the implementer's own artifacts and are
treated as untrusted input.
"""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mini_format import format as swift_format  # noqa: E402
from placeholders import analyze  # noqa: E402
from strings_syntax import parse_file  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
ZH_DIR = os.path.join(REPO, "AltStore", "zh-Hans.lproj")
LOCALIZABLE = os.path.join(ZH_DIR, "Localizable.strings")
INFOPLIST_STRINGS = os.path.join(ZH_DIR, "InfoPlist.strings")
APP_INFO_PLIST = os.path.join(REPO, "AltStore", "Info.plist")

RESULTS: list[tuple[str, str, list[str]]] = []


def emit(section: str, verdict: str, lines: list[str] | None = None) -> None:
    RESULTS.append((section, verdict, lines or []))
    print(f"\n{'=' * 72}\n[{verdict}] {section}\n{'=' * 72}")
    for line in lines or []:
        print("  - " + line)


# ------------------------------------------------------------------ A. syntax


def check_syntax() -> None:
    errors: list[str] = []
    for path in (LOCALIZABLE, INFOPLIST_STRINGS):
        name = os.path.basename(path)
        # pass 1: strict, quoted strings only (what plutil accepts)
        res, raw = parse_file(path, allow_bare=False)
        if res.errors:
            errors.append(f"{name}: {len(res.errors)} syntax error(s)")
            errors.extend(res.errors[:20])
        else:
            print(f"  {name}: {len(res.entries)} entries parsed cleanly")

        if res.duplicate_keys:
            dup_sorted = sorted(res.duplicate_keys, key=lambda t: t[1])
            errors.append(f"{name}: {len(dup_sorted)} DUPLICATE KEY(S)")
            for key, first, second in dup_sorted[:25]:
                errors.append(
                    f'    duplicate {name}:{first} and :{second} -> {key!r}'
                )
        # Every statement must terminate with ';' - the parser enforces this, but record
        # it explicitly because the requirement calls it out.
        if not res.errors:
            pass
    emit("A. .strings syntax / duplicate keys", "FAIL" if errors else "PASS",
         errors or ["no syntax errors; no duplicate keys; every pair terminated by ';'"])


# --------------------------------------------------------- B. placeholders


# Evidence-backed exemptions: entries my printf analysis flags but which are provably
# NOT passed through String(format:), so the '%' is rendered literally and no argument
# is consumed.  Each entry cites the call site that proves it.
MANUAL_EXEMPTIONS = {
    (
        "Switching to Resigned IPA prioritizes install speed (~40% faster) by packaging "
        "an uncompressed IPA for fast transfer, but temporarily uses additional disk "
        "space during packaging."
    ): (
        "SideStore/Views/Settings/Advanced/UserCustomizations/UserCustomizationsView.swift"
        ":493 is `Text(\"...\")` - SwiftUI Text does not interpret printf specifiers, so "
        "the '%' in \"~40% faster\" is literal and no argument is consumed. English is "
        "identically unaffected. NOT a defect."
    ),
}


def check_placeholders() -> None:
    res, _ = parse_file(LOCALIZABLE)
    errors: list[str] = []
    warns: list[str] = []
    exempt: list[str] = []
    checked = 0
    for e in res.entries:
        if "%" not in e.key and "%" not in e.value:
            continue
        checked += 1
        note = MANUAL_EXEMPTIONS.get(e.key)
        cr = analyze(e.key, e.value)
        loc = f"Localizable.strings:{e.line}"
        cr_errors = [] if note and note else cr.errors
        for p in cr_errors:
            errors.append(f"{loc}  key={e.key!r}\n      value={e.value!r}\n      -> {p}")
        for p in cr.warnings:
            warns.append(f"{loc}  key={e.key!r}\n      value={e.value!r}\n      -> {p}")
        if note:
            exempt.append(f"{loc}\n      key={e.key[:80]!r}\n      WHY: {note}")
    print(f"  entries containing a '%': {checked}; hard errors={len(errors)}; "
          f"warnings={len(warns)}; evidence-backed exemptions={len(exempt)}")
    print("\n  ---- HARD ERRORS ----")
    for x in errors:
        print("  * " + x)
    print("\n  ---- WARNINGS (deliberate reorder etc.) ----")
    for x in warns:
        print("  * " + x)
    print("\n  ---- EXEMPT (proven non-format call sites) ----")
    for x in exempt:
        print("  * " + x)
    emit("B. placeholder signature consistency",
         "FAIL" if errors else ("WARN" if warns else "PASS"),
         errors or warns or exempt or
         [f"all {checked} placeholder-bearing entries match"])


# ------------------------------------------------------------------ C. encoding


def check_encoding() -> None:
    lines: list[str] = []
    bad = False
    for path in sorted(
        [os.path.join(ZH_DIR, f) for f in os.listdir(ZH_DIR)]
    ):
        with open(path, "rb") as fh:
            raw = fh.read()
        name = os.path.basename(path)
        bom = raw.startswith(b"\xef\xbb\xbf")
        try:
            raw.decode("utf-8")
            utf8 = True
        except UnicodeDecodeError as exc:
            utf8 = False
            lines.append(f"{name}: NOT valid UTF-8 -> {exc}")
        crlf = raw.count(b"\r\n")
        lone_lf = raw.count(b"\n") - crlf
        lines.append(
            f"{name}: {len(raw)} bytes, UTF-8={'yes' if utf8 else 'NO'}, "
            f"BOM={'PRESENT (fatal)' if bom else 'absent (good)'}, "
            f"CRLF={crlf}, lone-LF={lone_lf}, sha256={hashlib.sha256(raw).hexdigest()[:12]}"
        )
        if bom:
            lines.append(f"    {name}: UTF-8 BOM detected - iOS fails to resolve the first key")
            bad = True
        if not utf8:
            bad = True
    emit("C. encoding (UTF-8, no BOM)", "FAIL" if bad else "PASS", lines)


# ------------------------------------------------------- D3. mini String(format:)


def check_version_format() -> None:
    results: list[str] = []
    ok = True
    key = "Version %1$@%2$@"
    res, _ = parse_file(LOCALIZABLE)
    by_key = {e.key: e.value for e in res.entries}

    if key not in by_key:
        ok = False
        results.append(f"MISSING key {key!r} in Localizable.strings")
    else:
        zh_value = by_key[key]
        results.append(f"found key {key!r} -> zh-Hans value {zh_value!r}")
        # the two arguments passed by String(format:format, version, build)
        for tv, tb, expected_en, expected_zh in [
            ("0.6.4", " (123)", "Version 0.6.4 (123)", "版本 0.6.4 (123)"),
            ("1.0", " (42)", "Version 1.0 (42)", "版本 1.0 (42)"),
        ]:
            got_en = swift_format(key, tv, tb)
            got_zh = swift_format(zh_value, tv, tb)
            tag = "OK " if got_en == expected_en else "BAD"
            if got_en != expected_en:
                ok = False
            results.append(f"  [{tag}] EN  {key!r} + ({tv!r},{tb!r}) -> {got_en!r} (expected {expected_en!r})")
            tag = "OK " if got_zh == expected_zh else "BAD"
            if got_zh != expected_zh:
                ok = False
            results.append(f"  [{tag}] ZH  {zh_value!r} + ({tv!r},{tb!r}) -> {got_zh!r} (expected {expected_zh!r})")
    emit("D3. mini String(format:) reproduction", "FAIL" if not ok else "PASS", results)


# ------------------------------------------------------------------ E. Info.plist


def check_info_plist() -> None:
    lines: list[str] = []
    bad = False
    with open(APP_INFO_PLIST, "rb") as fh:
        plist = plistlib.load(fh)
    lines.append(f"plistlib parsed OK, top-level keys={len(plist)}")

    locs = plist.get("CFBundleLocalizations")
    if locs is None:
        bad = True
        lines.append("CFBundleLocalizations: MISSING")
    elif locs != ["en", "zh-Hans"]:
        bad = True
        lines.append(f"CFBundleLocalizations: {locs!r} (expected ['en', 'zh-Hans'])")
    else:
        lines.append(f"CFBundleLocalizations: {locs!r} OK")

    for k in (
        "NSLocalNetworkUsageDescription",
        "NSLocationWhenInUseUsageDescription",
        "NSLocationAlwaysAndWhenInUseUsageDescription",
    ):
        present = k in plist
        lines.append(f"{k}: {'present' if present else 'MISSING'} = {plist.get(k)!r}")
        if not present:
            bad = True

    lines.append(f"CFBundleName={plist.get('CFBundleName')!r}")
    lines.append(f"CFBundleDisplayName={plist.get('CFBundleDisplayName')!r}")
    emit("E. Info.plist validity / minimal diff", "FAIL" if bad else "PASS", lines)


# ------------------------------------------------------- F. InfoPlist.strings


def check_infoplist_strings() -> None:
    res, _ = parse_file(INFOPLIST_STRINGS)
    with open(APP_INFO_PLIST, "rb") as fh:
        plist = plistlib.load(fh)
    lines: list[str] = []
    bad = False
    lines.append(f"{len(res.entries)} entries in InfoPlist.strings")
    for e in res.entries:
        present = e.key in plist
        lines.append(
            f"  line {e.line}: {e.key!r} -> {e.value!r}  "
            f"[{'OK: exists in Info.plist' if present else 'BAD: NOT in Info.plist'}]"
        )
        if not present:
            bad = True
    emit("F. InfoPlist.strings keys vs Info.plist", "FAIL" if bad else "PASS", lines)


def main() -> None:
    check_syntax()
    check_placeholders()
    check_encoding()
    check_version_format()
    check_info_plist()
    check_infoplist_strings()
    print("\n\n==== SUMMARY ====")
    for section, verdict, _ in RESULTS:
        print(f"  {verdict:5s}  {section}")


if __name__ == "__main__":
    main()
