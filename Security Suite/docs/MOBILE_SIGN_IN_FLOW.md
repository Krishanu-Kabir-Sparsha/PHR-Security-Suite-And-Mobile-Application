# Mobile sign-in: workspace, company, method, credentials

**Last updated:** 2026-09-24
**Audience:** a developer changing the mobile sign-in, and the person who has to
configure it for a customer.

Supersedes the "Authentication" section of `MOBILE_APP_HANDOVER.md`, which
describes the flow as it was before the three pre-password steps existed.

---

## 1. The order, and why it is that order

```
  1. workspace      GET  /api/mobile/v1/tenant/resolve      public
  2. company        GET  /api/mobile/v1/tenant/companies    public, often empty
  3. method         (no call - decided from the company payload)
  4. credentials    POST /api/mobile/v1/auth/login
  5. fingerprint    POST /api/mobile/v1/auth/login/device    advanced only
     or passkey     POST /api/mobile/v1/auth/login/webauthn
  6. session        tokens issued, attendance recorded
```

Steps 1–3 happen **before the password field is drawn**. Each narrows what the
next one means: the workspace decides which database is being talked to, the
company decides which policy applies, and the policy decides whether a
fingerprint is going to be asked for. Somebody should know they are about to
need their thumb before they have typed a password, not after.

It also means a password is never posted to a host that has not first answered
"yes, I am a Perfect HR workspace".

**A step with one possible answer is skipped, not shown.** A single-company
tenant never sees step 2; a company permitting one method never sees step 3. A
screen that asks a question with one answer teaches people to stop reading it.

---

## 2. The workspace is the tenant

Perfect HR provisions each customer as its own PostgreSQL database behind its
own hostname, and the server runs `dbfilter = ^%h$` — **the database name is
exactly the hostname** (`saas_subscription/models/tenant_provisioner.py:61`).

So the tenant identifier and the address the app talks to are the same string.
There is no registry to look one up from the other, nothing central to be
unavailable, and no customer list to leak.

This is why the app cannot ship with a compiled-in host, and the previous build
did. `AppConfig` carried an `apiBaseUrl` per flavour and both Dio clients read it
at construction, so **one build could reach exactly one customer**. The workspace
now arrives at run time (`lib/core/tenant/`) and the Dio providers watch it, so
choosing a workspace rebuilds the client rather than requiring a restart.

What people are allowed to type, and what it becomes:

| typed | resolved |
|---|---|
| `acme` | `https://acme.perfecthr.net` |
| `ACME.PerfectHR.net` | `https://acme.perfecthr.net` |
| `https://acme.perfecthr.net/web/login` | `https://acme.perfecthr.net` |
| `localhost:8069` | `http://localhost:8069` |
| `http://acme.perfecthr.net` | **refused** |

The bare-label case matters most: it is what somebody reads off an induction
email. `http` is refused for any real host because honouring it would put a
password on the wire in clear with nothing on screen to say so; loopback is
exempt because a developer has no certificate and there is nothing to protect.

---

## 3. Who may sign into which company

**`res.users.company_ids` is the rule, and there is no second list.**

Odoo already models this, already enforces it everywhere else, and HR already
maintains it. A parallel table saying the same thing would be two sources of
truth that drift — which is exactly what the divergence report in
`controllers/capabilities.py` exists to catch, because it has happened here
before. Sign-in *enforces* `company_ids` rather than re-declaring it.

Checked in three places, all of them necessary:

| when | why |
|---|---|
| at `/auth/login` | the obvious one |
| at `/auth/login/device` | the first call may have been minutes ago |
| on **every** authenticated request | otherwise revoking access waits up to 30 days for the refresh cycle |

---

## 4. What IS configured per company

Three fields on `res.company`, on the **Mobile Sign-in** tab of the company
form. They are per-company answers, and Settings is per-user-and-current-company:
an administrator configuring four companies from Settings would switch company
four times and never see all four answers at once.

