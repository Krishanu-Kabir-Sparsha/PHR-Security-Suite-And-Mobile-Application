# Perfect HR mobile — deploy & test checklist

Covers all three rounds of mobile work: **authentication**, **check-in/out**,
and **authorization + subscription**. Last updated 2026-09-27.

Related: [`MOBILE_SIGN_IN_FLOW.md`](MOBILE_SIGN_IN_FLOW.md) ·
[`ATTENDANCE_SYSTEM.md`](ATTENDANCE_SYSTEM.md) ·
[`MOBILE_AUTHORIZATION.md`](MOBILE_AUTHORIZATION.md)

---

## Part 1 — What to deploy

### Every module the mobile app needs

The dependency closure is **five** Security Suite modules. All five must be on
the addons path or the install fails on a tenant that does not already have
them — an earlier version of this list named only three, and it worked on dev
purely because the other two were already there.

| Module | Version | Where it lives |
|---|---|---|
| `perfecthr_mobile_api` | **18.0.1.15.0** | `sec_security_suite_addons/Security Suite/` |
| `sec_core` | 18.0.1.2.0 | `sec_security_suite_addons/Security Suite/` |
| `sec_declaration_gateway` | 18.0.1.0.0 | `sec_security_suite_addons/Security Suite/` |
| `sec_plaza_rbac` | 18.0.1.5.0 | `sec_security_suite_addons/Security Suite/` |
| `sec_webauthn_auth` | 18.0.1.9.0 | `sec_security_suite_addons/Security Suite/` |
| `sec_override_engine` | 18.0.1.2.0 | not a mobile dependency; carries its own alert fix |
| `hrms_dashboard` | **18.0.1.0.12** | `Debranded Apps (connected to github odoo intern)/` |
| `saas_subscription` | **18.0.1.4.0** | master only — see the fleet rollout below |
| `saas_tenant_guard` | **18.0.1.1.0** | master **and every tenant** |
| `perfect_hr_mobile` | **0.2.0+2** | **rebuild the APK** |

Check which build is on the handset with
`adb shell dumpsys package com.perfecthr.perfect_hr_mobile | grep versionName` — this
round is **0.2.0+2**; the previous one was 0.1.0+1.

The APK **must** be rebuilt — `geolocator: ^13.0.1` is a new native dependency.
The manifest has declared `ACCESS_FINE_LOCATION` since the first build with
nothing reading it, so before this every punch reached the server with no
coordinates.

```bash
scp -r "Security Suite/perfecthr_mobile_api" \
       "Security Suite/sec_core" \
       "Security Suite/sec_override_engine" \
       "Debranded Apps (connected to github odoo intern)/hrms_dashboard" \
       you@dev.perfecthr.net:/opt/odoo/custom-addons/

ssh you@dev.perfecthr.net
find /opt/odoo/custom-addons -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
sudo systemctl stop odoo
sudo -u odoo /opt/odoo/odoo-bin -c /etc/odoo/odoo.conf -d dev.perfecthr.net \
     -u perfecthr_mobile_api,sec_core,sec_override_engine,hrms_dashboard \
     --stop-after-init
sudo systemctl start odoo
sudo journalctl -u odoo -n 100 --no-pager | grep -iE "error|traceback|Automatic check-out"
```

```powershell
cd sec_security_suite_addons\perfect_hr_mobile
flutter build apk --release --dart-define=FLAVOR=dev
$env:Path += ";$env:LOCALAPPDATA\Android\Sdk\platform-tools"
adb install -r build\app\outputs\flutter-apk\app-release.apk
```

**Hard-close the app after installing** (swipe it out of recents) so cached
payloads from the old build are re-fetched in the new shape.

### Optional — run the server tests first

117 test methods exist and have **never been executed** (no Odoo/PostgreSQL on
the dev workstation). They will catch the break arithmetic and geofence maths
faster than manual testing will.

