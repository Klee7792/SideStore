"""Automated translation-quality smell tests (report item H), plus honest random sampling.

Machine checks catch the mechanical failures: untranslated leftovers, values with no CJK
at all, keep-English entries that drifted, and English function words leaking into Chinese
sentences.  Sampling then gives a human-reviewable slice with a reproducible seed so the
result can be re-derived by anyone reading the report.
"""

from __future__ import annotations

import os
import random
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from strings_syntax import parse_file  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
LOCALIZABLE = os.path.join(REPO, "AltStore", "zh-Hans.lproj", "Localizable.strings")
KEEP = os.path.join(REPO, "scripts", "i18n", "keep_english.txt")

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# common English function words that indicate an untranslated fragment in Chinese prose
_EN_WORDS = re.compile(
    r"\b(the|and|for|with|from|this|that|please|would|should|could|your|you|are|has|have"
    r"|been|will|can|not|when|then|there|their|them|they|which|while|before|after|during"
    r"|because|about|into|only|also|than|does|did|using|used|must|may|more|other|some|such"
    r"|these|those|here|where|how|what|why|all|any|each|every|per|via|now|new|old)\b",
    re.IGNORECASE,
)


def load_keep() -> set[str]:
    out = set()
    with open(KEEP, encoding="utf-8") as fh:
        for line in fh:
            s = line.rstrip("\n").rstrip("\r")
            if not s.strip() or s.lstrip().startswith("#"):
                continue
            out.add(s.lstrip())
    return out


def main() -> None:
    res, _ = parse_file(LOCALIZABLE)
    keep = load_keep()
    entries = res.entries

    print(f"entries={len(entries)}  keep_english={len(keep)}")

    # ---- 1. values with no CJK at all that are NOT on the keep-English list -------
    no_cjk = [
        e for e in entries
        if not _CJK.search(e.value) and e.key not in keep
    ]
    print(f"\n[H1] entries with NO Chinese characters and not whitelisted: {len(no_cjk)}")
    for e in no_cjk:
        print(f"   line {e.line}: {e.key!r}  ->  {e.value!r}")

    # ---- 2. value identical to key but not whitelisted ---------------------------
    identical = [
        e for e in entries if e.key == e.value and e.key not in keep
    ]
    print(f"\n[H2] value == key but key not in keep_english.txt: {len(identical)}")
    for e in identical[:60]:
        print(f"   line {e.line}: {e.key!r}")

    # ---- 3. keep-English entries whose value drifted away from the key -----------
    drifted = [e for e in entries if e.key in keep and e.value != e.key]
    print(f"\n[H3] keep-English entries whose rendered value != key: {len(drifted)}")
    for e in drifted:
        print(f"   line {e.line}: key={e.key!r} value={e.value!r}")

    # ---- 4. keep-English entries missing from the strings file -------------------
    present = {e.key for e in entries}
    missing_keep = sorted(k for k in keep if k not in present)
    print(f"\n[H4] keep-English keys absent from Localizable.strings: {len(missing_keep)}")
    for k in missing_keep:
        print(f"   {k!r}")

    # ---- 5. English function words surviving inside Chinese values ---------------
    leaking = []
    for e in entries:
        if not _CJK.search(e.value):
            continue
        hits = sorted({m.group(0).lower() for m in _EN_WORDS.finditer(e.value)})
        if hits:
            leaking.append((e, hits))
    print(f"\n[H5] Chinese values still containing English function words: {len(leaking)}")
    for e, hits in leaking:
        print(f"   line {e.line}: {hits}")
        print(f"        key  : {e.key!r}")
        print(f"        value: {e.value!r}")

    # ---- 6. same Chinese value used for visibly different English keys -----------
    by_value: dict[str, list] = defaultdict(list)
    for e in entries:
        if e.value == e.key:
            continue
        by_value[e.value].append(e)
    collisions = [(v, es) for v, es in by_value.items() if len(es) > 1]
    print(f"\n[H6] distinct English keys collapsed onto one Chinese value: {len(collisions)}")
    for v, es in collisions:
        print(f"   {v!r}")
        for e in es:
            print(f"        line {e.line}: {e.key!r}")

    # ---- 7. reproducible random sample for human review --------------------------
    reviewable = [e for e in entries if e.key != e.value]
    rng = random.Random(20250112)
    sample = rng.sample(reviewable, 45)
    print("\n" + "=" * 78)
    print(f"[H7] RANDOM SAMPLE (seed=20250112, {len(sample)} of {len(reviewable)} translated entries)")
    print("=" * 78)
    for i, e in enumerate(sample, 1):
        print(f"\n[{i:02d}] Localizable.strings:{e.line}")
        print(f"    EN: {e.key}")
        print(f"    ZH: {e.value}")


if __name__ == "__main__":
    main()
