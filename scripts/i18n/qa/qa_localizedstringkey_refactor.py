"""QA guard for the SwiftUI `String` -> `LocalizedStringKey` refactor.

Why this needs a guard
----------------------
The refactor changes helper signatures from `title: String` to `title: LocalizedStringKey`
so that `Text(title)` actually localises (a `String` argument to `Text()` does NOT look up
Localizable.strings; only `LocalizedStringKey` does).

The danger: **Swift will implicitly convert a string *literal* to `LocalizedStringKey`, but
NOT a `String` variable.** So every call site is fine as long as it passes a literal or a
value already typed `LocalizedStringKey`. A single call site passing a `String` variable
(especially one coming from a model, e.g. `app.name`) is a **compile error** that nobody
on Windows can catch, because this project cannot be compiled here.

This script statically inspects every call site of every changed helper and classifies the
argument:
    LITERAL          -> "..." or interpolation  -> compiles, localises
    TYPED_KEY        -> declared `LocalizedStringKey` (or Optional thereof) -> compiles
    STRING_TYPED     -> declared `String` -> COMPILE ERROR
    UNKNOWN          -> cannot resolve the declaration -> needs human eyes

`UNKNOWN` is reported loudly rather than assumed safe: the whole point is that we cannot
compile, so an unresolved type is a risk, not a pass.
"""

from __future__ import annotations

import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

# Helper name -> the parameter positions that changed type to LocalizedStringKey.
CHANGED = {
    "sectionHeader": {1},                      # sectionHeader(title:icon:) / sectionHeader(_ title:)
    "headerFieldRow": {1},                     # headerFieldRow(title:headerKey:text:placeholder:)
    "infoTokenRow": {1, 3},                    # title:...:subtitle:
    "detailRow": {1},                          # detailRow(title:value:)
    "detailRowWithCopy": {1},                  # detailRowWithCopy(title:value:isCopied:)
    "toggleRow": {1, 2},                       # toggleRow(title:subtitle:isOn:) / toggleRow(title:isOn:)
    "textFieldRow": {1, 2},                    # title:subtitle:...
    "stepToggle": {1},                         # stepToggle(_ title:step:)
}

STRING_TYPE = re.compile(r"^(?:var|let)\s+(\w+)\s*(?::\s*([^=]+?))?\s*=")


def swift_files() -> list[str]:
    out = []
    for root in ("AltStore", "SideStore", "Shared"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(REPO, root)):
            dirnames[:] = [d for d in dirnames if d != "Dependencies"]
            for fn in filenames:
                if fn.endswith(".swift"):
                    out.append(os.path.join(dirpath, fn))
    return sorted(out)


def strip_comments_and_strings(src: str) -> str:
    """Blank out string contents so we can find call sites without matching their text."""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and src[i + 1: i + 2] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == "/" and src[i + 1: i + 2] == "*":
            i += 2
            while i < n and src[i: i + 2] != "*/":
                i += 1
            i += 2
            continue
        if c == '"':
            if src[i: i + 3] == '"""':
                end = src.find('"""', i + 3)
                i = (end + 3) if end != -1 else n
                out.append('""')
                continue
            out.append('"LIT"')
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def split_args(argstr: str) -> list[str]:
    args, depth, cur, i, n = [], 0, [], 0, len(argstr)
    while i < n:
        c = argstr[i]
        if c == '"':
            # keep literals intact so we can classify them
            cur.append('"')
            i += 1
            while i < n:
                if argstr[i] == "\\":
                    cur.append(argstr[i: i + 2])
                    i += 2
                    continue
                if argstr[i] == '"':
                    cur.append('"')
                    i += 1
                    break
                cur.append(argstr[i])
                i += 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            args.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    if "".join(cur).strip():
        args.append("".join(cur))
    return args


def foreach_bindings(code: str) -> dict[str, str]:
    """`ForEach(pipelineStepToggles...) { index, entry in` -> {'entry': 'pipelineStepToggles'}"""
    out: dict[str, str] = {}
    for m in re.finditer(r"ForEach\(\s*(?:Array\(\s*)?([A-Za-z_]\w*)", code):
        coll = m.group(1)
        # skip Swift stdlib collections that are not project declarations
        if coll in ("Array", "stride", "zip"):
            continue
        tail = code[m.end(): m.end() + 400]
        cb = re.search(r"\{\s*(?:(\w+)\s*,\s*)?(\w+)\s+in\b", tail)
        if cb:
            out[cb.group(2)] = coll
    return out