```bash
sudo -u odoo /opt/odoo/odoo-bin -c /etc/odoo/odoo.conf -d test_phr \
     -i perfecthr_mobile_api --test-enable --stop-after-init
```

Use a **throwaway database**. `--test-enable` writes real records.

---

---

## Part 1b — Rolling out to SaaS tenants

Skip this if you are only testing one hand-made database. It matters the
moment a **provisioned** tenant is involved.

### Why a plain `-u` is not enough

Tenants are created from a template by `saas_subscription`, and afterwards
`_restrict_tenant_modules()` **deletes** the `ir_module_module` rows for
everything not installed, while `saas_tenant_guard` blocks `update_list()` so
the catalogue cannot be re-scanned.

That combination froze the catalogue against the **platform**, not just against
the tenant admin: the provisioner's own `--init` goes through the same ORM
call. A module added after a tenant was created could not reach it, and because
Odoo logs an unknown module name as a *warning* and still exits **0**, the sync
reported success and cleared `module_sync_pending`. First-time provisioning
never hit it, because the guard is not yet installed at Step 5 — which is why
it stayed invisible.

Fixed in `saas_subscription` 18.0.1.4.0 / `saas_tenant_guard` 18.0.1.1.0:

* `perfecthr_mobile_api` joins `SYSTEM_TENANT_MODULES`, so every tenant gets it
  regardless of package, exactly as SSO does. Its dependencies come with it.
* The provisioner opens a **time-boxed** discovery window (15 min, an absolute
  expiry, so a crashed install cannot leave a tenant unlocked) and closes it in
  a `finally`.
* `_install_modules()` now **verifies** against the database and raises if a
  requested module is still not installed.

### The order matters

Each tenant's own copy of the guard has to understand the window before the
sync can use it.

```bash
# 1. All modules onto the shared addons path.
scp -r "Security Suite/perfecthr_mobile_api" "Security Suite/sec_core"        "Security Suite/sec_declaration_gateway" "Security Suite/sec_plaza_rbac"        "Security Suite/sec_webauthn_auth" "Security Suite/sec_override_engine"        "Debranded Apps (connected to github odoo intern)/hrms_dashboard"        "Debranded Apps (connected to github odoo intern)/saas_subscription"        "Debranded Apps (connected to github odoo intern)/saas_tenant_guard"        you@server:/opt/odoo/custom-addons/

# 2. The guard on EVERY tenant first. -u works because it is already installed.
for db in $(sudo -u postgres psql -At -d postgres             -c "SELECT datname FROM pg_database WHERE datname LIKE '%.perfecthr.net';"); do
  echo "== $db"
  sudo -u odoo /opt/odoo/odoo-bin -c /etc/odoo/odoo.conf -d "$db"        -u saas_tenant_guard --stop-after-init --no-http
done

# 3. The master.
sudo -u odoo /opt/odoo/odoo-bin -c /etc/odoo/odoo.conf -d perfecthr_master      -u saas_subscription,saas_package --stop-after-init

# 4. Flag every live subscription for sync, then let the cron run
#    (or run it now from Settings > Technical > Scheduled Actions).
sudo -u postgres psql -d perfecthr_master -c   "UPDATE saas_subscription SET module_sync_pending = true
    WHERE state IN ('active','suspended') AND tenant_db_name IS NOT NULL;"
```

### Confirm it actually landed

| # | Check | Expected | ✓ |
|---|---|---|---|
| 1b.1 | On a tenant: `SELECT name,state FROM ir_module_module WHERE name='perfecthr_mobile_api';` | one row, `installed` | ☐ |
| 1b.2 | `SELECT value FROM ir_config_parameter WHERE key='saas.allowed_modules';` | contains `perfecthr_mobile_api` | ☐ |
| 1b.3 | `SELECT key FROM ir_config_parameter WHERE key='saas.module_discovery_until';` | **no row** — the window closed | ☐ |
| 1b.4 | Master: `SELECT name,module_sync_pending FROM saas_subscription WHERE module_sync_pending;` | empty once the cron has run | ☐ |
| 1b.5 | Point the app at that tenant and sign in | Works | ☐ |
| 1b.6 | Break it on purpose: remove a `sec_*` module from the addons path and re-sync | The sync now **fails loudly** instead of reporting success | ☐ |

