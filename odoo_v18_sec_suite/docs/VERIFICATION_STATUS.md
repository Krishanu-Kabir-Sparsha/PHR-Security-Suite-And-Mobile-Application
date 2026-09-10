# Verification Status — read this before trusting any "done" marker

The master build prompt forbids marking a task done on the strength of
"this should work". This file records exactly what level of verification each
kind of claim in this repository currently rests on, so nobody has to guess.

## The build environment has no Odoo and no PostgreSQL

Checked in session 1:

- `python3 -c "import odoo"` — not installed; `pip install odoo==18.0` finds no
  distribution (Odoo is not published to PyPI under that name).
- No `psql`, no `postgres`, no `/usr/lib/postgresql`.

**Consequence:** the `TransactionCase` test suites in `addons/*/tests/` have been
*written* but have **never been executed**. They are specifications of expected
behaviour, not passing tests. No task may be marked `done` in `PROGRESS.md` on
the basis of these tests until they have actually run green against a real
Odoo 18 database.

## What has actually been verified

| Check | Tool | Status |
|---|---|---|
| Python files parse | `ast.parse` via `tools/validate_addons.py` | Passing |
| XML data files well-formed | `ElementTree` via the same validator | Passing |
| No Odoo-17-and-earlier view syntax (`<tree>`, `attrs=`, `states=`) | regex scan in the validator | Passing |
| Manifest declares every data file, and every declared file exists | validator | Passing |
| ACL rows reference models the module declares; every model has an ACL row | validator | Passing |
| Seed role catalog respects bounds, unique codes, one Nuclear Key, all three tiers, no intra-role SoD breach | generator self-check, re-asserted in `test_plaza_role_catalog.py` and `test_sod_checker.py` | Passing as a static data check |
| OCA `auditlog` / `base_tier_validation` exist and are released on the `18.0` branch | git inspection of upstream | Passing |

## What is therefore still open

Every task in `PROGRESS.md` marked `code-complete (untested)` needs a run of:

```bash
odoo -d <db> -i sec_plaza_rbac --test-enable --test-tags /sec_plaza_rbac --stop-after-init
```

on an environment that has Odoo 18 and PostgreSQL. Until that happens, treat
Phase 0 as engineering-complete but not verification-complete, and do not begin
Phase 2 authorisation work on the assumption that the Phase 0 foundations hold.
