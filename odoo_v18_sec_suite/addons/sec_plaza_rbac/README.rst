=====================================
Security Suite - Plaza Model RBAC
=====================================

Implements the Plaza Model role catalog, its module/field-level access matrix,
and the segregation-of-duties checker.

Requirements covered
====================

============  ==========================================================
Requirement   Where
============  ==========================================================
BRD FR-2.1    ``role.plaza_model``, bounded 10-20 active roles
BRD FR-2.2    non-standard grant guard in ``models/res_users.py``
BRD FR-2.3    ``catalog_version`` field plus mail.thread tracking
BRD FR-2.4    intra-role constraint + ``plaza.sod.scan`` cross-role scan
PRD US-2.1    ``tests/test_plaza_role_catalog.py``
PRD US-2.2    ``tests/test_sod_checker.py``
============  ==========================================================

Models
======

``role.plaza_model``
    One standardised organisational role. Carries a mandatory description, a
    backing ``res.groups`` record, an override-approval tier, and an access
    matrix.

``role.plaza_model.access``
    One line of a role's access matrix: model, CRUD permissions, restricted
    fields, and the transaction class plus capability used by the SoD checker.

``plaza.sod.scan`` / ``plaza.sod.conflict``
    A scan run and its findings. A conflict is one user who can both create and
    approve the same class of transaction through a combination of roles.

``plaza.grant.exception``
    A logged, justified, approved grant of a security group outside the Plaza
    catalog. Without one, such a grant is refused.

Design decisions worth knowing
==============================

* The 20-role ceiling is enforced at write time; the 10-role floor is a go-live
  readiness gate (``check_catalog_readiness``), because a write-time floor would
  make the first role impossible to create.
* Role-backing groups carry no ``category_id`` on purpose, so a user can hold
  several roles at once. Same-category groups render as a single-choice
  selection in Odoo, which would defeat the point of a SoD checker.
* Seed data is ``noupdate="1"``: module upgrades must never silently rewrite who
  can do what.

Known limitations
=================

* The access matrix is currently a *declaration* reviewed by the SoD checker and
  the monthly report. Generating ``ir.model.access`` and ``ir.rule`` records from
  it automatically is deferred; until then the matrix and the live ACLs are kept
  in step by review, not by code. Tracked in ``PROGRESS.md``.
* Field-level restrictions are recorded as text; enforcement via ``groups=`` on
  the target field is applied per-module in later phases.