> 1b.3 is the one not to skip. A window left open means that tenant can re-scan
> the shared addons directory, which is the single thing `saas_tenant_guard`
> exists to prevent.

> 1b.6 is what proves the silent-success bug is actually gone. Put the module
> back afterwards.

---

## Part 2 — Configure

### 2.1 Company (Settings → Companies → your company → **Mobile Sign-in** tab)

| Group | Field | Set to |
|---|---|---|
| Who may choose this company | Mobile login enabled | ✅ on |
| How they must prove who they are | Mobile auth policy | `Company chooses, user picks` |
| Attendance | Auto check-in on sign-in | ✅ on |
| Attendance | Automatic check-out | ✅ on (the migration should have done this) |
| Attendance | Tolerance | `2.00` hours |
| Location | Geofence mode | `Off` to start — turn on at test 5.x |

> The 18.0.1.14.0 migration enables `auto_check_out` automatically, but **only**
> where the setting was still on its shipped default. Check the upgrade log for
> the line naming the companies it touched.

### 2.2 Employee record

Employees → your test employee:
- **HR Settings → Identification No** = `EMP-00421` (this is the Employee ID you
  can sign in with, and what the fingerprint terminals match on)
- **Work Information → Work Location** set
- **Work Information → Working Hours** set (drives the auto-close time)
- A **contract** with a `date_start` — without one, *Joined* is correctly blank

### 2.3 Work location coordinates (for the geofence tests only)

Employees → Configuration → Work Locations → your location:
- `geofence_latitude`, `geofence_longitude`, `geofence_radius_m` (default 250)
- `geofence_ready` should tick green once both coordinates are set

### 2.4 Subscription snapshot — **needed to test Part 6**

The Subscription screen reads `saas.subscription_info` from the tenant's own
config. A dev tenant provisioned through the SaaS pipeline already has it. If
yours does not, seed it:

*Settings → Technical → Parameters → System Parameters → New*

- Key: `saas.subscription_info`
- Value (one line):

```json
{"package_name":"Enterprise","tier_level":"enterprise","billing_plan_label":"Annual","state":"active","is_trial":false,"date_start":"2026-01-01","date_next_invoice":"2027-01-01","currency":"৳","monthly_price":12000.0,"storage_limit_gb":50.0,"user_limit":100,"subscription_ref":"SUB-00017","manage_url":"https://perfecthr.net/my/subscriptions/17","upgrade_url":"https://perfecthr.net/my/subscriptions/17/upgrade","synced_at":"2026-09-20T10:00:00"}
```

### 2.5 Two test users

You need both to test the access gates.

| User | Groups | Purpose |
|---|---|---|
| **Staff** | `base.group_user` only | Sees no plan, no technical detail |
| **Admin** | + `base.group_system` or Plaza Admin | Sees both |

---

## Part 3 — Tenant resolution and device pairing

The workspace step and pairing come **before** any sign-in, so they are tested
first. A pairing code is minted inside one tenant's database and is meaningless
anywhere else.

| # | Step | Expected | ✓ |
|---|---|---|---|
| 0.1 | Fresh install, first screen | "Perfect HR address", hint `yourcompany.perfecthr.net` | ☐ |
| 0.2 | Type `dev` alone | Resolves — "Your company name on its own works too" | ☐ |
| 0.3 | Type `https://dev.perfecthr.net/` | Resolves to the **same** workspace | ☐ |
| 0.4 | Type a host that is not a tenant | Plain refusal, no hostname error, no stack trace | ☐ |
| 0.5 | A resolved workspace | Shows the **company's own name**, not the URL | ☐ |
| 0.6 | Company step | Lists **only** companies with mobile login enabled | ☐ |
| 0.7 | Disable mobile login on a company in Odoo, re-resolve | That company disappears from the list | ☐ |