def resolve_member(obj, prop, path, lineno, stripped, decls):
    """Resolve the declared type of `obj.prop` where obj comes from a ForEach binding."""
    code = stripped[path]
    bindings = foreach_bindings(code)
    coll = bindings.get(obj)
    if coll is None:
        return None
    # find the declaration of the collection: `private let coll: [(name: LocalizedStringKey, step: X)]`
    m = re.search(
        rf"\b(?:let|var)\s+{re.escape(coll)}\s*(?::\s*([^=\n]+?))?\s*=", code
    )
    if not m:
        return None
    typ = (m.group(1) or "").strip()
    if "[" not in typ:
        return None
    # tuple members inside the array literal
    for tm in re.finditer(r"(\w+)\s*:\s*([A-Za-z_][\w.]*)", typ):
        if tm.group(1) == prop:
            return tm.group(2)
    # fall back: the array literal may be `[(name: "A", step: .x), ...]`
    lit = code[m.end():]
    lm = re.search(rf"\b{re.escape(prop)}\s*:\s*([A-Za-z_][\w.]*)", lit)
    return lm.group(1) if lm else None


def main() -> None:
    files = swift_files()
    stripped: dict[str, str] = {}
    decls: dict[str, dict[str, str]] = {}
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        stripped[path] = strip_comments_and_strings(src)
        decls[path] = {}
        for m in STRING_TYPE.finditer(src):
            decls[path][m.group(1)] = (m.group(2) or "").strip()

    problems: list[str] = []
    checked = 0

    for path, code in stripped.items():
        rel = os.path.relpath(path, REPO).replace("\\", "/")
        lines = code.split("\n")
        for lineno, line in enumerate(lines, 1):
            for fn, positions in CHANGED.items():
                for m in re.finditer(rf"(?<![\w.]){re.escape(fn)}\s*\(", line):
                    if re.match(r"\s*(?:private\s+)?func\s", lines[lineno - 1]):
                        continue
                    start = m.end() - 1
                    depth = 0
                    end = None
                    for j in range(start, len(line)):
                        if line[j] == "(":
                            depth += 1
                        elif line[j] == ")":
                            depth -= 1
                            if depth == 0:
                                end = j
                                break
                    if end is None:
                        continue
                    args = split_args(line[start + 1: end])
                    for pos in positions:
                        if pos - 1 >= len(args):
                            continue
                        arg = args[pos - 1].strip()
                        labelled = re.match(r"^(\w+)\s*:\s*(.+)$", arg)
                        target = labelled.group(2).strip() if labelled else arg
                        if target.startswith('"'):
                            checked += 1
                            continue  # literal -> implicit conversion, compiles

                        # member access, e.g. entry.name coming from a ForEach over a
                        # tuple array whose element type we just changed
                        member = re.match(r"^(\w+)\.(\w+)$", target)
                        if member:
                            typ = resolve_member(
                                member.group(1), member.group(2), path, lineno, stripped, decls
                            )
                            checked += 1
                            if typ is None:
                                problems.append(
                                    f"{rel}:{lineno}  {fn}()  arg#{pos} -> `{target}`: "
                                    f"could not resolve member type - NEEDS HUMAN CHECK"
                                )
                            elif "LocalizedStringKey" in typ:
                                continue
                            elif "String" in typ:
                                problems.append(
                                    f"{rel}:{lineno}  {fn}()  arg#{pos} -> `{target}` is "
                                    f"`{typ}`: COMPILE ERROR - String does not implicitly "
                                    f"convert to LocalizedStringKey"
                                )
                            else:
                                problems.append(
                                    f"{rel}:{lineno}  {fn}()  arg#{pos} -> `{target}` is "
                                    f"`{typ}` - verify type"
                                )
                            continue

                        ident = re.match(r"^(\w+)$", target)
                        if not ident:
                            problems.append(
                                f"{rel}:{lineno}  {fn}()  arg#{pos} is an expression, not a "
                                f"literal: {target!r}"
                            )
                            continue
                        name = ident.group(1)
                        typ = None
                        for k in range(lineno - 1, -1, -1):
                            for dm in re.finditer(
                                rf"\b(?:let|var)\s+{re.escape(name)}\s*(?::\s*([^=\n]+?))?\s*=",
                                lines[k],
                            ):
                                typ = (dm.group(1) or "").strip()
                                break
                            if typ is not None:
                                break
                        checked += 1
                        if typ is None:
                            problems.append(
                                f"{rel}:{lineno}  {fn}()  arg#{pos} -> `{name}`: could not "
                                f"resolve declaration - NEEDS HUMAN CHECK"
                            )
                        elif "LocalizedStringKey" in typ:
                            continue
                        elif "String" in typ:
                            problems.append(
                                f"{rel}:{lineno}  {fn}()  arg#{pos} -> `{name}` is declared "
                                f"`{typ}`: COMPILE ERROR - String does not implicitly "
                                f"convert to LocalizedStringKey"
                            )
                        else:
                            problems.append(
                                f"{rel}:{lineno}  {fn}()  arg#{pos} -> `{name}` is declared "
                                f"`{typ}` - verify type"
                            )

    print(f"call-site arguments checked: {checked}")
    print(f"problems: {len(problems)}")
    for p in problems:
        print("  * " + p)
    if problems:
        sys.exit(1)
    print("every call site of the changed helpers passes a literal or a LocalizedStringKey")


if __name__ == "__main__":
    main()
