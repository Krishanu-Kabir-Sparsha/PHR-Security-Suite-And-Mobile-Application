==========================================
Security Suite - Surveillance Dashboard
==========================================

Live anomaly feed and triage (US-7.1).

Most of the data already existed
================================

``anomaly.alert`` in ``sec_core`` has been collecting since Phase 1: missing
documentation, write attempts on frozen records, freeze enforcement being
switched off, stream lock toggles, credential and clone events, break-glass
recovery, override requests, collusion attempts and executions.

This module adds the two anomaly classes in US-7.1 that nothing raised —
**edits outside business hours** and **edits crossing a high-value threshold** —
plus the feed, the evidence links and the triage views.

High-value thresholds ship empty, on purpose
============================================

PRD Section 12 open question 2 asks which figures should trigger alerts and who
tunes them. That is unanswered, so **no default thresholds are shipped**.

Inventing a figure would be worse than shipping none. Too low buries the
dashboard; too high is a control that exists on paper and fires never. Either
way the number carries the appearance of a considered business decision nobody
actually made. The configuration checker and ``coverage_report()`` say plainly
when nothing is configured, so the gap is visible rather than mistaken for
coverage — an empty dashboard section otherwise reads identically whether
nothing exceeded a threshold or no threshold exists.

Each threshold records a **tuning owner**, which answers the second half of the
PRD's question concretely rather than in a policy document nobody reads.

Three comparison modes, because "high value" is ambiguous:

* **delta** (the sensible default) — the value moved a lot either way. Catches a
  large correction to an existing figure, usually the more interesting event:
  1,000,000 to 1,001,000 is a small delta on a big number, while 1,000 to
  100,000 is a small number that grew alarmingly.
* **absolute** — the new value itself is large.
* **increase** — only growth is flagged, for fields where reductions are routine.

Multi-currency caveat: thresholds compare the value as stored on the field,
with no conversion. In a multi-currency setup, either set per-field thresholds
accordingly or watch the company-currency field.

Two decisions that determine whether the dashboard gets used
============================================================

**Timezone.** Locker timestamps are UTC, correctly. Comparing a UTC hour to
"09:00-18:00" would flag an entire Bangladeshi working day as out-of-hours, and
the dashboard would be written off as noisy in its first week. Detection
converts to a configured local timezone, falling back to the company's. The
shipped timezone parameter is empty on purpose: a hard-coded default is a
guarantee of wrong answers somewhere.

**Severity.** Out-of-hours alerts are raised at **low** severity. Working late
is normal. A dashboard where routine evening work appears as high severity
teaches its reader to ignore high severity, which costs more than it gains. The
value of an out-of-hours flag is as one signal among several: an out-of-hours
edit to a high-value field by someone who also skipped documentation is a story;
any one of them alone usually is not.

Also worth setting before go-live
---------------------------------

``sec_surveillance.working_days`` ships as Monday-Friday (ISO, Monday = 1). An
organisation on a Sunday-Thursday week that leaves this alone will have two
normal working days flagged and two weekend days cleared. **Security Suite →
Surveillance → Check Surveillance Configuration** reports the effective
settings and refuses an inconsistent one.

Triage, and why bulk review is deliberately awkward
===================================================

Bulk review exists because refusing it would be worse: a monitor facing sixty
low-severity out-of-hours alerts on a Monday morning either gets a batch action
or starts ignoring the dashboard, and an ignored dashboard is the real failure
mode.

It is made slightly awkward rather than convenient:

* every alert in a batch gets its own ``anomaly.review`` row **marked bulk**, so
  a batch dismissal is distinguishable in the monthly report from sixty
  individually considered ones;
* **high and critical alerts are refused in bulk** — those are exactly what a
  batch action would be misused to sweep away;
* the note is applied to every alert in the selection, and the wizard says so.

Reviews are append-only and reopening is itself logged, so an alert whose first
conclusion kept turning out wrong shows that history rather than only its
latest state.

Evidence links
==============

Each alert resolves the Locker entries for its record and the override request
it arose from, with buttons to open each. Triage speed is the point: an alert
that says "something happened to a sales order" and leaves the reviewer to go
and find it will be skimmed and dismissed.

The links are computed rather than stored, because alerting happens inside the
transaction being blocked and must stay cheap.

Failure behaviour
=================

Surveillance evaluation is wrapped so that a fault in it cannot break auditing.
An audit trail that fails to record because a dashboard rule threw is a worse
outcome than a missing alert, and there is a test for it.
