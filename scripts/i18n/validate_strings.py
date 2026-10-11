#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate the SideStore zh-Hans localization output.

Runs five independent gates and prints a single verdict:

1. Placeholders in every translation match the placeholders of its key
   (same count, same conversion, explicit indices form 1..n).
2. ``.strings`` files are syntactically valid: every entry ends with ';'
   and quotes are balanced / escaped.
3. The ``Bundle.Info.activeBundleVersion`` change still renders the same
   string it did before (static key + String(format:) is equivalent).
4. ``AltStore/Info.plist`` is well-formed XML, declares exactly
   ``CFBundleLocalizations == ["en", "zh-Hans"]`` and is otherwise identical to
   the pre-localization snapshot in :data:`EXPECTED_INFO_PLIST`.
5. No file outside the agreed scope was touched
   (``Dependencies/``, other targets, ``project.pbxproj``).

Exit code is 0 when every gate passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import plistlib
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR: Path = Path(__file__).resolve().parent
REPO_ROOT: Path = SCRIPT_DIR.parents[1]

sys.path.insert(0, str(SCRIPT_DIR))
import extract_strings as ex  # noqa: E402  (path bootstrap must come first)

LOCALIZABLE: Path = REPO_ROOT / "AltStore" / "zh-Hans.lproj" / "Localizable.strings"
INFOPLIST_STRINGS: Path = REPO_ROOT / "AltStore" / "zh-Hans.lproj" / "InfoPlist.strings"
INFO_PLIST: Path = REPO_ROOT / "AltStore" / "Info.plist"

#: Entries that are allowed to keep their English value verbatim.
KEEP_ENGLISH_FILE: Path = SCRIPT_DIR / "keep_english.txt"

#: Paths that must never be modified by this localization pass.
FORBIDDEN_PATHS: tuple[str, ...] = (
    "AltStore.xcodeproj/project.pbxproj",
    "Dependencies/",
    "AltWidget/",
    "SideBackup/",
    "xcconfigs/",
)


class Gate:
    """Accumulates pass/fail information for one quality gate."""

    def __init__(self, name: str) -> None:
        self.name: str = name
        self.problems: list[str] = []

    def fail(self, message: str) -> None:
        """Record one problem."""
        self.problems.append(message)

    @property
    def passed(self) -> bool:
        """True when no problem was recorded."""
        return not self.problems


# --------------------------------------------------------------------------------------
# Gate 1 - placeholder parity
# --------------------------------------------------------------------------------------

#: A positional reference such as %1$@.
POSITIONAL_RE: re.Pattern[str] = re.compile(r"%(?P<argnum>\d+)\$")


def gate_placeholders() -> Gate:
    """Every translation must accept exactly the arguments its key accepts."""
    gate: Gate = Gate("1. Placeholder parity (key vs translation)")
    entries, _report = ex.extract_all()
    translations, keep_english, malformed = ex.load_translations()

    for row in malformed:
        gate.fail(f"unparsable translation row: {row}")

    for entry in entries:
        key: str = entry.key
        translated: str | None = translations.get(key)
        if translated is None:
            gate.fail(f"missing translation for key {key!r} ({entry.origin}:{entry.line})")
            continue
        if key in keep_english:
            if translated != key:
                gate.fail(f"key in keep_english.txt must be verbatim: {key!r}")
            continue
        if translated == key:
            gate.fail(
                f"translation identical to key and not listed in keep_english.txt: {key!r}"
            )
            continue

        key_signature: tuple[tuple[int, str], ...] = ex.placeholder_signature(key)
        value_signature: tuple[tuple[int, str], ...] = ex.placeholder_signature(translated)
        if key_signature != value_signature:
            gate.fail(
                "placeholder mismatch {0!r}: key={1} value={2}".format(
                    key,
                    [c for _, c in key_signature],
                    [c for _, c in value_signature],
                )
            )

        if key_signature:
            indices: list[int] = [int(m.group("argnum")) for m in POSITIONAL_RE.finditer(translated)]
            expected: list[int] = list(range(1, len(key_signature) + 1))
            if indices and sorted(indices) != expected:
                gate.fail(
                    f"positional placeholders must be 1..{len(key_signature)}: {key!r}"
                )

    for stale in keep_english:
        if stale not in {entry.key for entry in entries}:
            gate.fail(f"keep_english.txt entry is not an extracted key: {stale!r}")

    return gate


