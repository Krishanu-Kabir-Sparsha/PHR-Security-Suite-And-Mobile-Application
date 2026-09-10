==================================
Security Suite - Audit Locker
==================================

A hash-chained, append-only audit trail built on OCA ``auditlog``.

Requirements covered
====================

============  ==========================================================
Requirement   Where
============  ==========================================================
BRD FR-4.1    ``audit.locker.entry`` (+ source IP, which OCA omits)
BRD FR-4.2    ``write``/``unlink`` blocked on both Locker and auditlog.log
BRD FR-4.3    ``audit.replica.target`` + ``replicate_pending`` (P4-1)
PRD US-4.1    ``tests/test_locker_capture.py``
============  ==========================================================

External dependency
===================

Requires OCA ``auditlog`` from ``OCA/server-tools`` branch ``18.0``
(18.0.2.0.9 verified in P0-4)::

    cd /opt/odoo/custom-addons
    git clone -b 18.0 --depth 1 https://github.com/OCA/server-tools.git

Add that directory to ``addons_path``. Pin to a commit rather than tracking
branch HEAD: an upstream change to a security control should be a decision, not
a surprise.

What this adds to OCA auditlog
==============================

OCA auditlog does the hard part well — it patches the ORM per subscribed model
and captures field-level before/after values. Three things it does not do, all
of them required here:

**Source IP.** ``auditlog.http.request`` stores path, root URL, user and
context. No client address anywhere. FR-4.1 requires it, so the Locker captures
it directly.

**Immutability.** Upstream log rows are ordinary records. Both ``write()`` and
``unlink()`` now raise, for every role.

**Tamper evidence.** Each entry hashes its own content plus the previous entry's
hash. Altering or removing any historical row invalidates every hash after it.

On the difference between tamper-proof and tamper-evident
=========================================================

FR-4.2 asks that entries be uneditable by any role "including system
administrators". At the application layer that is delivered. But BRD Section 8.2
already concedes the real limit: a PostgreSQL superuser bypasses permission
checks by design, so an application-level immutability guarantee is a guarantee
against everyone except the person most worth worrying about.

The chain changes the claim from *tamper-proof* to *tamper-evident*. A DBA can
still change the data; they cannot do so without leaving arithmetic that no
longer adds up. Once P4-1 ships external replication, they would also have to
alter a copy they do not administer.

That is a weaker claim than the source instructions asked for, and a far more
defensible one in front of an auditor. State it that way to the CEO/Owner.

Verification runs daily by cron and can be triggered from
**Security Suite → Audit Locker → Verify Chain Integrity**. A break raises a
critical anomaly and should be treated as a security incident, not a glitch.

Two deliberate operational decisions
====================================

**Audit scope is selective.** BRD risk 6 and PRD risk 5 both warn that logging
every field at production volume degrades write latency, against a 100ms
budget. Read logging is off everywhere; business models use ``fast`` logging
(changed fields only); control-configuration models use ``full``, because
weakening a control matters more than editing any single order.

**No automatic purge.** OCA's autovacuum cron is held inactive and
``unlink()`` raises. Retention is still an open question with Legal (PRD Section
12) and, when answered, should be an explicit archival process with its own
approval — an unattended nightly purge is exactly the mechanism an insider
would rely on.

External replication (P4-1)
===========================

The hash chain makes alteration *detectable*. It does not make the evidence
*survive*. If the only copy lives in a database one person administers, a
determined or coerced administrator can drop the lot and leave nothing to
compare against. Replication is what closes that.

**The part that is not software.** BRD Section 8.2 is explicit: this control
works only if the replica is administered by someone other than the application
DBA. A file written to this host, by this service account, protects against a
bad UPDATE and against nothing else. The code cannot enforce organisational
separation and does not pretend to — each target records a named
``independent_custodian``, and the absence of any configured target is reported
as a failure rather than as an empty backlog.

Two target types ship: an **append-only file** (``O_APPEND``, fsynced) and an
**HTTPS endpoint** with an HMAC signature so the receiver can distinguish a
genuine batch from anything else posted at the URL. Object storage with a
retention lock is stronger in principle and is not implemented here, because it
needs a vendor SDK and credentials that belong to whoever holds the independent
copy rather than to this module.

**Each entry ships with both hashes**, so the holder of the replica can verify
the chain without trusting anything from the primary. Replicating content alone
would let someone who rewrote history replicate the rewrite unchallenged.

**Shipping is queued, not inline.** Replication must never be able to fail an
audited business transaction; an audit control that can block a sales order gets
switched off the first time the network hiccups. Entries are written locally and
shipped by a five-minute cron. The lag is real and is reported —
``replication_status()`` gives the backlog and the age of the oldest unshipped
entry, and an hourly cron raises an alert once a lag becomes a failure.

A batch that reaches no target at all leaves its entries **pending**. Marking
them replicated on failure would lose them permanently and silently.

Reconciliation (P4-2)
=====================

Replication writes the evidence somewhere else; reconciliation is what makes
that useful. An unread replica proves nothing — it is a backup that has never
been restored. A daily cron compares the primary against every readable target.

**The comparison that matters most is the third one.** The obvious checks are
entries missing from the replica (lag or shipping failure) and differing hashes
(something was altered). But the strongest signal of the threat this suite was
built for is **entries present in the replica and absent from the primary**.

That cannot be a lag, cannot be a network fault, and cannot happen through the
application — ``unlink()`` on a Locker entry is refused for every role. It is
the shape of rows deleted directly from the database. It is reported separately,
at critical severity, and the detail text says to preserve the replica before
doing anything else.

**Unverifiable is never reported as verified.** An append-only file can be read
back. An HTTPS target cannot, unless its custodian exposes a verification
endpoint returning the ``{sequence: entry_hash}`` map — set that on the target.
Without it the verdict is ``unverifiable``, and a status check counts it against
cleanliness. A report saying "no mismatches" about a replica it could not read
would be worse than no report.

A target that has never been reconciled also counts against a clean status, for
the same reason.

Known limitation
================

Appends serialise on a single chain-head row lock, which is what prevents two
concurrent writes chaining onto the same predecessor (a fork would look
identical to tampering). Measure this in the P4-5 load test; per-model chains
are the obvious mitigation if throughput suffers.
