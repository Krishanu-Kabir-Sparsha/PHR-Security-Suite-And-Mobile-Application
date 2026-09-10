====================================
Security Suite - Override Engine
====================================

The Nuclear Key protocol: the only route to changing a frozen record.

Built on OCA ``base_tier_validation`` (``OCA/server-ux@18.0``, 18.0.3.4.1
verified in P0-4), which must be on the addons path.

Scope of this module today
==========================

**P2-5 (built):** the override request — target record, recognised policy
exception category, justification, proposed changes, Written/Oral documentation,
and submission into the three-tier ladder.

**P2-6 (built):** WebAuthn-gated sequential approval, with a mobile approval
page and a per-tier evidence record.

**P2-7 (built):** distinct-identity enforcement and the execution gate.

**P2-8 (built):** executing the approved change under a single-use unlock, with
immediate re-freeze and a Locker entry covering the whole chain.

Phase 2 is code-complete.

Execution: what actually happens
================================

**The approved change is structured, not prose.** ``proposed_changes`` is what
approvers read; ``change_ids`` is the field/value list execution applies.
Approving free text and then letting the requester type whatever they liked
into the record would mean three signatures attest to something nobody checked.

**The unlock is scoped to those fields on that record.** An approval obtained
for a price correction cannot be spent changing the counterparty, and a ticket
never authorises deletion — deleting a confirmed document is not a correction,
it is removal of the thing being corrected.

**Re-freezing is not a state change.** The record never leaves its frozen state.
What exists briefly is a single-use ticket; spending it is what re-freezes.
There is no window during which the record is "unlocked" in any general sense,
and nothing to forget to switch back.

**Both enforcement layers are told separately.** The ORM check consults the
ticket. The PL/pgSQL trigger from P1-5 knows nothing about tickets, so the
transaction also issues ``SET LOCAL sec.freeze_unlock``, reset immediately in a
``finally``. Missing either produces a puzzling half-failure — the kind of thing
that gets "fixed" by disabling a control.

Independence: what is blocked, what is flagged
==============================================

The distinction matters, because a control that blocks on a weak signal is a
control that gets switched off.

**Blocked** — provably the same identity:

* the requester approving any tier;
* one user account satisfying two tiers (the gap ``base_tier_validation``
  leaves open, and the reason this module exists);
* two user accounts linked to the same ``res.partner`` — what a deliberately
  paired account looks like in Odoo.

**Flagged, not blocked** — suspicious with innocent explanations:

* two tiers approved from the same source address. In a single-office company
  that is Tuesday. It raises an alert and appears in the monthly report.

The honest limit, worth stating to the CEO/Owner rather than glossing
------------------------------------------------------------------------

No software check can tell whether three genuinely distinct people, on distinct
devices, agreed in a corridor beforehand. What this architecture does is force
that conversation to involve three named individuals who each cryptographically
signed for it, on their own hardware, in sequence.

That is a far stronger evidentiary position than the phone-call model in the
BRD's problem statement, and it is what should be claimed — not "collusion is
prevented".

The execution gate
==================

``_assert_executable()`` runs immediately before the edit (P2-8) and re-derives
everything from stored approval records rather than trusting ``state`` or the
upstream ``validated`` flag. Those are conclusions; this is the last checkpoint
before a frozen record changes. It requires three distinct approvers, none of
them the requester, one approval per configured tier, every one
WebAuthn-confirmed. Any failure raises a critical anomaly before refusing.

Approval requires a security key, with no fallback
==================================================

``validate_tier`` refuses to record any tier unless a WebAuthn assertion **bound
to that specific request** was verified in the same HTTP round trip. If
verification is unavailable on the server, the approval is refused rather than
downgraded — FR-5.3 says not by password alone, and an approval recorded as
"unconfirmed" would still complete the override.

Why one round trip. The assertion marker lives on the HTTP request object. A
separate verify call followed by a separate approve call would lose it, and the
obvious fix — putting the marker in the session — is exactly wrong: one
confirmation would then authorise every later approval in the same browser
session. ``/override/approve/submit`` therefore verifies and records in one
call, and clears the marker afterwards.

Rejection is deliberately *not* gated. A rejection cannot change a frozen
record, and putting a hardware-key ceremony between a reviewer and "no" would
discourage the safe answer. It is still recorded with actor, time and IP.

Mobile approval page
====================

``/override/approve/<id>`` is a standalone page, not a backend form: PRD Section
9 requires approval screens usable on a mobile browser with nothing installed,
and the CEO/Owner persona wants low-friction approval from a phone. It shows the
target record, requester, category, instruction source, justification, proposed
changes and attachments before the buttons.

Two settings carry the entire sequencing requirement
====================================================

On every ``tier.definition`` for this model::

    approve_sequence        = True    approvals in order, not in parallel
    approve_sequence_bypass = False   no tier may be skipped

With ``approve_sequence`` False, all three reviewers see the request at once and
US-5.2's "each tier sees the request only after the prior tier has approved"
becomes silently untrue while the configuration still looks correct. There is a
test asserting both values; do not delete it.

What upstream does not do
=========================

Read from the ``base_tier_validation`` source rather than assumed:
``validate_tier`` filters reviews by the sequences the acting user may approve.
A user sitting in two reviewer groups can therefore satisfy two tiers. BRD FR-5.1
forbids that, and nothing upstream prevents it — it is ours to write in P2-7.

Reason categories
=================

A bounded list, deliberately short. Free-text reasons produce a register nobody
can analyse: after a year you cannot answer "how many overrides were pricing
corrections?", which is the question the monthly forensic report exists to
answer. A long list is indistinguishable from free text, because people pick
whichever entry is nearest.

Six ship by default. ``System or Integration Error`` is worth watching: a rising
count there is a signal to fix the system rather than to keep approving
overrides.

Design notes
============

**Written/Oral rules are inherited from ``sec.instruction.mixin`` (P1-2), not
reimplemented.** If the two ever diverged, one of the two routes into a frozen
record would start accepting undocumented oral instructions — the specific
failure the BRD was written to prevent.

**An override may only target a record that is actually frozen.** Otherwise this
degrades into a general-purpose approval workflow and the approval evidence stops
implying what it currently implies.

**The justification and proposed changes are locked once under review**, so the
CEO/Owner approves what the department head actually saw.