### Pairing this handset

| # | Step | Expected | ✓ |
|---|---|---|---|
| 0.8 | In Odoo as an **ordinary employee** → **Mobile App** menu | Visible, with *Pair My Phone* and *My Paired Devices* | ☐ |
| 0.9 | Pair My Phone | A code, with a visible expiry | ☐ |
| 0.10 | App → *Pair this device* → enter login + code | Paired; the app confirms the account | ☐ |
| 0.11 | Odoo → **My Paired Devices** | The handset is listed with its label | ☐ |
| 0.12 | Re-use the **same** code a second time | Refused — single use | ☐ |
| 0.13 | Wait past 10 minutes, then use a code | Refused as expired, with "generate a new code" | ☐ |
| 0.14 | Enter a wrong code five times | The code is burned; generating a new one recovers | ☐ |
| 0.15 | Use a code from tenant A against tenant B | Refused — codes live in one tenant's database only | ☐ |

---

## Part 4 — Tenant isolation ← **new, and the important one**

Perfect HR tenants are **different customers**. Nothing a handset holds for one
may ever be reachable while it is pointed at another.

Before this release the session token and the Ed25519 device key lived in
single unnamespaced slots. A phone paired to Acme that changed workspace to
Globex would offer **Acme's** device handle, and a signature made with Acme's
private key, to Globex's server. Globex rejects it — after it has arrived in
their logs.

You need **two tenants** for this part. If dev is your only one, skip to Part 5
and note it as untested rather than passing it.

| # | Step | Expected | ✓ |
|---|---|---|---|
| 0.16 | Pair + sign in to tenant **A**. Sign out. Tap **Use a different address** | Returns to the workspace step | ☐ |
| 0.17 | Check tenant A's `mobile.token` rows in Odoo | The token is **revoked** — leaving a workspace revokes at that workspace | ☐ |
| 0.18 | Enter tenant **B**, reach the credentials step | The app offers **Pair this device**, *not* "already paired" | ☐ |
| 0.19 | B's login screen | Does **not** name tenant A's login anywhere | ☐ |
| 0.20 | Sign in at B (pair again first if B requires a device) | Works, with B's own credentials | ☐ |
| 0.21 | Odoo on tenant **B** → **My Paired Devices** | Shows a device paired to **B**. Tenant A's handle appears nowhere | ☐ |
| 0.22 | Now go back: leave B, return to workspace **A** | A asks for a full sign-in **and** re-pairing | ☐ |

### Upgrading an existing install (do this once, on the handset you already paired)

| # | Step | Expected | ✓ |
|---|---|---|---|
| 0.23 | Install the new APK **over** the old one — do *not* uninstall | Still signed in. **No re-pairing, no re-login** | ☐ |
| 0.24 | More → the device is still recognised | Pairing survived the upgrade | ☐ |
| 0.25 | Approve something needing the device key | Signs correctly — the counter did not restart | ☐ |

> 0.23–0.25 test the one-time adoption of pre-namespacing credentials. If you
> uninstall first you will not be testing it, and you will have to pair again.

---

## Part 5 — Authentication

| # | Step | Expected | ✓ |
|---|---|---|---|
| 1.1 | Open app, first screen | "Perfect HR address" field, hint `yourcompany.perfecthr.net` | ☐ |
| 1.2 | Type just `dev` (no domain) | Resolves — "Your company name on its own works too" | ☐ |
| 1.3 | Type a nonsense address | Plain refusal, no stack trace, no raw hostname error | ☐ |
| 1.4 | Enter a valid workspace | Company list appears, **only companies with mobile login enabled** | ☐ |
| 1.5 | Company step | Method picker: *Basic* and *Advanced*, per company policy | ☐ |
| 1.6 | Set policy to `Advance only`, retry | Basic is **not offered** | ☐ |
| 1.7 | Sign in as an **approver / Plaza admin** with policy `basic` | Still forced to Advanced — a user-level rule beats the company's | ☐ |
| 1.8 | Credentials step | Label reads "Work email or Employee ID" | ☐ |
| 1.9 | Sign in with `EMP-00421` instead of email | Works | ☐ |
| 1.10 | Wrong password | Same message for wrong-user and wrong-password (no account enumeration) | ☐ |
| 1.11 | Advanced path | Biometric prompt on the handset; the print never leaves the device | ☐ |
| 1.12 | Sign out, sign back in | Works; no "already checked in" error | ☐ |

