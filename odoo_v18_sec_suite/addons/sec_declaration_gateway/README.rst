==========================================
Security Suite - Declaration Gateway
==========================================

Blocking Unified Declaration / NDA+ sign-off, plus the Written/Oral instruction
classification and its documentation requirement.

Requirements covered
====================

============  ==========================================================
Requirement   Where
============  ==========================================================
BRD FR-1.1    ``declaration.version`` / ``declaration.signoff``
BRD FR-1.2    ``sec.instruction.mixin.instruction_type``
BRD FR-1.3    ``_compute_documentation_complete`` + submit gate
BRD FR-1.4    ``_raise_anomaly_out_of_band`` on blocked submission
PRD US-1.1    ``tests/test_declaration_gateway.py``
PRD US-1.2    ``tests/test_instruction_documentation.py``
PRD US-1.3    same file, ``test_blocked_submission_raises_anomaly_alert``
============  ==========================================================

Legal scope boundary
====================

This module captures acceptance. It does not contain declaration wording, and
must not. The shipped ``declaration_version_placeholder`` record is in DRAFT with
``approved_by_legal`` unset and contains no declaration language. Legal Counsel
supplies the text, records their name, and publishes. BRD Section 9 risk 4
specifically warns that the family-liability clause in the source instructions is
unlikely to be enforceable and must not be deployed as drafted.

The gate is dormant until a version is published, so installing this module does
not lock anybody out.

Three implementation decisions worth knowing
============================================

**The gate is a server-side dispatch check, not a modal.** It lives in
``ir.http._dispatch``. A modal rendered by the web client can be dismissed from
the browser console; a dispatch gate cannot. This is stricter than the PRD's
wording ("full-screen modal") but satisfies its actual criterion, that no
dashboard route is reachable before acceptance.

**Administrators are not exempt.** Only ``base.user_root`` is, because exempting
it is necessary for cron and module installation. Exempting real administrators
would exempt precisely the population the BRD is worried about.

**The missing-documentation alert is written on a separate cursor.** A blocked
submission rolls back. An alert written on the same cursor would roll back with
it, so every blocked attempt would vanish — the opposite of FR-1.4. See
``_raise_anomaly_out_of_band``.

Known limitations
=================

* The ``ir.http._dispatch`` override redirects JSON-RPC calls as well as page
  loads. A user mid-session when a new declaration is published may see a failed
  request before being bounced to the declaration page on next navigation.
  Acceptable, but worth a nicer client-side handler later.
* ``sec.edit.request`` targets a record by model name and integer id, because
  there is nothing to freeze yet. P1-4 replaces this with a real reference.
