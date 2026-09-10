=========================
Security Suite - Core
=========================

Shared primitives used by the rest of the suite.

Provides
========

``anomaly.alert``
    The PRD anomaly alert entity: type, severity, acting user, source IP,
    target record, reason, and a review workflow requiring a mandatory note.

``anomaly.review``
    Append-only record of every triage decision: who, when, outcome, mandatory
    note, state before and after, and whether it was part of a batch. Mirrored
    to the Locker when that module is installed.

    This lives here rather than in the dashboard module deliberately. If it sat
    there, an installation without the dashboard could still mark alerts
    reviewed, silently and untraceably. Dismissing an alert is a
    security-relevant act — the System Monitor is the one person positioned to
    make an inconvenient finding disappear — so the log belongs wherever the
    alerts are.

``sec.anomaly.mixin``
    ``_raise_anomaly(...)`` — the single supported way for other modules to
    flag something. Writes with ``sudo()`` so an acting user cannot suppress
    the record of their own blocked action, and never raises, so a fault in
    alerting cannot roll back the security decision that triggered it.

Why this module exists
======================

The master build prompt's module map has no ``sec_core``. It was added because
P1-3 requires anomaly events to be raised in Phase 1, while the dashboard that
consumes them is Phase 3. Without a shared home, ``sec_record_freeze`` and
``sec_audit_locker`` would have had to depend on ``sec_declaration_gateway`` to
reach the model, which is an unrelated concern. Recorded in PROGRESS.md under
Known Deviations.

``sec_surveillance_dashboard`` (Phase 3) will extend this model with the live
feed, thresholds and notification delivery. It must not redefine it.
