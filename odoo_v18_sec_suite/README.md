# Odoo CE V18 — Advanced Security, Access Control & Immutable Audit System

Implementation of the BRD v2.0 / PRD v1.0 module suite. Built as separate Odoo
addons rather than a monolith, so each can be reviewed and tested on its own.

## Before you touch anything

Read **`PROGRESS.md`** and **`BUILD_STATE.json`** first, in full. They record
what is actually done. Then read **`docs/VERIFICATION_STATUS.md`**, which records
what "done" currently rests on — at time of writing, no test has ever been
executed, because the build environment has no Odoo and no PostgreSQL.

## Layout

```
addons/                        Odoo addon modules
  sec_plaza_rbac/              Plaza Model RBAC + SoD checker   [Phase 0, built]
docs/                          Phase 0 records and design notes
tools/validate_addons.py       Static validator; runs without Odoo
PROGRESS.md                    Human-readable continuity log
BUILD_STATE.json               Machine-readable continuity state
```

Modules still to build: `sec_declaration_gateway`, `sec_record_freeze`,
`sec_audit_locker`, `sec_override_engine`, `sec_webauthn_auth`,
`sec_surveillance_dashboard`, `sec_forensic_reporting`.

## External dependencies

Both confirmed released on the Odoo 18 branch (see
`docs/OCA_V18_COMPATIBILITY.md`); vendor them at a pinned commit rather than
branch HEAD.

| Module | Repository | Version |
|---|---|---|
| `auditlog` | `OCA/server-tools@18.0` | 18.0.2.0.9 |
| `base_tier_validation` | `OCA/server-ux@18.0` | 18.0.3.4.1 |

## Checks

```bash
python3 tools/validate_addons.py          # static, no Odoo needed

# Real verification, once an environment exists:
odoo -d <db> -i sec_plaza_rbac --test-enable --test-tags /sec_plaza_rbac --stop-after-init
```

## Scope boundary

The NDA+ / declaration legal wording, the family-liability clause, and any
employment-law language are **not** engineering deliverables (BRD Section 11,
PRD Section 5.2). `sec_declaration_gateway` will expose a configuration point
for legally-approved text; this repository does not draft it.