# --------------------------------------------------------------------------------------
# Gate 2 - .strings syntax
# --------------------------------------------------------------------------------------

#: one entry: optional /* comment */ blocks then "key" = "value";
ENTRY_RE: re.Pattern[str] = re.compile(
    r'(?P<comment>(?:/\*.*?\*/\s*)*)'
    r'"(?P<key>(?:[^"\\]|\\.)*)"\s*=\s*"(?P<value>(?:[^"\\]|\\.)*)"\s*;',
    re.DOTALL,
)


def strip_comments(text: str) -> str:
    """Remove /* ... */ comments so quoted text inside comments is ignored."""
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def parse_strings_file(text: str) -> tuple[list[tuple[str, str]], str | None]:
    """Tokenize a NeXTSTEP-style ``.strings`` file.

    Returns ``(entries, error)``. ``error`` is ``None`` when the whole file
    parsed cleanly. The grammar we enforce is exactly what Foundation accepts:
    a sequence of ``"key" = "value";`` pairs, optionally preceded by
    ``/* ... */`` or ``// ...`` comments, with ``\\`` and ``"`` escapes.
    """
    entries: list[tuple[str, str]] = []
    index: int = 0
    length: int = len(text)

    def skip_ws_and_comments() -> str | None:
        nonlocal index
        while index < length:
            char: str = text[index]
            if char in " \t\r\n":
                index += 1
            elif text.startswith("/*", index):
                end: int = text.find("*/", index + 2)
                if end == -1:
                    return "unterminated /* comment"
                index = end + 2
            elif text.startswith("//", index):
                end = text.find("\n", index)
                index = length if end == -1 else end
            else:
                return None
        return None

    def read_quoted() -> tuple[str | None, str | None]:
        nonlocal index
        if index >= length or text[index] != '"':
            return None, f"expected a quoted string at offset {index}"
        index += 1
        chunks: list[str] = []
        while index < length:
            char = text[index]
            if char == "\\":
                if index + 1 >= length:
                    return None, "trailing backslash in string"
                chunks.append(text[index : index + 2])
                index += 2
                continue
            if char == '"':
                index += 1
                return "".join(chunks), None
            if char == "\n":
                return None, "unescaped newline inside a quoted string"
            chunks.append(char)
            index += 1
        return None, "unterminated quoted string"

    while index < length:
        error: str | None = skip_ws_and_comments()
        if error:
            return entries, error
        if index >= length:
            break

        key, error = read_quoted()
        if error:
            return entries, error
        error = skip_ws_and_comments()
        if error:
            return entries, error
        if index >= length or text[index] != "=":
            return entries, f"expected '=' after key at offset {index}"
        index += 1
        error = skip_ws_and_comments()
        if error:
            return entries, error
        value, error = read_quoted()
        if error:
            return entries, error
        error = skip_ws_and_comments()
        if error:
            return entries, error
        if index >= length or text[index] != ";":
            return entries, f"expected ';' after value at offset {index}"
        index += 1
        entries.append((key, value))

    return entries, None


def unescape_strings_value(value: str) -> str:
    """Decode the escapes used inside a ``.strings`` quoted literal."""
    return (
        value.replace("\\\\", "\\")
        .replace('\\"', '"')
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\r", "\r")
    )


