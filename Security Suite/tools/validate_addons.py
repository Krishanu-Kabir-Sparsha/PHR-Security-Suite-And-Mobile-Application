#!/usr/bin/env python3
"""Static validation for the security suite addons.

This exists because the build environment has no Odoo runtime and no
PostgreSQL, so the real test suites cannot be executed here (see
docs/VERIFICATION_STATUS.md). It catches the class of defect that would
otherwise sit undetected until someone installs the module: syntax errors,
malformed XML, manifest files pointing at things that do not exist, ACL rows
referencing models that were never declared, and Odoo 17-and-earlier view
syntax that Odoo 18 rejects.

It is NOT a substitute for running the module against a real database.

Usage:  python3 tools/validate_addons.py [addons_dir]
Exit code 0 = clean, 1 = findings.
"""

import ast
import csv
import os
import re
import sys
import xml.etree.ElementTree as ET

# Odoo 18 removed these; leaving them in place produces load-time failures
# that are easy to introduce and tedious to trace.
FORBIDDEN_VIEW_PATTERNS = [
    (r"\battrs\s*=", "attrs= was removed in Odoo 17; use direct invisible/readonly/required"),
    (r"\bstates\s*=\s*\"", "states= on view nodes was removed in Odoo 17"),
    (r"<tree\b", "<tree> was renamed to <list> in Odoo 18"),
    (r"</tree>", "</tree> was renamed to </list> in Odoo 18"),
]

findings = []


def fail(module, message):
    findings.append("[%s] %s" % (module, message))


def declared_models(module_path, concrete_only=False):
    """Model names declared in the module's python.

    With concrete_only, returns only models this module *originates*: abstract
    and transient models are skipped (no table, so no ACL rows), and so are
    extensions of models owned by another module (a class whose _name also
    appears in its own _inherit, or which has _inherit and no _name) — their
    ACLs belong to the module that defined them.
    """
    names = set()
    for root, _dirs, files in os.walk(module_path):
        for filename in files:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(root, filename)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except SyntaxError as exc:
                fail(os.path.basename(module_path), "syntax error in %s: %s" % (path, exc))
                continue
            # Models declared under tests/ are fixtures. They exist only while
            # a test runs, are never reachable by a user, and correctly ship no
            # ACL rows -- OCA base_tier_validation's tier.validation.tester is
            # the canonical example. Counting them produced "model has no
            # ir.model.access.csv entry" findings that can never be actioned.
            # Parsed above regardless, so a syntax error in a test still fails.
            rel = os.path.relpath(path, module_path).replace(os.sep, "/")
            if rel == "tests" or rel.startswith("tests/"):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                attrs = {}
                for stmt in node.body:
                    if not isinstance(stmt, ast.Assign):
                        continue
                    for target in stmt.targets:
                        if not isinstance(target, ast.Name):
                            continue
                        if target.id not in ("_name", "_inherit"):
                            continue
                        value = stmt.value
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            attrs[target.id] = [value.value]
                        elif isinstance(value, (ast.List, ast.Tuple)):
                            attrs[target.id] = [
                                e.value for e in value.elts
                                if isinstance(e, ast.Constant) and isinstance(e.value, str)
                            ]
                name_list = attrs.get("_name", [])
                inherit_list = attrs.get("_inherit", [])
                if not concrete_only:
                    names.update(name_list)
                    names.update(inherit_list)
                    continue
                base_names = {b.attr for b in node.bases if isinstance(b, ast.Attribute)}
                if "AbstractModel" in base_names or "TransientModel" in base_names:
                    continue
                if not name_list:
                    continue  # pure extension
                model_name = name_list[0]
                if model_name in inherit_list:
                    continue  # extension expressed as _name + _inherit
                names.add(model_name)
    return names


