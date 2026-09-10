========================================
Security Suite - Forensic Reporting
========================================

The monthly forensic and compliance report for the CEO/Owner (US-8.1, BRD FR-8).

Assembly, not new analysis
==========================

Each module has carried its own reporting method since it was built —
``latest_scan_summary``, ``verify_chain``, ``verify_triggers``,
``clone_detection_report``, ``independence_report``,
``approvals_without_strong_auth``, ``coverage_report``,
``review_activity_report``, ``check_catalog_readiness``,
``webauthn_enrolment_report``. This module calls them and renders the result.

Recomputing any of it here would create two implementations of the same
judgement, and they would eventually disagree. Worse, a discrepancy between what
a module reports about itself and what the report says would be invisible. If
``verify_chain()`` is wrong, the report should be wrong in the same way, and the
error should be findable in one place.

The report leads with what is not working
=========================================

The BRD asks for an override log, a declaration reconciliation, an anomaly
summary and SoD status. All of that is here.

But a compliance report that lists activity while omitting that no high-value
threshold has ever been configured, or that the audit chain broke three weeks
ago, tells the CEO/Owner the opposite of the truth: it *looks* like assurance.
So every section can contribute **findings**, and findings appear first.

**An unconfigured control counts as a finding.** An empty section otherwise
reads identically whether nothing happened or the control was never switched on.
"No override was approved without WebAuthn" and "no override has ever been
approved" are very different sentences, and the reader should never have to
guess which one they are looking at.

**A section that cannot be gathered becomes a finding too**, never a blank. One
subsystem raising must not produce a report that silently omits it — the section
is marked unavailable and counted, and generation continues, because a report
that refuses to generate is a report nobody reads.

Contents
========

============================  ====================================================
Section                       Source
============================  ====================================================
Override log                  ``override.request`` for the period, with the
                              Written/Oral instruction source per FR-4.4
Declaration reconciliation    published version vs. active users, plus any
                              sign-off whose text hash no longer matches
Anomaly summary               counts by type and severity, unreviewed
                              high/critical, and the triage activity behind them
Segregation of duties         latest scan plus role catalog readiness
Control health                Locker chain integrity, freeze trigger presence,
                              approval strength, independence signals,
                              authenticator sufficiency, clone detection
                              coverage, threshold coverage
============================  ====================================================

Scheduling and versioning
=========================

Generated on demand and by a monthly cron for the month just ended. A second
report for the same period is a **new version**: the earlier one is marked
superseded, linked in both directions, and stays readable.

Immutability, in three parts
============================

US-8.1 asks for a report "immutable once generated". Only the first of these
delivers that phrase; the other two are what make it mean anything.

**No edits after generation.** ``write()`` and ``unlink()`` refuse once the
report is generated, for ``sudo()`` too. Before P3-5 these were entirely
unguarded — only regeneration over an existing record was blocked — so a
generated report was editable, which would have made the document worthless as
evidence. Two narrow exceptions remain, because they are genuinely learned
afterwards: rendering the PDF, and being marked superseded by a later version.

**Tamper evidence, not just refusal.** Same argument as the Locker (BRD Section
8.2): an application-layer refusal binds everyone except the person with a
database prompt. The payload is hashed at generation, re-checked on read and by
a daily cron, and a mismatch raises a critical anomaly. The claim is "an altered
report is detectable", which is true — not "a report cannot be altered", which
is not.

**The document is pinned to the data.** A PDF re-rendered months later runs
today's template over today's code; if either changed, the document differs from
the one the CEO/Owner signed off, with nothing to show for it. The PDF is
rendered once, stored, and hashed. Later downloads return the stored bytes.

If ``wkhtmltopdf`` is not installed, rendering fails with a message saying so.
The report data is complete and readable on screen regardless; only the export
is affected.

The notification puts the finding count in the subject line, so an inbox scan
carries the signal rather than requiring the attachment to be opened.