### Token & session

| # | Step | Expected | ✓ |
|---|---|---|---|
| 1.13 | Sign out from More | Session revoked **server-side** — check `mobile.token` in Odoo, the row is revoked | ☐ |
| 1.14 | Leave app 1h+, return | Silent refresh, no re-login | ☐ |
| 1.15 | After a refresh, check the token row | `enrolment_required`, `company_id`, `auth_mode` all still set | ☐ |

> 1.15 is the regression test for a shipped bug: `rotate()` dropped
> `enrolment_required`, so one `/auth/refresh` removed the device-enrolment gate
> entirely.

| # | Step | Expected | ✓ |
|---|---|---|---|
| 1.16 | Remove the user from the company in Odoo, then use the app | Token revoked on the next request | ☐ |

---

## Part 6 — Auto check-in on sign-in

| # | Step | Expected | ✓ |
|---|---|---|---|
| 2.1 | First sign-in of the day, nothing on today's attendance | Checked in automatically; Home shows **CHECKED IN** with the time | ☐ |
| 2.2 | **The lunch trap.** Check out in Odoo, then reopen/re-login on the phone | **No second check-in.** The afternoon session is not invented | ☐ |
| 2.3 | Punched in at a kiosk/terminal first, then sign in on the phone | No duplicate row | ☐ |
| 2.4 | Sign out and back in at 21:00 same day | No new row | ☐ |
| 2.5 | Employee on approved leave today | No check-in; state reads `on_leave` | ☐ |
| 2.6 | Turn **off** `mobile_auto_checkin`, sign in | No check-in, sign-in still succeeds | ☐ |
| 2.7 | User with **no** `hr.employee` link | Sign-in still succeeds; banner says the login is not linked to an employee file | ☐ |

---

## Part 7 — Check in / check out

### 5.1 Times (the UTC bug)

| # | Step | Expected | ✓ |
|---|---|---|---|
| 3.1 | Check in, look at Attendance tab | **Your actual local time**, not 6 hours earlier | ☐ |
| 3.2 | Two sessions in a day | Listed `9:00 AM → 5:00 PM`, ascending — never backwards | ☐ |
| 3.3 | Kill the app, reopen | Times unchanged (cache round-trip does not shift them) | ☐ |
| 3.4 | Compare phone vs Odoo Attendance list | Same wall-clock time | ☐ |

### 5.2 The stale session

| # | Step | Expected | ✓ |
|---|---|---|---|
| 3.5 | Leave a row open from a previous day, open the app | Home banner: *"You are still checked in from …"* **before** you tap anything | ☐ |
| 3.6 | Tap **Close that session** | Closes at `check_in + scheduled hours` (≈8h), **not** at now | ☐ |
| 3.7 | Check the row in Odoo | Check-out ≈8h after check-in; Mode = `Automatic Check-Out` | ☐ |
| 3.8 | Now check in normally | Works — no "hasn't checked out since …" error | ☐ |

> Before this fix, one unclosed row made `_check_validity` refuse **every** later
> check-in, with no way out from the phone.

### 5.3 Breaks