def gate_strings_syntax() -> Gate:
    """Check that both .strings files parse and that keys are unique."""
    gate: Gate = Gate("2. .strings syntax")
    for path in (LOCALIZABLE, INFOPLIST_STRINGS):
        if not path.exists():
            gate.fail(f"missing file: {path}")
            continue

        raw: bytes = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            gate.fail(f"{path.name}: file must be UTF-8 without BOM")
        try:
            text: str = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            gate.fail(f"{path.name}: not valid UTF-8 ({error})")
            continue

        entries, error = parse_strings_file(text)
        if error:
            gate.fail(f"{path.name}: {error}")
            continue

        keys: list[str] = [key for key, _value in entries]
        duplicates: list[str] = sorted({k for k in keys if keys.count(k) > 1})
        for duplicate in duplicates:
            gate.fail(f"{path.name}: duplicate key {duplicate!r}")

        # Every entry must be terminated (parse_strings_file guarantees this),
        # and no raw, unescaped quote may survive inside a value.
        for key, value in entries:
            if key.endswith("\\") or value.endswith("\\"):
                gate.fail(f"{path.name}: entry ends with a dangling escape: {key!r}")

        print(f"   {path.name}: {len(entries)} entries")

        if path is LOCALIZABLE:
            # Cross-check the rendered file against a fresh extraction.
            expected_keys: set[str] = {entry.key for entry in ex.extract_all()[0]}
            rendered_keys: set[str] = {unescape_strings_value(key) for key, _v in entries}
            for missing_key in sorted(expected_keys - rendered_keys):
                gate.fail(f"key missing from Localizable.strings: {missing_key!r}")
            for extra_key in sorted(rendered_keys - expected_keys):
                gate.fail(f"stale key in Localizable.strings: {extra_key!r}")
    return gate


# --------------------------------------------------------------------------------------
# Gate 3 - Bundle+AltStore.swift behaviour
# --------------------------------------------------------------------------------------


#: Minimal NSString-style format specifier (enough for this project's copy).
NS_SPEC_RE: re.Pattern[str] = re.compile(
    r"%(?:(?P<argnum>\d+)\$)?"
    r"(?P<flags>[-+0#]*)"
    r"(?P<width>\d+)?"
    r"(?:\.(?P<precision>\d+))?"
    r"(?P<length>ll|l|h|q|z|j|t)?"
    r"(?P<conversion>[@diouxXeEfFgGcCsSpaA%])"
)


def ns_format(format_string: str, *args: object) -> str:
    """Render a format string the way ``String(format:)`` would.

    Python's ``%`` operator rejects ``%@``, so this tiny subset exists purely
    to prove the old and the new Swift code path render the same text.
    """
    out: list[str] = []
    index: int = 0
    next_positional: int = 0
    while index < len(format_string):
        char: str = format_string[index]
        if char != "%":
            out.append(char)
            index += 1
            continue
        match: re.Match[str] | None = NS_SPEC_RE.match(format_string, index)
        if match is None:
            out.append(char)
            index += 1
            continue

        conversion: str = match.group("conversion")
        if conversion == "%":
            out.append("%")
            index = match.end()
            continue

        argnum: str | None = match.group("argnum")
        if argnum is not None:
            value: object = args[int(argnum) - 1]
        else:
            value = args[next_positional]
            next_positional += 1

        if conversion in {"d", "i"}:
            out.append("%d" % int(value))  # noqa: UP031
        elif conversion == "f":
            precision: str = match.group("precision") or "6"
            out.append("%.*f" % (int(precision), float(value)))  # noqa: UP031
        else:
            out.append(str(value))
        index = match.end()
    return "".join(out)


