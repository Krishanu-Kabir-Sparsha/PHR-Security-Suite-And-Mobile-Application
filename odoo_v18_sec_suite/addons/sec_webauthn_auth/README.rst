==========================================
Security Suite - WebAuthn Authentication
==========================================

FIDO2/WebAuthn credential enrolment and storage (US-6.1, BRD FR-6.1).

Scope of this module today
==========================

**P2-1 (built):** credential model, Relying Party configuration and its
preconditions, single-use time-limited challenges, enrolment page and browser
ceremony, revocation, enrolment-sufficiency reporting.

**P2-2 (built):** cryptographic verification of both ceremonies via
``py_webauthn`` 3.0.0. Enrolment now completes; approvals can be confirmed.

**P2-3 (built):** cloned-authenticator detection via sign-counter regression.

**P2-4 (built):** break-glass re-enrolment requiring independent approval.

Verification is delegated to the library, not hand-rolled
=========================================================

Parsing CBOR attestation objects, validating COSE keys and checking attestation
statements is precisely the kind of code where a subtle error yields something
that looks like it works and accepts forged credentials. This is the one place
in the suite where "prefer a maintained library" is not a style preference.

The library handles clientDataJSON parsing, type/challenge/origin checks, the
rpIdHash comparison, attestation verification and signature checking. This
module handles what the library cannot know about: binding an assertion to one
specific action, single-use challenge consumption, credential ownership, and
counter state.

An assertion authorises one action, not a session
=================================================

A verified assertion proves the authenticator holder was present just now. It
does not prove *what* they meant to authorise. If one assertion could be spent
by any privileged action in the same session, a user tricked into confirming
something small would have authorised something large.

So every challenge carries a ``context_ref`` naming the exact record and action
it authorises, verification refuses a mismatched context, and the success marker
lives on the HTTP request rather than the session.

``user_verification`` is ``required`` on both ceremonies: presence alone proves
somebody touched the key, not that it was its owner.

Two preconditions, enforced not assumed
=======================================

**A fixed Relying Party ID.** ``sec_webauthn.rp_id`` ships empty on purpose;
there is no safe default. Credentials bind to one origin, so changing the domain
later kills every enrolled authenticator — including, at the worst possible
moment, the Nuclear Key holder's. Enrolment refuses to start until it is set,
and the error says why.

**HTTPS with a browser-trusted certificate.** Browsers refuse the WebAuthn API
on insecure origins (localhost excepted). An Odoo at
``http://192.168.1.10:8069`` cannot do WebAuthn at all, however correct this
code is. Enrolment refuses over plain HTTP and names the origin, rather than
letting someone spend a day debugging an opaque browser error in Python.

``sec_webauthn.allow_insecure_origin`` exists for local development only. In
production it buys nothing — the browser still refuses — and hides the real
problem.

What is stored, and what is not
===============================

Only the credential ID, the COSE **public** key, a sign counter and device
metadata. The private key and any biometric data stay on the device and never
transit the network (BRD FR-6.2), which is also why WebAuthn keeps biometric
handling out of scope for most data-protection obligations (BRD Section 10).

Cryptographic material is immutable after enrolment, and credentials are
**revoked, never deleted** — the record that a credential existed is part of the
evidence for every approval it authenticated.

Revocation is self-service; re-enrolment is not
===============================================

A deliberate asymmetry. Someone who believes their key is compromised must be
able to revoke it immediately, and the worst case is inconvenience. Re-enrolling
can let an attacker add their own authenticator, so it is gated.

Three enrolment routes
----------------------

**1. First enrolment — self-service.** No credential has ever existed for this
user, so there is nothing to steal and ceremony would only obstruct onboarding.

**2. Adding a device while one still works — confirm with the existing key.**
Proving control of the current authenticator is stronger than convening
approvers and far less friction. FR-6.5 wants the CEO/Owner to hold two
authenticators, so this path has to be usable.

**3. Credentials existed, none are usable — break-glass.** Requires an approved
``sec.webauthn.recovery.request``: two approvals from distinct people, neither
of them the requester, each confirmed on their own authenticator. Approval opens
a single-use 24-hour enrolment window.

Why two approvers and not the three-tier ladder
-----------------------------------------------

The master build prompt flags a circular dependency here: the natural home for
these approvals is the override engine (P2-5), which does not exist yet. This
module carries a self-contained rule in the meantime.

It is also deliberately not tied to the three tiers, and that part may outlive
the interim. The commonest real recovery is the CEO/Owner losing their phone —
and a rule requiring the CEO's own tier to approve the CEO's recovery is
unsatisfiable at exactly the moment it is needed. Eligible approvers are any
approval-tier role holders other than the requester who hold a working
authenticator themselves.

If fewer than two eligible approvers exist, the request raises a **critical**
alert rather than failing quietly. An unsatisfiable recovery path is an
availability risk worth discovering before somebody's phone goes in a river.

Enrolment sufficiency
=====================

``check_enrolment_sufficient()`` implements BRD FR-6.5: a Tier 3 (Nuclear Key)
role requires **two** authenticators, since a single device is a single point of
failure on the highest-authority approval step. Reported rather than blocked at
enrolment, because the second device is usually procured separately.
``webauthn_enrolment_report()`` lists everyone still short, for the monthly
report (P3-4).

Clone detection, and why it is not just "counter went down = revoke"
====================================================================

py_webauthn checks the sign counter **before** it verifies the signature. So an
attacker who knows a credential ID can post a garbage assertion carrying a low
counter and reach the regression path without possessing the key. If that path
revoked the credential, anyone could remotely disable an approver's
authenticator — and the Nuclear Key would be unavailable precisely when someone
wanted it unavailable.

A suspected regression is therefore re-verified with the counter comparison
neutralised, which forces the library through signature verification (origin,
RP ID, challenge and user verification are all still checked). Only a regression
carrying a **valid signature** means the genuine key produced it:

* **Valid signature + regressed counter** → two copies of the private key exist.
  The credential is revoked automatically, the approval is blocked, a critical
  alert is raised and the owner is notified directly.
* **Invalid signature + regressed counter** → a forgery attempt. Refused and
  alerted as critical; **the credential is not touched.**

Revocation rather than refusing the single assertion is deliberate: a genuine
clone means every future assertion from that credential is equally suspect.

Authenticators that report no counter
-------------------------------------

Synced passkeys and most platform authenticators report a constant zero. Zero
against zero is not a regression, it is an absence of evidence — treating it as
a clone would revoke nearly every phone credential on second use. Those
credentials are flagged ``counter_supported = False`` and listed by
``clone_detection_report()``.

Tell the CEO/Owner plainly: for a synced passkey, a copied key would not
announce itself. That is an argument for a hardware key as the second
authenticator on the Tier 3 role, not merely a preference.

Python dependency
=================

``py_webauthn`` 3.0.0 must be installed on the Odoo server::

    pip install webauthn==3.0.0

The manifest declares it, so Odoo refuses to install the module without it
rather than failing later at the first enrolment.

Upgrading to this version withdraws a Phase 1 exemption
=======================================================

P1-6 shipped with ``sec_record_freeze.allow_toggle_without_webauthn`` set True,
because requiring a confirmation that did not exist would have made the back-end
lock toggles unusable. The ``18.0.1.1.0`` migration sets it to False
automatically now that verification exists — an exemption withdrawn by code
rather than left to somebody remembering. It never grants the exemption back.