| # | Step | Expected | ✓ |
|---|---|---|---|
| 3.9 | While checked in, tap **Take a Break** | State → **ON BREAK**; button becomes *End Break* | ☐ |
| 3.10 | Try **Check Out** mid-break | Refused: *"End the break before you check out"* | ☐ |
| 3.11 | End break, wait a minute, check out | Succeeds | ☐ |
| 3.12 | Open the attendance in Odoo | A **Breaks** section lists it | ☐ |
| 3.13 | Worked Hours | Reduced by **exactly** the break | ☐ |
| 3.14 | **Double-deduction check.** Same test on an employee with a scheduled lunch | Lunch is **not** deducted on top — a 1h break must not cost 2h | ☐ |
| 3.15 | Employee with **no** recorded break | Worked Hours unchanged from before this release | ☐ |

### 5.4 Geofence

Set company geofence mode to **Enforce** first.

| # | Step | Expected | ✓ |
|---|---|---|---|
| 3.16 | Check in from far away | Refused with the **distance** and the location name | ☐ |
| 3.17 | The refusal | A **reason prompt**, not a dead end | ☐ |
| 3.18 | Enter "Client visit at Gulshan", send again | **Accepted** | ☐ |
| 3.19 | Odoo → Attendances → filter **Away From Work Location** | The row is there with the reason | ☐ |
| 3.20 | Deny location permission on the phone, check in | **Still punches.** No coordinates sent, no refusal | ☐ |
| 3.21 | Turn location off entirely, check in | Still punches | ☐ |
| 3.22 | Set mode to `Warn` | Punch accepted first time, flagged off-site | ☐ |
| 3.23 | Set mode to `Off` | No location check at all | ☐ |

> 3.20 and 3.21 are the ones that matter most. A GPS failure must never stop
> someone being recorded as at work — those failures fall hardest on whoever has
> the older handset or the basement office.

### 5.5 Cross-dynamic (phone ↔ web)

