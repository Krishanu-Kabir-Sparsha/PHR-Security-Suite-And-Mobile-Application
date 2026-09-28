# Mobile authorisation, employment and subscription

What the app shows a person *after* they have signed in, and who is allowed to
see each part of it. The sign-in flow itself is in
[`MOBILE_SIGN_IN_FLOW.md`](MOBILE_SIGN_IN_FLOW.md).

Module: `perfecthr_mobile_api` **18.0.1.15.0**.

---

## 1. Three separate questions

The app decides what to draw from three answers that are deliberately *not*
collapsed into one, because each leads somewhere different:

| Question | Source | If the answer is no |
|---|---|---|
| Does this deployment have the module at all? | `features` | "Not part of your workspace" |
| May this user perform the operation? | `permissions` (Odoo's own `has_access`) | The control is not drawn |
| What duty does the catalog give them? | `roles` (Plaza RBAC) | No approval surfaces |

"Your company does not use payroll" and "you are not allowed to see payroll"
are different sentences, and only one of them is worth asking an administrator
about.

**None of this is an authorisation boundary.** `/me/capabilities` drives menus.
Every endpoint authorises independently, running as the real user under their
real record rules — a client that fabricates a capability gets a nicer-looking
menu and the same 403.

The two things that *are* boundaries are marked as such below.

---

## 2. The employment card

`perfecthr.mobile.employment.card(employee)` — **one definition**, used by both
`/auth/login` and `/me/capabilities`.

```
employee_code            identification_id (the badge number)
job_title / job_position
department / manager
work_location / shift
work_email / work_phone
employment_status        raw contract state: draft | open | close | cancel
employment_status_label  "Awaiting contract" | "Active" | "Ended" | "Cancelled"
employee_type            "Permanent" | "Contractor" | ... (deployment's own labels)
joined_on                from the CONTRACT, never from create_date
contract_end             null on an open-ended contract
company
```

### Why it is defined once

It used to be built twice — sign-in sent `employment_status` and `joined_on`,
capabilities did not. Because the app re-reads capabilities whenever it returns
to the foreground, the Status row appeared at sign-in and then silently vanished
the first time somebody switched apps. That is the ordinary fate of a payload
defined in two places.

`test_employment_profile.py::test_both_endpoints_describe_the_same_shape`
asserts the key set, because no per-field assertion would have caught it.

### Why `joined_on` is never `create_date`

`create_date` is when the *record* was made. For any company that migrated into
Perfect HR that is the migration date, so a twenty-year employee read as a new
joiner. Tenure drives leave accrual, probation, increments and gratuity.

Three sources are tried, best first, and **none of them is `create_date`**:

1. `hr_employee_updation.joining_date` (earliest contract start)
2. `hr_contract.first_contract_date`
3. the earliest `contract_ids.date_start` we can see

If none resolves, the field is `null` and the app draws no row. A blank prompts
someone to ask HR; a confidently wrong date does not.

### Status is sent raw *and* labelled

The app styles on `employment_status` and prints `employment_status_label`.
Sending only the label would force the phone to match English to decide whether
a contract had ended; sending only the raw value would put database vocabulary
on an employee's own profile.

---

## 3. Subscription — `GET /me/subscription`

### Where the data comes from

A subscription record lives on the **master** database. A tenant cannot read
`saas.subscription` — the model is not in its registry. What it has is a
snapshot written by provisioning into its own `ir.config_parameter` under
`saas.subscription_info`
(`saas_subscription/models/tenant_provisioner.py::_store_subscription_snapshot`).

This endpoint reads that snapshot and **never calls the master**. A billing
server that is slow or unreachable must not be able to hang a phone's Settings
screen. The staleness that buys is reported as `synced_at` rather than hidden —
saying when a figure was last confirmed is the difference between a stale
number and a wrong one.

### Limits come from the snapshot; usage is measured now

| Field | Source |
|---|---|
| `user_limit`, `storage_limit_gb`, plan, price, dates | snapshot |
| users in use | live `res.users` count (`share = False`, `active = True`) |
| storage in use | live `pg_database_size` + `SUM(ir_attachment.file_size)` |

Taking usage from the snapshot would report provisioning-day figures forever —
the kind of number that looks right and never is.

### Who may read it — **this is a real boundary**

`res.users._may_view_subscription()`, checked in the controller before the
payload is built:

```
base.group_system
sec_plaza_rbac.group_security_super_admin
sec_plaza_rbac.group_plaza_admin
hr.group_hr_manager
```

Plan, price and renewal date are facts about the employer's commercial
relationship with its vendor, not about the employee.

> This is **narrower than the web on purpose.** The in-tenant web dashboard
> (`saas_tenant_dashboard`) grants `base.group_user`, so every internal user can
> already open it there. A phone is read over shoulders far more often than a
> desktop is.

### Quotas never block

`near_limit` is advisory at 80%, and `ratio` is clamped to 1.0 so a company over
its seat count gets a full bar rather than one that overflows its track. Nothing
anywhere returns a refusal. A company that could not record attendance because
it was near a storage limit would have been failed by its software, not by its
plan — and the screen says so out loud, because a progress bar beside a limit is
otherwise read as a threshold that will stop something.

### A zero limit means unlimited

Not "full", and not a division by zero. `test_a_zero_limit_means_unlimited_not_full`.

---

## 4. Technical detail is withheld, not hidden

`_may_view_diagnostics()` — narrower than the subscription gate, because an HR
manager administers people, not servers:

```
base.group_system
sec_plaza_rbac.group_security_super_admin
sec_plaza_rbac.group_plaza_admin
```

Gated **server-side**, so the payload never reaches an ordinary employee's
handset at all:

| Withheld | Was shown as |
|---|---|
| `hr_modules_installed` | "HR modules: hr, hr_attendance, …" |
| `expected_app` (package + SHA-256) | the fingerprint-mismatch card |

Hiding these in the app would not have been enough: a payload that reaches the
handset is in logs, in crash reports and in whatever a proxy kept.

`is_workspace_admin` is sent as its own flag rather than inferred from the
presence of a diagnostic field — that inference would silently invert the day a
field legitimately came back empty.

### What the app says instead

| Before | Now |
|---|---|
| Section "Modules" | "Your Perfect HR" |
| "Not installed on your server" | "Not part of your workspace" |
| "Loans — needs `ohrms_loan`" | "Loans" (module name for admins only) |
| "On your server, coming to the app" | "Your company has these, coming to the app soon" |
| "Checking what your server offers" | "Checking what your workspace includes" |
| "not linked to an employee record" | "not linked to your employee file" |
| Row "Server: dev.perfecthr.net" | under "Technical details", admins only |

**One exception, shown to everyone:** the sample-data warning. A real session
quietly sitting on fabricated figures is the one thing on that screen that could
lead somebody to act on a number that is not real, and a previous build shipped
exactly that. The *live* case is no longer stated at all — a row that is always
there is one nobody reads, which is what made the warning easy to miss.

---

## 5. `tenant_url`

`/auth/login` now returns the workspace's canonical address from
`web.base.url`, which provisioning freezes for this purpose.

Not the host the handset dialled: those differ whenever a tenant is reached
through an alias or a bare IP during setup, and the dialled one would send
somebody to the wrong place. The app prefers the canonical value and falls back
to the dialled host.

---

## 6. Tests

| File | Covers |
|---|---|
| `tests/test_employment_profile.py` | 9 — the one definition, the joining-date guard, status labelling |
| `tests/test_subscription.py` | 18 — absence, corruption, trial vs invoice date, quota arithmetic, the access gate |
| `test/features/subscription/subscription_test.dart` | 12 — parsing, quota display, and the three empty states |
| `test/features/settings/more_screen_test.dart` | both sides of every gate, plus the promotion-without-sign-out case |

The three empty states are worth keeping apart: **"there is no plan", "you may
not see the plan" and "we could not read the plan" are three different
sentences.** Collapsing them would tell an administrator their subscription had
lapsed when it had not.