def gate_bundle_version() -> Gate:
    """Verify the static-key rewrite is behaviourally identical."""
    gate: Gate = Gate("3. Bundle+AltStore.swift version formatting")
    source: Path = REPO_ROOT / "Shared" / "Extensions" / "Bundle+AltStore.swift"
    if not source.exists():
        gate.fail(f"missing file: {source}")
        return gate

    text: str = source.read_text(encoding="utf-8")
    if 'NSLocalizedString(String(format: "Version %@%@", version, build)' in text:
        gate.fail("dynamic NSLocalizedString key is still present")
    if 'NSLocalizedString("Version %1$@%2$@", comment: "SideStore Version")' not in text:
        gate.fail('static key "Version %1$@%2$@" not found')
    if "String(format: format, version, build)" not in text:
        gate.fail("String(format:) call not found")

    # Old behaviour: the key was already interpolated before the lookup, so
    # the visible text was literally "Version <v><b>".
    # New behaviour: a static key is localized and String(format:) fills it in.
    old_render: str = ns_format("Version %@%@", "0.6.4", " (123)")
    new_render: str = ns_format("Version %1$@%2$@", "0.6.4", " (123)")
    if old_render != new_render or old_render != "Version 0.6.4 (123)":
        gate.fail(f"format strings render differently: {old_render!r} vs {new_render!r}")

    translations, _keep, _malformed = ex.load_translations()
    chinese_format: str | None = translations.get("Version %1$@%2$@")
    if chinese_format is None:
        gate.fail('missing translation for "Version %1$@%2$@"')
    elif ex.placeholder_signature(chinese_format) != ex.placeholder_signature("Version %1$@%2$@"):
        gate.fail("Chinese version format has different placeholders")
    elif ns_format(chinese_format, "0.6.4", " (123)") != "版本 0.6.4 (123)":
        gate.fail("Chinese version renders unexpected text")
    return gate


# --------------------------------------------------------------------------------------
# Gate 4 - Info.plist
# --------------------------------------------------------------------------------------