| # | Step | Expected | ✓ |
|---|---|---|---|
| 4.1 | Check in on the phone, switch to the web dashboard tab (**don't reload**) | Picks up the check-in on focus | ☐ |
| 4.2 | The web timer | Shows **real elapsed time**, not `00:00:00` | ☐ |
| 4.3 | Check out on the web, switch back to the phone | Updates on foreground | ☐ |
| 4.4 | Click check-in on the web while already checked in elsewhere | Honest refusal — **no optimistic flip** that lies about the state | ☐ |
| 4.5 | Web check-in with a stale session open | Refused with the reason | ☐ |
| 4.6 | Reload the web dashboard mid-session | Timer resumes at the correct elapsed time | ☐ |

> 4.4 was a real defect: the web flipped the button optimistically and never
> reconciled, so the dashboard could sit there claiming you were checked in when
> the server had refused.

---

## Part 8 — Authorization

### 6.1 The employment card (More → under your name)

| # | Step | Expected | ✓ |
|---|---|---|---|
| 5.1 | Open More | Card shows Employee ID, Position, Employment, Department, Reports to, Work location, Shift, Status | ☐ |
| 5.2 | **Status** row | Reads `Active` / `Ended` — **never** `open` / `close` | ☐ |
| 5.3 | **Employment** row | Reads `Permanent` / `Contractor` — never a raw key | ☐ |
| 5.4 | **Joined** row, employee **with** a contract | The contract start date, formatted (`March 1, 2019`) | ☐ |
| 5.5 | **Joined** row, employee with **no** contract | **Row absent.** Not today's date, not the record creation date | ☐ |
| 5.6 | Employee with a blank HR record | No card at all — not a card of dashes | ☐ |

> 5.5 is the regression guard. It used to come from `create_date`, so every
> employee of a migrated company read as having joined on the migration date.

| # | Step | Expected | ✓ |
|---|---|---|---|
| 5.7 | **Promotion without sign-out.** Change the employee's Job Position in Odoo. Background the app, wait, foreground it | New position appears **without signing out** | ☐ |
| 5.8 | Same for department / manager / work location | All refresh | ☐ |

> 5.7 was broken two ways: the two endpoints sent different payloads, and the
> app never parsed the fresher one. Status and Joined appeared at sign-in and
> vanished the first time you switched apps.

### 6.2 Role-wise features

| # | Step | Expected | ✓ |
|---|---|---|---|
| 5.9 | Sign in as **Staff** | No Approvals tile, no Workforce, no role-preview picker | ☐ |
| 5.10 | Sign in as a **manager** | Approvals appears | ☐ |
| 5.11 | Uninstall a module in Odoo (e.g. `hr_recruitment`), refresh the app | Recruitment moves to *"Not part of your workspace"* | ☐ |
| 5.12 | More → **Your roles** | Roles named by **duty**, not by code | ☐ |
| 5.13 | As Plaza Admin → **View as role** | Picker present; a persistent banner while previewing | ☐ |
| 5.14 | As Staff | Picker **absent** — not present-and-refusing | ☐ |
| 5.15 | Multi-company user → More → **Company** | Switcher present; switching re-scopes the data | ☐ |
| 5.16 | Single-company user | No switcher | ☐ |

### 6.3 Multi-company

| # | Step | Expected | ✓ |
|---|---|---|---|
| 5.17 | Switch company in the app | Attendance, leave and team all re-scope | ☐ |
| 5.18 | Employment card after the switch | Shows the employment for **that** company | ☐ |

---

## Part 9 — Subscription

Requires §2.4 seeded and the two users from §2.5.

| # | Step | Expected | ✓ |
|---|---|---|---|
| 6.1 | Sign in as **Staff** → More | **No Subscription tile** | ☐ |
| 6.2 | Sign in as **Admin** → More → Account | **Subscription** tile present | ☐ |
| 6.3 | Open it | Plan name, price, billing, status, started, renews, reference | ☐ |
| 6.4 | Price | Formatted `৳12,000.00 / month` — symbol, thousands, two decimals | ☐ |
| 6.5 | Renews row | Date **plus** a countdown (`· in 97 days`) | ☐ |
| 6.6 | **Usage → People with a login** | A **live** count, matching active internal users in Odoo | ☐ |
| 6.7 | **Usage → Storage** | A live GB figure, not `0` and not the limit | ☐ |
| 6.8 | Add a user in Odoo, pull to refresh | Count goes **up** | ☐ |
| 6.9 | Usage note | States that going over a limit **never stops anyone working** | ☐ |
| 6.10 | **What your workspace runs** | App display names — *Attendances*, *Employees*. **Never** `hr_attendance` | ☐ |
| 6.11 | Footer | *"Plan details last confirmed …"* with the `synced_at` time | ☐ |
| 6.12 | **Manage plan** button | Opens the customer portal in a browser | ☐ |

### Subscription edge cases

Edit the `saas.subscription_info` parameter between each, then pull to refresh.

| # | Change | Expected | ✓ |
|---|---|---|---|
| 6.13 | `"is_trial":true,"trial_end_date":"2026-10-05"` | Banner **amber**, "Free trial — N days left"; *Trial ends* counts to **that** date, not the invoice date | ☐ |
| 6.14 | `"state":"suspended"` **and** `"is_trial":true` | Reads **Suspended**, not Trial — the worst true thing leads | ☐ |
| 6.15 | `"state":"expired"` | Banner **red**, "This subscription has ended" | ☐ |
| 6.16 | `"user_limit":0,"storage_limit_gb":0` | "No limit on your plan" — **no bar, no division by zero, not a full bar** | ☐ |
| 6.17 | `"user_limit":1` | Bar **amber and full**, never overflowing its track; nothing is blocked | ☐ |
| 6.18 | `"monthly_price":0` | Price row **absent** — not `৳0.00` | ☐ |
| 6.19 | Delete the parameter entirely | *"No subscription on this workspace"* — **not** an error, **not** an empty plan | ☐ |
| 6.20 | Set the value to `not json` | Same as 6.19, plus a warning in the Odoo log | ☐ |
| 6.21 | Turn off wifi, open the screen | *"Could not load your plan"* — **never** "No subscription on this workspace" | ☐ |

> 6.19 vs 6.21 is the distinction the screen exists to preserve. Telling an
> administrator their subscription lapsed when the network merely blipped is the
> worst thing it could do.

| # | Step | Expected | ✓ |
|---|---|---|---|
| 6.22 | Remove the admin group from the user while the app is open, then open Subscription | *"Not available to you"* — a refusal, **not** "something went wrong" | ☐ |

---

## Part 10 — No technical information in the front end

| # | Step | Expected | ✓ |
|---|---|---|---|
| 7.1 | **Staff** → More | Section reads **"Your Perfect HR"**, not "Modules" | ☐ |
| 7.2 | Staff → absent features | *"Not part of your workspace"*; **"Loans"**, never *"needs ohrms_loan"* | ☐ |
| 7.3 | Staff → queued features | *"Your company has these, coming to the app soon"* | ☐ |
| 7.4 | Staff → **About** | Workspace + Company only. **No** Address, **no** Build, **no** HR module list, **no** SHA-256 card | ☐ |
| 7.5 | Staff → anywhere | No `hr_`, no `ir.`, no `res.`, no model names, no config keys | ☐ |
| 7.6 | **Admin** → About | A **"Technical details"** block with Address, Build, HR modules, fingerprint check | ☐ |
| 7.7 | Admin → absent features | *"Loans — needs ohrms_loan"* is back | ☐ |
| 7.8 | Admin → Address row | The **canonical** `web.base.url` host, not whatever the phone dialled | ☐ |
| 7.9 | Any error anywhere | Plain English. No status codes, no error keys, no stack traces | ☐ |

### The one thing shown to everyone

| # | Step | Expected | ✓ |
|---|---|---|---|
| 7.10 | Normal live session | **No** "Live from your account" row — the unremarkable case is silent | ☐ |
| 7.11 | Flip to mock data | **"Sample data (development)"**, amber, **for staff as well as admins** | ☐ |

> A real session quietly sitting on fabricated figures is the one thing on that
> screen that could make somebody act on a number that is not real. A previous
> build shipped exactly that.

### Proving the gate is server-side, not cosmetic

| # | Step | Expected | ✓ |
|---|---|---|---|
| 7.12 | As **Staff**, call `GET /api/mobile/v1/me/capabilities` with their bearer token | `hr_modules_installed` is `[]`, `expected_app` is `{}`, `is_workspace_admin` is `false` | ☐ |
| 7.13 | As **Staff**, call `GET /api/mobile/v1/me/subscription` | **403** `subscription_forbidden` — no plan data in the body at all | ☐ |

> This is the one that matters. Hiding these in the app would leave them in
> logs, crash reports and whatever a proxy kept.

---

## Part 11 — Regression sweep

Run after everything else; these are the previously shipped bugs.

| # | Check | Expected | ✓ |
|---|---|---|---|
| 8.1 | More → **Mobile App** root menu in Odoo | Present for `base.group_user`, with *Pair My Phone* and *My Paired Devices* | ☐ |
| 8.2 | Home after check-**out** | Buttons still present (`canCheckIn` includes `checkedOut`) | ☐ |
| 8.3 | Home and Attendance tab | **Agree** on the state — no screen showing buttons the other hides | ☐ |
| 8.4 | Approve an override without a security key | An anomaly row is written in `sec_core` and **survives** the refusal | ☐ |
| 8.5 | Odoo → Attendances list | No duplicate rows from any test above | ☐ |
| 8.6 | Odoo log after the whole run | No tracebacks | ☐ |

> 8.4 was invisible before: the alert was written on the same cursor as the
> `UserError`, so every one rolled back and the table was always empty.

---

## What is **not** verified

- **The 117 Odoo server test methods have never been run.** No Odoo or
  PostgreSQL on the development workstation. See §1.
- **None of this has been exercised on a physical handset by me** — every
  Flutter test is a widget/unit test against stubs.
- The geofence has never been tested against real GPS drift, only against
  synthetic coordinates.