### `mobile_login_enabled` — default **off**

Controls *disclosure*, not access. The company picker is drawn before anyone
has typed a password, so whatever it lists is readable by anyone who knows the
tenant URL. A tenant with a dozen subsidiaries should not publish that org
chart to an anonymous caller.

**Leaving every company unticked is a valid configuration, not a broken one.**
The endpoint returns an empty list, the app skips step 2, and each user lands in
their own default company. Ticking is only needed where people must *choose*.

### `mobile_auth_policy` — default **advanced only**

| value | offers |
|---|---|
| `advance` | advanced only |
| `choice` | both, advanced preselected |
| `basic` | both, basic preselected |

Default is `advance` because it is the behaviour that already shipped. Quietly
relaxing an existing control on upgrade would be the worst available default.

Note that `basic` still offers advanced. The stronger option is never removed,
only de-preferred — somebody who wants to use their fingerprint always can.

### `mobile_auto_checkin` — default **on**

See section 6.

---

## 5. Basic vs advanced, and the rule neither can break

**Advanced** — password, then an Ed25519 signature from the paired handset,
released by a fingerprint. A stolen password alone buys nothing.

**Basic** — the password by itself. A genuine reduction, stated plainly rather
than buried. Three things bound it:

1. Offered only where the company's policy says so, and the default is
   advanced-only everywhere.
2. **Refused outright** for anyone holding an approval tier, the
   `requires_webauthn` flag, or an administrator group — whatever their company
   permits. `res.users._mobile_requires_advance`.
3. The session records `auth_mode`, so anything later asking "how well was this
   person authenticated" gets a truthful answer instead of an assumption.

The permitted set is computed server-side as *company policy ∩ what the account
may use*, never the union, and never from what the app sent. The client draws
the buttons; it does not decide the rule.

Approvals are unaffected by either. `sec_override_engine` demands a signature
bound to the specific request being approved, so **no session of any kind is
sufficient on its own.**

---

## 6. Signing in records attendance

A completed sign-in checks the employee in, **once per day**.

"Once per day" is derived, not remembered: if the employee has any
`hr.attendance` row whose check-in falls today, nothing happens. That one test
covers every case and has no extra state to go stale.

| situation | outcome |
|---|---|
| first sign-in of the day | `recorded` |
| already checked in | `already_in` |
| fingerprint terminal punched them in at 08:55 | `already_today` |
| **checked out for lunch, reopens the app at 14:00** | `already_today` |
| approved leave covers today | `on_leave` |
| company has it switched off | `disabled` |
| no `hr.employee` linked | `no_employee` |
| the write failed | `skipped` |

**The lunch case is why the obvious implementation is wrong.** After a lunch
check-out the employee is *not* checked in, so "check in if not checked in"
would invent an afternoon session the moment they glanced at the app.

Two further rules:

* **It can never fail a sign-in.** Every failure is swallowed and reported as
  `skipped`. A missing punch can be corrected by HR; being locked out of the app
  cannot be corrected by anyone.
* **Check-out is never automatic.** Signing out, or a session expiring, records
  nothing. A phone that lost its token at 14:00 has not told us the person went
  home, and a check-out guessed from that would silently shorten a paid day.

Rows are written through `_attendance_action_change` — the same entry point as
the kiosk, the systray and `hr_attendance_gateway` — with `in_mode = manual` and
`in_browser = "Perfect HR mobile app"`, so provenance is legible in the
attendance list without a join.

---

## 7. Signing in with an Employee ID

`/auth/login` accepts a work email **or** an Employee ID, and the server decides
which. No new field was needed: `hr.employee.identification_id` is the standard
Odoo Employee ID / badge number, and `hr_attendance_gateway` already matches
biometric terminal punches on it.

The login is tried first and unchanged, so the email path is untouched. Only
when no such login exists is the identifier treated as a badge number, and an
unmatched identifier is passed through to the password check rather than
refused early — otherwise the endpoint's timing would tell a caller whether an
Employee ID exists.