#: Snapshot of ``AltStore/Info.plist``'s top level *before* the localization
#: pass added ``CFBundleLocalizations``. The gate compares the file against
#: this snapshot plus that one array, so the verdict does not depend on the
#: shape of the git history. (The previous implementation diffed the file
#: against git; once Info.plist was committed the diff was empty and the whole
#: file was reported as "added", which permanently polluted IS_PASS.)
#:
#: If a future, legitimate change edits Info.plist, update this snapshot in the
#: same commit - that is exactly the change-scope guarantee this gate provides.
EXPECTED_INFO_PLIST: dict[str, object] = {
    "ALTAnisetteURL": "https://ani.sidestore.io",
    "CFBundleDevelopmentRegion": "$(DEVELOPMENT_LANGUAGE)",
    "CFBundleDocumentTypes": [
        {
            "CFBundleTypeIconFiles": [],
            "CFBundleTypeName": "iOS App",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "Alternate",
            "LSItemContentTypes": ["com.apple.itunes.ipa"],
        }
    ],
    "CFBundleExecutable": "$(EXECUTABLE_NAME)",
    "CFBundleIcons": {
        "CFBundlePrimaryIcon": {
            "NSAppIconComplementingColorNames": ["GradientTop", "GradientBottom"]
        }
    },
    "CFBundleIdentifier": "$(PRODUCT_BUNDLE_IDENTIFIER)",
    "CFBundleInfoDictionaryVersion": "6.0",
    "CFBundleName": "$(PRODUCT_NAME)",
    "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": "$(MARKETING_VERSION)",
    "CFBundleURLTypes": [
        {
            "CFBundleTypeRole": "Editor",
            "CFBundleURLName": "SideStore General",
            "CFBundleURLSchemes": ["sidestore"],
        },
        {
            "CFBundleTypeRole": "Editor",
            "CFBundleURLName": "SideStore Backup",
            "CFBundleURLSchemes": ["sidestore-$(PRODUCT_BUNDLE_IDENTIFIER)"],
        },
    ],
    "CFBundleVersion": "$(CURRENT_PROJECT_VERSION)",
    "INIntentsSupported": ["RefreshAllIntent", "ViewAppIntent"],
    "LSApplicationQueriesSchemes": [
        "sidestore-com.SideStore.SideStore",
        "sidestore-com.SideStore.SideStore.Beta",
        "localdevvpn",
    ],
    "LSRequiresIPhoneOS": True,
    "LSSupportsOpeningDocumentsInPlace": True,
    "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True},
    "NSBonjourServices": [
        "_altserver._tcp",
        "_remotepairing-pairable-host._tcp",
        "_remotepairing-manual-pairing._tcp",
        "_services._dns-sd._udp",
        "_airplay._tcp",
        "_raop._tcp",
        "_sftp-ssh._tcp",
        "_sleep-proxy._udp",
        "_ssh._tcp",
        "_apple-mobdev2._tcp",
        "_asquic._udp",
        "_companion-link._tcp",
        "_meshcop._udp",
        "_remotepairing._tcp",
        "_rp-tunnel._tcp",
        "_srpl-tls._tcp",
        "_trel._udp",
        "_http._tcp",
        "_https._tcp",
        "_smb._tcp",
        "_afpovertcp._tcp",
        "_printer._tcp",
        "_ipp._tcp",
        "_ipps._tcp",
        "_scanner._tcp",
        "_daap._tcp",
        "_dpap._tcp",
        "_airport._tcp",
        "_homekit._tcp",
        "_hap._tcp",
        "_touch-able._tcp",
        "_spotify-connect._tcp",
        "_googlecast._tcp",
        "_device-info._tcp",
        "_workstation._tcp",
        "_rfb._tcp",
        "_net-assistant._udp",
        "_rdlink._tcp",
        "_stikpairprobe._tcp",
        "_webdav._tcp",
        "_webdavs._tcp",
        "_ftp._tcp",
        "_telnet._tcp",
        "_coap._udp",
        "_coaps._udp",
        "_mqtt._tcp",
        "_adb._tcp",
        "_airdrop._tcp",
        "_sidecar._tcp",
        "_sonos._tcp",
        "_plex._tcp",
        "_amzn-alexa._tcp",
        "_home-assistant._tcp",
        "_rtsp._tcp",
        "_sip._udp",
        "_sip._tcp",
        "_h323._tcp",
        "_h323._udp",
        "_ws._tcp",
        "_wss._tcp",
        "_remoted._tcp",
        "_coredevice._tcp",
        "_appletv-v2._tcp",
        "_apple-mobdev._tcp",
        "_jitstreamer._tcp",
        "_matter._tcp",
        "_matterc._udp",
        "_airprint._tcp",
        "_vnc._tcp",
    ],
    "NSLocalNetworkUsageDescription": (
        "SideStore can use local network access to discover Bonjour (mDNS) "
        "services on your network. This is not required for core functionality."
    ),
    "NSLocationAlwaysAndWhenInUseUsageDescription": (
        "SideStore uses location updates to keep background operations active."
    ),
    "NSLocationWhenInUseUsageDescription": (
        "SideStore uses location updates to keep background operations active."
    ),
    "NSUserActivityTypes": ["RefreshAllIntent", "ViewAppIntent"],
    "OSLogPreferences": {
        "com.SideStore.SideStore": {
            "AltJIT": {"Level": {"Enable": "Info", "Persist": "Info"}},
            "Main": {"Level": {"Enable": "Info", "Persist": "Info"}},
            "Sideload": {"Level": {"Enable": "Info", "Persist": "Info"}},
        }
    },
    "UIApplicationSceneManifest": {
        "UIApplicationSupportsMultipleScenes": True,
        "UISceneConfigurations": {
            "UIWindowSceneSessionRoleApplication": [
                {
                    "UILaunchStoryboardName": "LaunchScreen",
                    "UISceneConfigurationName": "Default Configuration",
                    "UISceneDelegateClassName": "$(PRODUCT_MODULE_NAME).SceneDelegate",
                    "UISceneStoryboardFile": "Main",
                }
            ]
        },
    },
    "UIBackgroundModes": ["audio", "fetch", "location", "remote-notification", "processing"],
    "UIFileSharingEnabled": True,
    "UILaunchStoryboardName": "LaunchScreen",
    "UIMainStoryboardFile": "Main",
    "UIRequiredDeviceCapabilities": ["armv7"],
    "UIStatusBarTintParameters": {
        "UINavigationBar": {"Style": "UIBarStyleDefault", "Translucent": False}
    },
    "UISupportedInterfaceOrientations": ["UIInterfaceOrientationPortrait"],
    "UISupportedInterfaceOrientations~ipad": [
        "UIInterfaceOrientationPortrait",
        "UIInterfaceOrientationPortraitUpsideDown",
        "UIInterfaceOrientationLandscapeLeft",
        "UIInterfaceOrientationLandscapeRight",
    ],
    "UTImportedTypeDeclarations": [
        {
            "UTTypeConformsTo": ["public.data"],
            "UTTypeDescription": "iOS App",
            "UTTypeIconFiles": [],
            "UTTypeIdentifier": "com.apple.itunes.ipa",
            "UTTypeTagSpecification": {
                "public.filename-extension": "ipa",
                "public.mime-type": "application/x-ios-app",
            },
        },
        {
            "UTTypeConformsTo": ["com.apple.plist"],
            "UTTypeDescription": "Mobile Device Pairing",
            "UTTypeIconFiles": [],
            "UTTypeIdentifier": "org.sidestore.mobiledevicepairing",
            "UTTypeTagSpecification": {
                "public.filename-extension": ["mobiledevicepairing", "mobiledevicepair"]
            },
        },
    ],
}

