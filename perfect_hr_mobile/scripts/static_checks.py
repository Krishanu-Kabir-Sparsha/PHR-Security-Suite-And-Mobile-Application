#!/usr/bin/env python3
"""Toolchain-free static checks for the Perfect HR Mobile Dart sources.

This is NOT a substitute for `flutter analyze`. It exists because parts of this
codebase were authored in an environment without a Dart SDK, and a subset of
compile errors is mechanically detectable from source text alone:

  1. Unbalanced braces, parentheses and brackets.
  2. Named arguments passed to our own classes that the constructor does not
     declare — a very common error when a widget API is edited after its call
     sites were written.
  3. Classes that `implements` one of our own interfaces without declaring
     every member of it.
  4. `part` directives whose generated file is absent (expected before
     build_runner runs, but worth listing).
  5. Imports of project files that do not exist.
  6. Symbols referenced from `package:perfect_hr_mobile/...` in tests that are
     not declared anywhere in lib/.

Run:  python3 scripts/static_checks.py
Exit: 0 when clean, 1 when findings.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "lib"
TEST = ROOT / "test"

findings: list[str] = []
notes: list[str] = []


def dart_files(*roots: Path) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if root.exists():
            out.extend(sorted(root.rglob("*.dart")))
    return out


def strip_noise(text: str) -> str:
    """Removes comments and string literals so delimiters inside them do not
    confuse the balance check."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    text = re.sub(r"'''.*?'''", "''", text, flags=re.S)
    text = re.sub(r'""".*?"""', '""', text, flags=re.S)
    # Single-line strings, honouring escapes.
    text = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", text)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', text)
    # Angle brackets are tracked as nesting so that generics like
    # Map<String, Object?> do not split on their comma. But `=>`, `>=`, `<=`
    # and `->` also contain them, and counting those pushed the depth negative
    # — which made nested named arguments inside a lambda look top-level and
    # produced three false positives. Neutralise the operators first.
    for operator in ("=>", ">=", "<=", "->"):
        text = text.replace(operator, "  ")
    return text


# --- 1. Delimiter balance ---------------------------------------------------

def check_balance(path: Path, text: str) -> None:
    clean = strip_noise(text)
    pairs = {"}": "{", ")": "(", "]": "["}
    stack: list[str] = []
    for ch in clean:
        if ch in "{([":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack[-1] != pairs[ch]:
                findings.append(f"{rel(path)}: unbalanced '{ch}'")
                return
            stack.pop()
    if stack:
        findings.append(
            f"{rel(path)}: {len(stack)} unclosed delimiter(s): {''.join(stack)}"
        )


# --- 2. Named arguments against our own constructors -----------------------

CLASS_RE = re.compile(
    r"^(?:abstract\s+|final\s+|sealed\s+|base\s+|interface\s+)*class\s+(\w+)",
    re.M,
)


def collect_constructors(files: list[Path]) -> dict[str, set[str]]:
    """Maps ClassName -> set of accepted named parameter names.

    Deliberately permissive: a class whose constructors cannot be parsed is
    recorded as accepting anything (None), so this check produces no false
    positives on syntax it does not understand.
    """
    accepted: dict[str, set[str] | None] = {}
    for path in files:
        text = strip_noise(path.read_text(encoding="utf-8"))
        for match in CLASS_RE.finditer(text):
            name = match.group(1)
            body = extract_body(text, match.end())
            if body is None:
                accepted[name] = None
                continue
            params: set[str] = set()
            parsed_any = False
            # Any constructor: `ClassName(` or `ClassName.named(`
            for ctor in re.finditer(
                rf"(?:const\s+)?{re.escape(name)}(?:\.\w+)?\s*\(", body
            ):
                args = extract_parens(body, ctor.end() - 1)
                if args is None:
                    continue
                parsed_any = True
                params |= named_params(args)
            # Field declarations feed `super.x` style forwarding in subclasses.
            if not parsed_any:
                accepted.setdefault(name, None)
            else:
                prev = accepted.get(name)
                accepted[name] = params if prev in (None, set()) else (prev | params)
    return {k: v for k, v in accepted.items() if v is not None}


def named_params(args: str) -> set[str]:
    """Extracts named parameter identifiers from a parameter list."""
    names: set[str] = set()
    brace = args.find("{")
    if brace == -1:
        return names
    depth = 0
    end = -1
    for i in range(brace, len(args)):
        if args[i] == "{":
            depth += 1
        elif args[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return names
    block = args[brace + 1 : end]
    for part in split_top_level(block):
        part = part.strip()
        if not part:
            continue
        # DOTALL: a default value may wrap onto following lines, e.g.
        #   super.userMessage =
        #       "We couldn't reach Perfect HR just now.",
        # Without re.S the strip fails and the parameter is missed entirely,
        # which produced two false positives on NetworkFailure.
        part = re.sub(r"=.*$", "", part, flags=re.S).strip()
        m = re.search(r"(\w+)$", part)
        if m:
            names.add(m.group(1))
    return names


def split_top_level(text: str) -> list[str]:
    out, depth, current = [], 0, []
    for ch in text:
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(current))
            current = []
        else:
            current.append(ch)
    out.append("".join(current))
    return out