def check_module(module_path):
    module = os.path.basename(module_path)
    manifest_path = os.path.join(module_path, "__manifest__.py")
    if not os.path.exists(manifest_path):
        fail(module, "missing __manifest__.py")
        return

    # 1. Manifest parses and is a dict.
    try:
        manifest = ast.literal_eval(open(manifest_path, encoding="utf-8").read())
    except Exception as exc:  # noqa: BLE001 - report anything malformed
        fail(module, "manifest is not a literal dict: %s" % exc)
        return
    for key in ("name", "version", "license", "depends", "data"):
        if key not in manifest:
            fail(module, "manifest missing required key '%s'" % key)
    version = manifest.get("version", "")
    if not str(version).startswith("18.0."):
        fail(module, "manifest version '%s' is not an Odoo 18 version string" % version)

    # 2. Every python file compiles, and uses no removed Odoo APIs.
    for root, _dirs, files in os.walk(module_path):
        for filename in files:
            if filename.endswith(".py"):
                path = os.path.join(root, filename)
                content = open(path, encoding="utf-8").read()
                try:
                    ast.parse(content)
                except SyntaxError as exc:
                    fail(module, "syntax error in %s: %s" % (path, exc))
                # The states= field attribute was removed in Odoo 17. A field
                # carrying it loads but the conditional readonly silently does
                # nothing, which on a security model means a field the user was
                # supposed to be unable to edit.
                if re.search(r"\n\s+states\s*=\s*\{", content):
                    fail(
                        module,
                        "%s uses the states= field attribute, removed in Odoo 17"
                        % os.path.relpath(path, module_path),
                    )

    # 3. Every declared data file exists, is well-formed, and uses Odoo 18 syntax.
    for rel in manifest.get("data", []):
        path = os.path.join(module_path, rel)
        if not os.path.exists(path):
            fail(module, "manifest data file does not exist: %s" % rel)
            continue
        if rel.endswith(".xml"):
            try:
                ET.parse(path)
            except ET.ParseError as exc:
                fail(module, "malformed XML in %s: %s" % (rel, exc))
                continue
            content = open(path, encoding="utf-8").read()
            for pattern, reason in FORBIDDEN_VIEW_PATTERNS:
                if re.search(pattern, content):
                    fail(module, "%s: %s" % (rel, reason))

    # 4. ACL rows reference models the module actually declares.
    acl_path = os.path.join(module_path, "security", "ir.model.access.csv")
    if not os.path.exists(acl_path):
        # A module that originates concrete models but ships no ACL file leaves
        # those models reachable only by superuser, which is a security defect,
        # not a convenience.
        orphans = declared_models(module_path, concrete_only=True)
        if orphans:
            fail(
                module,
                "declares model(s) %s but has no security/ir.model.access.csv"
                % ", ".join(sorted(orphans)),
            )
    if os.path.exists(acl_path):
        models = declared_models(module_path)
        concrete = declared_models(module_path, concrete_only=True)
        with open(acl_path, encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            fail(module, "ir.model.access.csv is empty")
        for row in rows:
            ref = (row.get("model_id:id") or "").strip()
            # A row may legitimately reference a model owned by another module,
            # written "<module>.model_<name>" -- granting a role read access to
            # base.model_ir_model, for instance. That is valid Odoo and cannot
            # be checked against this module's own declarations, so validate the
            # shape and move on rather than reporting it as malformed.
            if "." in ref:
                _owner, _sep, local = ref.partition(".")
                if not local.startswith("model_"):
                    fail(
                        module,
                        "ACL row '%s' has a malformed model reference" % row.get("id"),
                    )
                continue
            if not ref.startswith("model_"):
                fail(module, "ACL row '%s' has a malformed model reference" % row.get("id"))
                continue
            technical = ref[len("model_"):].replace("_", ".")
            # model_role_plaza_model_access -> role.plaza.model.access, so compare
            # loosely: the dotted-to-underscored form of a declared model must match.
            candidates = {name.replace(".", "_") for name in models}
            if ref[len("model_"):] not in candidates:
                fail(
                    module,
                    "ACL row '%s' references model '%s' which this module does not declare"
                    % (row.get("id"), technical),
                )
        # Every non-abstract declared model should have at least one ACL row.
        # Only own-module references count towards coverage; a cross-module row
        # grants access to somebody else's model and says nothing about ours.
        covered = {
            ref[len("model_"):]
            for ref in ((row.get("model_id:id") or "").strip() for row in rows)
            if ref.startswith("model_")
        }
        for name in concrete:
            if name.startswith("sec.") and "." in name[4:]:
                pass  # our own models, still need ACLs
            if name.replace(".", "_") not in covered:
                fail(module, "model '%s' has no ir.model.access.csv entry" % name)

    # 5. Structural expectations from the master build prompt, Section 4.
    if not os.path.exists(os.path.join(module_path, "__init__.py")):
        fail(module, "missing __init__.py")
    if not os.path.isdir(os.path.join(module_path, "tests")):
        fail(module, "missing tests/ directory")
    elif not [
        f for f in os.listdir(os.path.join(module_path, "tests"))
        if f.startswith("test_")
    ]:
        fail(module, "tests/ directory contains no test_*.py files")
    if not os.path.exists(os.path.join(module_path, "README.rst")):
        fail(module, "missing README.rst")


def _default_addons_dir():
    """Where the modules live when no directory is given on the command line.

    The repository root, i.e. this script's parent's parent, because the
    modules sit beside ``tools/`` rather than under an ``addons/`` subdirectory.
    An earlier version appended "addons", which stopped resolving when the tree
    was reorganised -- and failed in the least helpful way available: the
    directory simply did not exist, so the script reported "no addon modules
    found" and exited non-zero. That reads as "the modules are broken" rather
    than "you pointed me at nothing", which is why it went unnoticed.

    ``addons/`` is still honoured when it is actually there, so a checkout
    using the old layout keeps working.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    legacy = os.path.join(root, "addons")
    return legacy if os.path.isdir(legacy) else root


def main():
    addons_dir = sys.argv[1] if len(sys.argv) > 1 else _default_addons_dir()
    if not os.path.isdir(addons_dir):
        print("Not a directory: %s" % addons_dir)
        return 2
    # A directory is a candidate module if it carries either marker. Requiring
    # both would let a module that lost its manifest slip through silently --
    # which is finding #1 below and worth keeping. Requiring neither means
    # sibling directories such as docs/ and tools/ get reported as broken
    # modules, which is noise that trains people to ignore the output.
    modules = sorted(
        os.path.join(addons_dir, name)
        for name in os.listdir(addons_dir)
        if os.path.isdir(os.path.join(addons_dir, name))
        and (
            os.path.exists(os.path.join(addons_dir, name, "__manifest__.py"))
            or os.path.exists(os.path.join(addons_dir, name, "__init__.py"))
        )
    )
    if not modules:
        print("No addon modules found in %s" % addons_dir)
        return 1
    for module_path in modules:
        check_module(module_path)

    print("Validated %d module(s): %s" % (
        len(modules), ", ".join(os.path.basename(m) for m in modules)))
    if findings:
        print("\n%d finding(s):" % len(findings))
        for finding in findings:
            print("  - %s" % finding)
        return 1
    print("No findings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
