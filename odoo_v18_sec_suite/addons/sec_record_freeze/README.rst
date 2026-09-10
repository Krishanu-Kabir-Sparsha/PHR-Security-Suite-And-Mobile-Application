====================================
Security Suite - Record Freeze
====================================

Blocks edits to Sales Orders, Purchase Orders and Accounting entries once they
reach Confirmed / Done / Posted, for every role including administrators.

Requirements covered
====================

============  ==========================================================
Requirement   Where
============  ==========================================================
BRD FR-3.1    ``sec.record.freeze.mixin.write`` / ``unlink``
BRD FR-3.2    ORM half here; database half is P1-5 (not yet built)
BRD FR-3.4    ``_freeze_unlock_authorised`` — returns False until P2-8
PRD US-3.1    ``tests/test_record_freeze.py``
============  ==========================================================

The one decision to read before deploying
=========================================

**Freezing is field-selective.** A blanket ``write()`` block on confirmed orders
breaks Odoo: the system writes to confirmed documents constantly for delivery
status, invoice status, delivered quantities, reconciliation and chatter. An ERP
where you cannot deliver goods against a confirmed order is not a secure ERP,
it is an uninstalled module.

Each ``sec.freeze.rule`` therefore names the fields that carry business meaning
— counterparty, dates, amounts, lines, taxes — and freezes those. Everything
else keeps moving.

The consequence, stated plainly: **a field left off a protected list is a field
somebody can change on a confirmed record.** Review the six shipped lists
against your own configuration, especially if you have custom fields. This is
the highest-value item in the monthly audit of this module.

Line models are covered
=======================

``sale.order.line``, ``purchase.order.line`` and ``account.move.line`` freeze
from their parent's state. Without this, being blocked from editing an order's
total is meaningless — you edit the line and the total recomputes.

What this does not protect against
==================================

Raw SQL. Someone with a ``psql`` prompt writes straight to the table and none of
this code executes. P1-5 adds database-level constraints, which raise the bar
further but do not stop a superuser (BRD Section 8.2 is candid about this).
The real answer is BRD Section 9 risk 1: remove direct production database
access. Until that is done, this is a strong control against people using Odoo
and no control at all against people with the database.

``sudo()`` and ``uid=1`` do **not** bypass the freeze; both are covered by tests.

Database-level enforcement (P1-5)
=================================

A PL/pgSQL trigger on each in-scope table refuses UPDATE of protected columns
and DELETE of rows in a frozen state, so a write that never passes through Odoo
is still refused: a ``psql`` session, a stray script, a reporting tool with
write credentials, or a bug in our own ORM override.

Same two constraints as the ORM layer, for the same reasons: it compares OLD and
NEW on protected columns only (using IS DISTINCT FROM, so a recompute writing an
unchanged value passes), and it guards only real stored columns — one2many
fields such as ``order_line`` are not columns and stay protected at the ORM
layer, with their child rows guarded by the line tables' own triggers.

Triggers are generated from the rule configuration by
``sec.freeze.rule.sync_all_triggers()``, called from the post-init hook, on
upgrade, and whenever a rule changes. ``migrations/18.0.1.1.0/
reference_guard_function.sql`` is a rendered copy for DBA review; do not apply
it by hand.

``verify_triggers()`` reports any expected trigger that is absent and raises a
critical anomaly. Dropping a trigger is a deliberate act, so a missing one is a
finding. Wire this into the P4-2 reconciliation job.

**It does not stop a PostgreSQL superuser**, who can disable or drop the
trigger. BRD Section 8.2 says as much. The answers remain P0-1 (remove standing
production access) and P4-1 (replicate evidence outside the DBA's control).

**Uninstalling drops every trigger** via the uninstall hook. Leaving them behind
would leave the database enforcing rules whose configuration no longer exists.

Back-end stream locks (P1-6)
============================

A different, stronger control from the confirm-state freeze. The freeze stops
edits to **confirmed** records; draft work carries on. A stream lock stops
**everything** in that stream — create, write and delete, in any state — for
everyone except a Super Administrator. It is the switch you pull during a
suspected incident or a forensic window.

Sales, Purchase and Accounting lock independently, as US-3.2 requires.

Before pulling it, understand the consequence the UI also states: **automated
jobs stop too.** Scheduled invoicing, delivery processing and anything else
touching the locked stream will fail while the lock is engaged. That is the
point of a lockdown, not a defect, but it is not a routine setting.

Every toggle captures actor, UTC timestamp, before/after state, source IP and a
mandatory written reason, in an append-only log. The ``locked`` field cannot be
written directly — that would skip the reason, the confirmation and the history.

On WebAuthn and honesty
-----------------------

US-3.2 requires WebAuthn confirmation of a toggle. WebAuthn does not exist until
P2-2. Rather than fake a confirmation, each log entry carries
``strongly_authenticated``, currently False, so the audit trail distinguishes
toggles that were cryptographically confirmed from those that were not. Asserting
True here would put a false claim into the evidence record, which is worse than
recording the gap.

Set ``sec_record_freeze.allow_toggle_without_webauthn`` to ``False`` the moment
``sec_webauthn_auth`` is deployed; toggles are then refused without a real
assertion.

Operational safety valve
========================

Set ``enforcement_active = False`` on a rule rather than uninstalling the module.
Doing so raises a **critical** anomaly alert and is logged. P1-6 adds the
Super Admin lock toggles for Sales and Purchase on top of this.
