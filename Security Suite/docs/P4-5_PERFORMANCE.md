# P4-5 — Performance Assessment Against the PRD NFRs

**Date:** 05 September 2026 (session 24)
**Status:** analysis and one optimisation, plus a harness to be run on real
hardware. **No load test has been executed** — there is no Odoo runtime here.

---

## The targets (PRD Section 9)

| NFR | Target |
|---|---|
| Audit logging overhead | < 100 ms added to a standard record save |
| Anomaly alert delivery | 99.5% within 60 s of the triggering event |
| Approval / override screens | < 2 s under normal load |

---

## What was actually measured

Only the parts that are pure Python and independent of the database. These are
real figures from this environment, not estimates:

| Operation | Measured |
|---|---|
| Locker canonicalisation + SHA-256, one entry | **7.3 µs** |
| Same, as a share of the 100 ms budget | **0.01%** |
| Chain verification, 100,000 entries (hashing only) | ~0.7 s |
| Chain verification, 1,000,000 entries (hashing only) | ~7.3 s |
| Forensic report payload hash, ~0.9 MB | 2.5 ms |

**The cryptography is not the problem and will not become the problem.** Anyone
proposing to weaken the hash chain for performance reasons should be shown this
table. At a million entries, verification is seven seconds of hashing in a
nightly cron.

---

## What was found by analysis, and fixed

### Three configuration queries on every write · fixed

Every `write()` to `sale.order`, `purchase.order`, `account.move` or their lines
issued three `SELECT`s before doing anything:

1. the freeze rule for the model,
2. the transaction stream for the model,
3. the stream lock for that stream.

All three read tiny configuration tables that change perhaps once a year, and
all three sat on the hot path of every sales order save. On a local database
that is a few hundred microseconds; across a network to a separate database
host, three round trips per write is the kind of overhead that shows up as "the
system got slower after the security module went in".

**Fixed** with `ormcache` on the rule id, the stream, and the set of locked
streams. Only ids and scalars are cached, never recordsets. Caches are cleared
on any change to a freeze rule or a stream lock, so a lockdown takes effect
immediately — a control that needed a restart to bite would be worse than the
query cost it saved.

---

## The risk this task cannot close

**The Locker serialises every audit append on one row.**

`append()` takes `SELECT ... FOR UPDATE` on the single chain-head row, because
two concurrent appends reading the same predecessor hash would fork the chain —
and a forked chain is indistinguishable from tampering at verification time.
That was the right call for correctness and was flagged as a performance risk
when it was written (P1-7).

The consequence: **every audited write in the system, across all users,
queues behind one row lock.** Single-threaded benchmarks will not show this. It
appears only under concurrency, and it appears as a cliff rather than a slope.

The arithmetic that matters is not the hash cost (7.3 µs) but the lock hold
time, which spans the `SELECT FOR UPDATE`, the `INSERT`, and the chain-head
`UPDATE` — realistically a few milliseconds including round trips. At a few
hundred audited writes per minute that is invisible. At a few thousand per
minute it is the bottleneck for the whole ERP.

**Prepared mitigation, not yet built:** per-model or per-stream chains. Sales,
Purchase and Accounting would each carry their own chain head, so they no longer
contend, and verification checks three chains instead of one. The cost is that a
cross-model ordering guarantee is lost, which nothing currently relies on.

**Do not implement this speculatively.** Measure first with the harness under
concurrency; if the numbers are comfortable, the added complexity is not worth
buying.

---

## Other hot paths worth watching, in order of likely impact

1. **Out-of-band cursor per blocked write.** Every refused edit opens a separate
   database cursor to record the anomaly so it survives the rollback. Correct,
   and cheap while refusals are rare. If a misconfigured integration starts
   hammering a frozen model, each failure costs a cursor. Worth an alert on
   refusal *rate*, which does not exist yet.
2. **`auditlog` in `fast` mode** captures changed fields only — already the
   cheaper setting, and read logging is off everywhere. Little left to tune.
3. **Anomaly evidence links** are computed, not stored, and one of them searches
   the Locker by model and id. Fine on a form view; avoid putting
   `locker_entry_count` in a list view over thousands of alerts.
4. **Replication** is queued on a five-minute cron and batched at 500. It cannot
   affect interactive latency by design. Its own risk is the opposite: a backlog
   that grows faster than it drains, which the hourly backlog check reports.
5. **Chain verification** is nightly and single-threaded. At a million entries
   it is seconds; at fifty million it is minutes and should move to verifying a
   rolling window plus a periodic full pass.

---

## The 60-second alerting target

Structurally met and worth stating precisely, because "real time" is doing a lot
of work in the PRD.

Alerts are raised **synchronously, inside the triggering transaction** (or on a
separate cursor when the transaction is being rolled back). They exist in the
database within milliseconds of the event. So the 60-second target is met for
*alert creation* with four orders of magnitude to spare.

**Delivery is a different question.** The dashboard is a pull view; email and
in-app notification go through Odoo's normal mail queue, which is cron-driven.
Whether a human learns of a critical anomaly within 60 seconds depends on
notification configuration that is outside this suite. If the CEO/Owner expects
a phone to buzz within a minute, that needs an outbound integration nobody has
specified yet.

---

## How to actually run this

`tools/benchmark_nfr.py`, in an Odoo shell against **a copy of production
data**. Table sizes and index depth are most of the answer; a scratch database
with fifty records will report numbers that mean nothing.

```bash
odoo shell -c /etc/odoo/odoo.conf -d YOUR_DB_COPY < tools/benchmark_nfr.py
```

It reports median and p95 for audited writes, the baseline, the derived audit
overhead against the 100 ms target, Locker append, order confirmation, the
blocked-write path, and chain verification over the live chain.

**It is single-threaded and says so in its own output.** The chain-head
contention above will not appear. Re-run with concurrent workers — several
simultaneous shells, or a load tool against the web endpoints — before treating
any of it as a production answer.

---

## Honest summary

- Measured: the cryptography is negligible. That question is settled.
- Fixed: three per-write configuration queries, now cached.
- Unresolved and unmeasurable from here: append serialisation under concurrency,
  which is the one genuine scaling risk in the design.
- Not attempted: end-to-end screen latency, which needs a browser and a server.

The NFRs cannot be signed off on this basis. What exists is a defensible
prediction and a repeatable way to test it.