#: The localization pass may only add this one key on top of the snapshot.
EXPECTED_INFO_PLIST_LOCALIZATIONS: list[str] = ["en", "zh-Hans"]


def gate_info_plist() -> Gate:
    """Info.plist must be valid XML and only gain CFBundleLocalizations."""
    gate: Gate = Gate("4. AltStore/Info.plist")
    if not INFO_PLIST.exists():
        gate.fail(f"missing file: {INFO_PLIST}")
        return gate

    with INFO_PLIST.open("rb") as handle:
        try:
            data: dict[str, object] = plistlib.load(handle)
        except Exception as error:  # noqa: BLE001 - report any parse failure
            gate.fail(f"could not parse Info.plist: {error}")
            return gate

    localizations = data.get("CFBundleLocalizations")
    if localizations != EXPECTED_INFO_PLIST_LOCALIZATIONS:
        gate.fail(
            f"CFBundleLocalizations is {localizations!r}, "
            f"expected {EXPECTED_INFO_PLIST_LOCALIZATIONS!r}"
        )

    expected: dict[str, object] = dict(EXPECTED_INFO_PLIST)
    expected["CFBundleLocalizations"] = list(EXPECTED_INFO_PLIST_LOCALIZATIONS)
    if data != expected:
        for key in sorted(set(data) | set(expected)):
            if data.get(key) != expected.get(key):
                gate.fail(
                    f"Info.plist {key!r} does not match the expected snapshot "
                    f"(update EXPECTED_INFO_PLIST if this change is intended)"
                )
    return gate