def extract_body(text: str, from_index: int) -> str | None:
    start = text.find("{", from_index)
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
    return None


def extract_parens(text: str, open_index: int) -> str | None:
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : i]
    return None


def check_call_sites(files: list[Path], accepted: dict[str, set[str]]) -> None:
    for path in files:
        text = strip_noise(path.read_text(encoding="utf-8"))
        for name, params in accepted.items():
            if not params:
                continue
            for call in re.finditer(rf"\b{re.escape(name)}\s*\(", text):
                args = extract_parens(text, call.end() - 1)
                if args is None:
                    continue
                for part in split_top_level(args):
                    m = re.match(r"\s*(\w+)\s*:", part)
                    if not m:
                        continue
                    arg = m.group(1)
                    if arg not in params:
                        line = text[: call.start()].count("\n") + 1
                        findings.append(
                            f"{rel(path)}:{line}: {name} has no named "
                            f"parameter '{arg}' "
                            f"(accepts: {', '.join(sorted(params)) or 'none'})"
                        )


# --- 3. Interface implementation completeness ------------------------------

def check_interfaces(files: list[Path]) -> None:
    interfaces: dict[str, set[str]] = {}
    for path in files:
        text = strip_noise(path.read_text(encoding="utf-8"))
        for match in re.finditer(
            r"abstract\s+interface\s+class\s+(\w+)", text
        ):
            body = extract_body(text, match.end())
            if body is None:
                continue
            members = set(
                re.findall(r"(?:\w[\w<>,\s?]*\s+)?(?:get\s+)?(\w+)\s*(?:\(|;)", body)
            )
            keywords = {"return", "if", "for", "while", "final", "const", "get"}
            interfaces[match.group(1)] = {m for m in members if m not in keywords}

    for path in files:
        text = strip_noise(path.read_text(encoding="utf-8"))
        for match in re.finditer(r"class\s+(\w+)\s+implements\s+([\w,\s]+)", text):
            impl_name, targets = match.group(1), match.group(2)
            body = extract_body(text, match.end())
            if body is None:
                continue
            declared = set(re.findall(r"(\w+)\s*(?:\(|;)", body))
            declared |= set(re.findall(r"\bget\s+(\w+)", body))
            for target in [t.strip() for t in targets.split(",")]:
                if target not in interfaces:
                    continue
                missing = {
                    m for m in interfaces[target] if m not in declared
                }
                if missing:
                    notes.append(
                        f"{rel(path)}: {impl_name} implements {target}; "
                        f"verify member(s): {', '.join(sorted(missing))}"
                    )


# --- 4/5. part directives and project imports ------------------------------

def check_directives(files: list[Path]) -> None:
    for path in files:
        text = path.read_text(encoding="utf-8")
        for part in re.findall(r"^part\s+'([^']+)';", text, re.M):
            target = (path.parent / part).resolve()
            if not target.exists():
                notes.append(
                    f"{rel(path)}: part '{part}' absent — generated by "
                    f"build_runner; expected before code generation runs"
                )
        for imp in re.findall(r"^import\s+'([^:']+\.dart)'", text, re.M):
            target = (path.parent / imp).resolve()
            if not target.exists():
                findings.append(f"{rel(path)}: import '{imp}' does not exist")


# --- 6. Test references into lib -------------------------------------------

def check_test_imports(test_files: list[Path]) -> None:
    for path in test_files:
        text = path.read_text(encoding="utf-8")
        for imp in re.findall(
            r"package:perfect_hr_mobile/([\w/]+\.dart)", text
        ):
            if not (LIB / imp).exists():
                findings.append(f"{rel(path)}: package import lib/{imp} missing")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    lib_files = dart_files(LIB)
    test_files = dart_files(TEST)
    all_files = lib_files + test_files

    for path in all_files:
        check_balance(path, path.read_text(encoding="utf-8"))

    check_directives(all_files)
    check_test_imports(test_files)
    check_interfaces(lib_files)
    check_call_sites(all_files, collect_constructors(lib_files))

    print(f"Checked {len(lib_files)} lib and {len(test_files)} test files.\n")

    if findings:
        print(f"FINDINGS ({len(findings)}):")
        for f in findings:
            print(f"  {f}")
    else:
        print("No findings from the mechanical checks.")

    if notes:
        print(f"\nNOTES ({len(notes)}) — verify by eye:")
        for n in notes:
            print(f"  {n}")

    print(
        "\nThese checks cannot detect type errors, exhaustiveness, null "
        "safety\nor API misuse. `flutter analyze` remains mandatory."
    )
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