---

## 8. Where the fingerprint actually goes

**Nowhere. It never leaves the handset, and this server has never seen one.**

This is worth being explicit about, because "save the biometric on the backend"
is the natural way to ask for it and the wrong thing to build.

What happens instead:

1. At pairing the **app** generates an Ed25519 keypair. The private half is
   written to the platform keystore (Android Keystore / Keychain) and never
   transmitted.
2. Only the **public** half is sent to the server, exactly as with a passkey.
3. Each signature requires `LocalAuthentication` to succeed first — that is the
   fingerprint, and what it does is *release the local key*, not authenticate to
   us.
4. The server verifies the signature against the stored public key.

So there is no fingerprint template to store, to leak, or to be compelled to
hand over, and a database dump yields nothing that can sign anything.

"After the bio match the user gets the private key" is therefore implemented as
*the fingerprint releases the key the device already holds*. A server that
handed out private keys would be strictly weaker: the key would exist in transit,
in server memory, and in whatever logged the response.

Every signature is bound to one challenge **and** one `context_ref`, so a
confirmation given to sign in cannot be replayed as an override approval. A
monotonic counter travels with it; a repeat or a regression means the key exists
in two installations, and the server refuses and raises a critical alert.

---

## 9. Two defects fixed here that were live

**Token rotation promoted enrolment-restricted sessions.** `rotate()` did not
carry `enrolment_required` forward, so the replacement was issued with the
field's default of `False`. `/auth/refresh` is on the enrolment allow-list by
necessity, so **one call to an endpoint the restriction explicitly permits
removed the restriction** — every "you must enrol a device" gate in the product
was one refresh away from being advice. Regression test:
`tests/test_token_rotation.py::test_refresh_cannot_lift_the_enrolment_restriction`.

**Sign-out never revoked anything.** `ApiAuthRepository.signOut` accepted an
`accessToken` and never used it, and the repository's Dio carries no
AuthInterceptor, so `/auth/logout` was called anonymously, answered 401, and the
caller swallowed it as "best effort". A handed-over phone kept a working access
token for an hour and a refresh token for thirty days. The only symptom was the
absence of one.

Also fixed, in the suite rather than the app: the "approval without WebAuthn"
alert in `sec_override_engine` was written on the same cursor as the `UserError`
that refuses the approval, so every one was rolled back and the table was always
empty. Use `_raise_anomaly_out_of_band` — added to `sec.anomaly.mixin` in
`sec_core` 18.0.1.2.0 — for any alert raised immediately before a `raise`.

---

## 10. Configuring a new customer

1. Install/upgrade `perfecthr_mobile_api` (18.0.1.12.0 or later).
2. **Single-company tenant:** nothing to do. The app skips the company step.
3. **Multi-company tenant:** on each company people must choose between, open
   the company form → **Mobile Sign-in** → tick **Show in Mobile Sign-in**.
4. Set **Mobile Sign-in Policy** per company. Leave at *Advanced only* unless
   there is a reason.
5. Check **Sign-in Records Attendance** matches what the customer wants.
6. Confirm each user's **Allowed Companies** is right — that is the rule for who
   may sign in where.
7. Users pair their handset from the web: Security Suite → Authenticators →
   Pair a Device, then enter the code in the app.

---

## 11. Still outstanding

* **None of the server tests have been executed.** `perfecthr_mobile_api` now
  carries 55 test methods, and like the rest of the suite's 643 they are
  specifications until a box with Odoo and PostgreSQL runs them. The Flutter
  side *is* executed: 327 tests, all passing, `flutter analyze` clean.
* The stepped sign-in has not been exercised on a physical handset.
* `rp_id` must be settled before more passkeys are enrolled — changing it voids
  every one already enrolled.
* The company picker's rate limiter is per worker process, so the real ceiling
  is 30 calls / 5 min multiplied by the worker count. Adequate against
  enumeration; not a load control.