def _git(*args: str) -> str:
    """Run a git command and return its stdout (empty string on failure)."""
    try:
        result: subprocess.CompletedProcess = subprocess.run(
            ["git", *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return result.stdout if result.returncode == 0 else ""


def _git_diff_names(path: str) -> list[str]:
    """Return changed paths for ``path`` as reported by git."""
    output: str = _git("diff", "--name-only", "--", path)
    untracked: str = _git("ls-files", "--others", "--exclude-standard", "--", path)
    names: list[str] = [line.strip() for line in output.splitlines() if line.strip()]
    names.extend(line.strip() for line in untracked.splitlines() if line.strip())
    return names


def _git_diff_text(path: str) -> str:
    """Return the unified diff for ``path`` (empty when git is unavailable)."""
    output: str = _git("diff", "--", path)
    if output.strip():
        return output
    # Untracked files have no diff; treat the whole file as added.
    if _git("rev-parse", "--is-inside-work-tree"):
        text: str = (REPO_ROOT / path).read_text(encoding="utf-8")
        return "\n".join("+" + line for line in text.splitlines())
    return ""


# --------------------------------------------------------------------------------------
# Gate 5 - scope of the change set
# --------------------------------------------------------------------------------------


def gate_change_scope() -> Gate:
    """Only in-scope files may be part of the localization change set."""
    gate: Gate = Gate("5. Change scope")
    changed: list[str] = []
    changed.extend(line.strip() for line in _git("diff", "--name-only").splitlines() if line.strip())
    changed.extend(
        line.strip()
        for line in _git("ls-files", "--others", "--exclude-standard").splitlines()
        if line.strip()
    )

    if not changed:
        print("   (git reports no changes - skipping)")
        return gate

    allowed_prefixes: tuple[str, ...] = (
        "AltStore/",
        "SideStore/",
        "Shared/",
        "scripts/i18n/",
        "docs/",
        # The fork's own CI workflows are maintained independently of the
        # localization pass and must not block it.
        ".github/workflows/",
    )
    # `.gitignore` needs whitelisting: the repo ignores *.md and *.txt globally,
    # so the glossary and the keep-English list would otherwise never reach a
    # fresh clone. `AGENTS.md` is the fork's governance document, which the
    # maintainer edits outside of any localization change.
    allowed_files: tuple[str, ...] = (".gitignore", "AGENTS.md")

    for path in changed:
        path = path.replace("\\", "/")
        if any(path.startswith(prefix) for prefix in FORBIDDEN_PATHS):
            gate.fail(f"out-of-scope file changed: {path}")
            continue
        if path in allowed_files:
            continue
        if not any(path.startswith(prefix) for prefix in allowed_prefixes):
            gate.fail(f"unexpected file changed: {path}")

    if ".gitignore" in changed:
        # The only sanctioned .gitignore changes are whitelisting the files this
        # localization pass needs in version control and ignoring the local
        # build output directory that must never be committed. Membership (not
        # exact equality) is checked so the rule keeps working when the entries
        # land in separate commits.
        diff_text: str = _git_diff_text(".gitignore")
        added_lines: list[str] = [
            line[1:].strip()
            for line in diff_text.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
        removed_lines: list[str] = [
            line[1:].strip()
            for line in diff_text.splitlines()
            if line.startswith("-") and not line.startswith("---")
        ]
        if removed_lines:
            gate.fail(f".gitignore lost lines: {removed_lines}")
        sanctioned_gitignore_additions: frozenset[str] = frozenset(
            {
                "!docs/i18n-glossary.md",
                "!scripts/i18n/keep_english.txt",
                "build1/",
            }
        )
        unsanctioned: list[str] = [
            line for line in added_lines if line not in sanctioned_gitignore_additions
        ]
        if unsanctioned:
            gate.fail(f"unexpected .gitignore additions: {unsanctioned}")

    print(f"   {len(changed)} changed path(s):")
    for path in changed:
        print(f"     - {path}")
    return gate


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run every gate and print the verdict."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    gates: list[Gate] = [
        gate_placeholders(),
        gate_strings_syntax(),
        gate_bundle_version(),
        gate_info_plist(),
        gate_change_scope(),
    ]

    for gate in gates:
        status: str = "PASS" if gate.passed else "FAIL"
        print(f"[{status}] {gate.name}")
        for problem in gate.problems:
            print(f"        ! {problem}")

    overall: bool = all(gate.passed for gate in gates)
    print()
    print(f"IS_PASS: {'YES' if overall else 'NO'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
