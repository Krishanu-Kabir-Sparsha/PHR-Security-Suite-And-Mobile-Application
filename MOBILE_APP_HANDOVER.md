# Perfect HR Mobile — Handover

**Last updated:** 2026-09-24
**Audience:** a developer picking this up cold, in a fresh workspace, with no memory of the conversations that produced it.

Read sections 1–5 before touching anything. Section 12 is the list of things that
have already cost time; skipping it means paying for them again.

> Supersedes `perfect_hr_mobile/PERFECT_HR_MOBILE_PROJECT_STATE.md`, which stopped
> being updated at "Session 4" and is now badly out of date. Treat that file as
> historical only.

---

## Contents

1. [What this is](#1-what-this-is)
2. [Where everything lives](#2-where-everything-lives)
3. [Current state at a glance](#3-current-state-at-a-glance)
4. [Authentication — the important part](#4-authentication--the-important-part)
5. [What is NOT done](#5-what-is-not-done)
6. [The API surface](#6-the-api-surface)
7. [App structure](#7-app-structure)
8. [Build and signing](#8-build-and-signing)
9. [Deploying the server side](#9-deploying-the-server-side)
10. [Testing](#10-testing)
11. [Source control state](#11-source-control-state)
12. [Landmines](#12-landmines)
13. [Open questions](#13-open-questions)

---

## 1. What this is

Perfect HR is an Odoo 18 deployment with a custom security suite (nine `sec_*`
modules) plus Open HRMS community HR modules. **Perfect HR Mobile** is a Flutter
app that talks to it.

There are two halves, and they must be changed and deployed together:

| Half | What it is | Language |
| --- | --- | --- |
| **The app** | Flutter, Android-first | Dart / Kotlin |
| **The API** | An Odoo module, `perfecthr_mobile_api` | Python |

The app does **not** use Odoo's web session or JSON-RPC. `perfecthr_mobile_api`
exposes a plain REST surface with bearer tokens, deliberately: the client's
networking layer wants a bearer token and a refresh endpoint, and having Odoo
issue them removed a whole component (Keycloak) from the original design rather
than adding one. Keycloak fields still exist in `AppConfig` and are **dead** —
ignore them.

**Authorisation is never done in the app.** The app asks
`GET /me/capabilities` what to show, but every read and write is authorised
server-side against the user's real Odoo groups, record rules, and the security
suite's guards. A tampered client can change what its own menus look like and
nothing else. Do not move an authorisation decision into Dart.

---

## 2. Where everything lives

Everything is on one Windows machine.

```
E:\sec_security_suite_addons\                 <- git repo root, working copy
├── perfect_hr_mobile\                        <- THE FLUTTER APP
├── Edited Fixed Versions\                    <- SOURCE OF TRUTH for all Odoo modules
│   ├── perfecthr_mobile_api\                 <- the REST API module
│   ├── sec_webauthn_auth\                    <- device binding + passkeys live here
│   ├── sec_plaza_rbac\                       <- roles, the Security Suite root menu
│   ├── sec_override_engine\                  <- override approvals
│   └── sec_*\                                <- the rest of the suite
├── All Addons\                               <- reference copies of Open HRMS modules
├── PerfectHR-release.apk                     <- the latest built APK, ~59.7 MB
└── MOBILE_APP_HANDOVER.md                    <- this file
```

**`Edited Fixed Versions` is the source.** You edit there, then copy to Odoo's
addons path to deploy. Editing the deployed copy directly is how work gets lost.

| Thing | Value |
| --- | --- |
| Odoo addons path | `C:\Program Files\Odoo 18\server\custom addons\` |
| Odoo Python | `C:\Program Files\Odoo 18\python\python.exe` (3.12.3) |
| Database | `Test_2` |
| Server host | `https://dev.perfecthr.net` |
| App API base | `https://dev.perfecthr.net/api/mobile/v1` (dev flavour, the default) |
| WebAuthn `rp_id` | `dev.perfecthr.net` |

Writing to `C:\Program Files` **requires an elevated shell.** A robocopy from a
normal shell will appear to hang or silently do nothing.

### Module versions as of this writing

| Module | Version |
| --- | --- |
| `perfecthr_mobile_api` | 18.0.1.11.0 |
| `sec_webauthn_auth` | 18.0.1.9.0 |
| `sec_plaza_rbac` | 18.0.1.5.0 |
| `sec_audit_locker` | 18.0.1.2.1 |
| `sec_surveillance_dashboard` | 18.0.1.2.0 |
| `sec_core` | 18.0.1.1.0 |
| `sec_forensic_reporting` | 18.0.1.1.0 |
| `sec_record_freeze` | 18.0.1.1.0 |
| `sec_declaration_gateway` | 18.0.1.0.0 |
| `sec_override_engine` | 18.0.1.0.0 |

---

## 3. Current state at a glance

### Works, tested on a real handset

- **Pairing a phone** to an account with a code from the web
- **Sign-in**: password, then the phone's fingerprint/screen lock
- **Session handling**: bearer token, silent refresh, sign-out
- **Security & devices** screen: status, device list, pair/unpair

### Built, and reaches real server data, but not yet exercised end to end by a human

- Employee Home (`/me/home`)
- Attendance check-in / check-out
- Leave: balances, apply, cancel
- Override approvals queue, approve (fingerprint-gated) and reject

### Built as placeholder screens only

Seven routes render `ScreenPlaceholder`. They navigate and look right and show
nothing real: `authMfa`, `authBiometric`, `checkInConfirmation`,
`attendanceCalendar`, `attendanceCorrection`, `requestDetail`, `approvalDetail`,
plus the deeper `team*`, `workforce*`, `payroll*`, `recruitment*`, `insights*`,
`notifications` and `search` routes.

### Feature directories that exist but contain zero Dart files

`ai_assistant`, `executive_intelligence`, `interview`, `learning`,
`notifications`, `payroll`, `performance`, `productivity`, `recruitment`,
`requests`, `skill_gap`, `team`, `workforce`.

They are scaffolding from an early session. **An empty directory here means
"planned", not "started".**

### Quality gates

- `flutter test` — **294 passing**, 0 failing
- `flutter analyze` — **0 errors, 0 warnings** (infos remain: trailing commas,
  `prefer_const`, directive ordering — all pre-existing and cosmetic)
- Server tests exist for device binding (24 cases in
  `sec_webauthn_auth/tests/test_device_binding.py`) but **have not been run**
  against a live database.

---

## 4. Authentication — the important part

This is the part with the most history and the most non-obvious decisions. If
you read nothing else, read this.

### 4.1 Why the app does not use passkeys

The original design was WebAuthn passkeys everywhere. **It does not work for a
native Android app on this deployment.**

Reaching a passkey from a native app requires the OS vendor to validate an
app-to-domain association on the handset — Digital Asset Links on Android,
Associated Domains on Apple. When that validation fails it fails closed, with:

```
[50152] RP ID cannot be validated
```

This was chased to exhaustion. `assetlinks.json` was served correctly over HTTPS
with the right package and fingerprint; **Google's own Digital Asset Links API
validated the association**; the APK was verified signed with the matching key.
The refusal happened inside Google Play Services on the handset, where there is
no server-side fault to correct, no actionable error, and a cache we cannot
flush.

**Conclusion: a vendor's cache must not sit in the critical path of signing in.**

### 4.2 What replaced it: device binding

The app generates **its own Ed25519 keypair**. No platform vendor is consulted.

Common misconception, stated because it came up: **there is no split key and
nothing is "matched".** Each device makes a complete keypair. The private half
never leaves the device. The server stores only public halves and verifies
*signatures*.

**Pairing:**

1. User, signed in on the **web**, opens
   **Security Suite → Authenticators → Pair a Device**
2. Server mints an 8-character code (Crockford alphabet — no I, L, O, U),
   **10 minutes**, **single use**, dead after **5 wrong attempts**, stored only
   as a SHA-256 digest
3. In the app: **Pair this device** on the sign-in screen, enter username + code
4. App generates the keypair, sends **only the public half**
5. Server stores it and returns an opaque device handle

The login must accompany the code — a stolen code alone binds nothing.

**Sign-in:**

1. Password → server
2. Server sees the account has a paired device, returns
   `{mfa_required: true, mfa_method: "device", mfa_token, device_challenge}`
3. App asks for the fingerprint/screen lock, which releases the private key
4. App signs and posts the signature
5. Server verifies against the stored public key, then issues the token

**No token exists until both factors pass.**

### 4.3 What gets signed

```
perfecthr-device-v1\n{challenge}\n{context_ref}\n{handle}\n{counter}
```

Newline-joined because every field is base64url, a `model,id` reference, or a
decimal integer — none can contain a newline, so it is unambiguous without
length prefixes.

- **`context_ref`** is what makes a signature bind to **one action**. A
  confirmation given to sign in cannot be replayed as an override approval. This
  is the single most important property here; there is a test named for it.
- **`counter`** only ever increases. A repeat means one key is in use from two
  installations — the same signal WebAuthn's `signCount` carries.
- **`perfecthr-device-v1`** is a domain tag. Change what is signed → bump it.
  The app sends its version so a mismatch is a clear refusal rather than a
  signature that mysteriously fails to verify.

### 4.4 How it sits inside the existing security suite

A paired device is stored as a **`sec.webauthn.credential` with
`mechanism = 'bound_device'`**, not in a parallel model. That was deliberate:
the two-device rule, revocation, the reset wizard, clone detection and
`override.approval.credential_id` all keep working unchanged, while `mechanism`
keeps the approval evidence honest about which proof was actually given.

`verify_device_signature()` sets the **same** request-scoped marker
(`request.sec_webauthn_verified_for`) that the passkey path sets, which
`override_approval._assert_webauthn_confirmed()` already reads. **The override
engine needed no change at all.**

Two consequences worth knowing:

- Bound devices are filtered **out** of `allowCredentials`. No browser or
  credential manager can satisfy one, so offering it would strand the user
  mid-ceremony.
- A counter regression **refuses and raises a critical anomaly, but does not
  auto-revoke**. The passkey path does revoke on a clone and can afford to —
  those credentials approve. This one signs in, and the likeliest benign cause
  (a restored device backup) would lock out a user who did nothing wrong.

The anomaly is written on a **separate cursor** (`self.pool.cursor()`), because
the caller raises immediately afterwards and a same-cursor write would be rolled
back by its own refusal. `sec_record_freeze/models/freeze_mixin.py` documents
the same trap.

### 4.5 Passkeys are not gone

They still work **in the browser** and remain preferred there. The web enrolment
page is untouched. What was removed is the *native in-app* passkey ceremony,
which cannot complete.

`EnrolmentController` and its tests are **kept**, unused by any widget. If the
association ever validates, re-enabling is one widget away.

### 4.6 Android hardening

`android:allowBackup="false"` plus `res/xml/data_extraction_rules.xml` excluding
everything, for both cloud backup and device-to-device transfer.

**This is a security decision, not tidiness.** A backup carrying the signing key
would let it be restored onto a second handset — two installations, one key,
both able to sign in and approve as the same person. Detection after the fact is
worse than the key never leaving. The cost is that replacing a phone means
pairing again.

---

## 5. What is NOT done

Stated plainly, because the user's own words were *"nothing is already finished
as per my requirement"*, and that is fair.

1. **Override approvals have never been run end to end by a human.** The code
   path is complete and unit-tested on both sides; no one has raised a real
   override on the web and approved it from the phone. **This is the highest-value
   next test** — it is what the whole security suite exists for.
2. **Attendance and Leave have not been exercised** against real data by a
   person, only by tests.
3. Most of the app is placeholder screens (section 3).
4. **iOS has never been built or run.** The device-binding code is written to be
   cross-platform (`local_auth` and `flutter_secure_storage` both support
   Android, iOS, macOS, Windows; Ed25519 is pure Dart), but this is *designed*
   portability, not *demonstrated* portability. Expect at minimum: signing setup,
   `NSFaceIDUsageDescription` in `Info.plist`, and a Keychain access-group review.
5. **Server-side tests have never been executed.** Written, syntax-checked, not
   run.
6. **Nothing is committed to git** (section 11).
7. The two passkeys on the primary test account are both in **one** Google
   Password Manager keychain. Numerically that satisfies "2 of 2"; in substance
   it is one credential store. For a Tier 3 approver that is a single point of
   failure worth flagging to whoever owns the policy.

---

## 6. The API surface

All under `https://dev.perfecthr.net/api/mobile/v1`. Every route is declared
`type="http"`, `auth="public"`, `csrf=False`, `save_session=False`, with
authorisation done by the `@authenticated` decorator in
`controllers/common.py`.

`auth="public"` does **not** mean unauthenticated — Odoo's `auth="user"` means a
*session cookie*, which a mobile client does not have. `@authenticated` resolves
the bearer token and switches the request to that user with `update_env`, so
every ORM call below runs under their real ACLs and record rules. Nothing is
sudo'd.

| Endpoint | Method | Auth | Notes |
| --- | --- | --- | --- |
| `/auth/login` | POST | none | Returns a token **or** an MFA demand |
| `/auth/login/device` | POST | none | Completes with a paired-device signature |
| `/auth/login/webauthn` | POST | none | Completes with a passkey assertion |
| `/auth/refresh` | POST | none | Rotates the pair; old pair revoked |
| `/auth/logout` | POST | bearer | Revokes **only** the presented token |
| `/device/pair` | POST | **none** | See below |
| `/me/capabilities` | GET | bearer | Feature matrix, roles, permissions |
| `/me/home` | GET | bearer | Employee home payload |
| `/me/attendance` | GET | bearer | |
| `/me/attendance/toggle` | POST | bearer | Check in / out |
| `/me/leave` | GET | bearer | Balances and requests |
| `/me/leave/apply` | POST | bearer | |
| `/me/leave/<id>/cancel` | POST | bearer | |
| `/me/authenticators` | GET | bearer | Status + device list with `mechanism` |
| `/me/authenticators/step-up` | POST | bearer | Passkey path only |
| `/me/authenticators/options` | POST | bearer | Passkey path only |
| `/me/authenticators/verify` | POST | bearer | Passkey path only |
| `/me/approvals` | GET | bearer | Override queue |
| `/me/approvals/<id>/challenge` | POST | bearer | Returns `method` + challenge |
| `/me/approvals/<id>/approve` | POST | bearer | Takes assertion **or** signature |
| `/me/approvals/<id>/reject` | POST | bearer | **Deliberately not gated** |

**`/device/pair` takes no bearer token, and cannot.** A new handset has no
session until it is paired, so requiring one would be circular — that
circularity is the "ordering trap" that used to force a detour through Chrome on
every new phone. The pairing code carries the authority instead.

**Rejecting an override needs no device confirmation.** This asymmetry is
deliberate and there is a test asserting it: an approval can change a frozen
record and a rejection cannot, and putting a fingerprint prompt between a
reviewer and "no" puts friction on the safe answer.

### Two gates every bearer request passes

Both live in `controllers/common.py`:

1. **The Unified Declaration gate.** `sec_declaration_gateway` hooks
   `ir.http._dispatch` and keys on `request.session.uid`; a bearer request has no
   session, so that hook never fires for mobile. Left alone the app would be a way
   *around* a control whose entire purpose is to be unavoidable. Re-implemented
   here, answering **403 with a machine-readable code** — never the gateway's 303
   redirect to HTML, which a JSON client would report as a parse error.
2. **The enrolment gate.** A token issued on a password alone carries
   `enrolment_required` and reaches only the paths in `ENROLMENT_ONLY_PATHS`.
   Without it, "everyone must confirm on a device" would be advice.

---

## 7. App structure

Feature-first, four layers per feature: `domain` → `data` → `application` →
`presentation`. State is **Riverpod**; navigation is **GoRouter** with a
`StatefulShellRoute` whose branch set is derived from the role's `NavProfile`.

```
lib/
├── core/
│   ├── config/         AppConfig — flavours, API base URL
│   ├── networking/     ApiClient (Dio), AuthInterceptor, DioFailureMapper
│   ├── routing/        app_router.dart, app_routes.dart
│   ├── security/       device_key_service.dart  <- THE keypair + biometric
│   │                   passkey_service.dart     <- MethodChannel to Kotlin
│   │                   second_factor.dart       <- SecondFactorMethod enum
│   ├── session/        session_controller.dart, user_role.dart
│   ├── storage/        Drift cache (deliberately UNENCRYPTED — see below)
│   └── theme/          AppPalette, AppSpacing, AppTypography
├── features/           see section 3
└── shared/             reusable widgets, ScreenPlaceholder
```

**The Drift cache is unencrypted on purpose** (logged risk R9). It is acceptable
*only* while sensitive material stays out of it. Bearer tokens and the
paired-device private key go in `flutter_secure_storage`
(Keystore/Keychain/DPAPI) and must never be written to Drift.

### Roles

`UserRole`: `employee`, `manager`, `hr`, `chro`, `executive`, `superAdmin`. The
wire values come from `ROLE_MAP` in `controllers/auth.py`, mapping Odoo groups to
mobile role strings. `navProfileFor()` currently returns the employee surface for
**every** role — a deliberate earlier fix, because the privileged profiles
pointed at screens that were never built, so a super-admin saw five placeholders
and nothing else.

### Key files for authentication

| File | What it does |
| --- | --- |
| `lib/core/security/device_key_service.dart` | Keypair, secure storage, biometric gate, signing |
| `lib/features/authentication/application/auth_providers.dart` | Sign-in orchestration, both second-factor paths |
| `lib/features/authentication/application/pair_device_controller.dart` | Pairing |
| `lib/features/authentication/presentation/pair_device_screen.dart` | AUTH-05 |
| `android/.../MainActivity.kt` | **Must** be `FlutterFragmentActivity` — see section 12 |

Server side:

| File | What it does |
| --- | --- |
| `sec_webauthn_auth/models/device_binding.py` | Pairing codes, signature verification |
| `sec_webauthn_auth/wizard/device_pair_wizard.py` | The web "Pair a Device" screen |
| `perfecthr_mobile_api/controllers/device.py` | `/device/pair` |
| `perfecthr_mobile_api/controllers/auth.py` | Sign-in, both MFA branches |

---

## 8. Build and signing

```bash
cd E:/sec_security_suite_addons/perfect_hr_mobile
flutter pub get
flutter analyze          # expect 0 errors, 0 warnings
flutter test             # expect 294 passing
flutter build apk --release
cp build/app/outputs/flutter-apk/app-release.apk ../PerfectHR-release.apk
```

Takes roughly 7 minutes cold, ~2 minutes warm. Output is ~59.7 MB.

### Signing

| | |
| --- | --- |
| Keystore | `android/app/upload-keystore.p12` (PKCS12, alias `perfecthr`) |
| Password | `android/key.properties` |
| In git? | **No — both gitignored, deliberately** |
| SHA-256 | `8A:15:E3:11:C2:BD:60:AD:97:7A:BF:3E:B9:BA:7C:9A:F5:A1:39:87:8D:A3:79:8A:FA:3D:BE:19:86:DB:F2:83` |

`build.gradle.kts` falls back to the debug key when `key.properties` is absent,
so **a release build can silently produce an unsigned-for-production APK.** Check
the file exists before trusting a build.

**The keystore is irreplaceable for app updates.** Android identifies an app by
its signing certificate; losing it means no installed copy can ever be updated
under the same identity.

**It no longer gates authentication.** Since device binding, sign-in does not
depend on the fingerprint at all. `assetlinks.json` and
`sec_webauthn.android_sha256` still exist for the passkey path, so keep them
correct — but **do not diagnose a sign-in failure by looking at the fingerprint.
Check the pairing first.**

### Installing

**Install over the top. Do not uninstall first.** An update preserves app data,
so the pairing survives. Uninstalling wipes the keystore entry and the user needs
a fresh pairing code.

---

## 9. Deploying the server side

From an **elevated** shell, per module:

```powershell
robocopy "E:\sec_security_suite_addons\Edited Fixed Versions\<module>" `
         "C:\Program Files\Odoo 18\server\custom addons\<module>" `
         /MIR /XD __pycache__
```

Then upgrade the module on `Test_2` (Apps → search → Upgrade, or `-u <module>`).

`/XD __pycache__` matters — stale `.pyc` files from a different Python cause
confusing import errors.

After any change to `sec_webauthn_auth`, also upgrade `perfecthr_mobile_api` and
`sec_override_engine`: they inherit from it.

### One-time server configuration

System parameters under Settings → Technical → Parameters:

| Key | Value |
| --- | --- |
| `sec_webauthn.rp_id` | `dev.perfecthr.net` |
| `sec_webauthn.origin` | `https://dev.perfecthr.net` |
| `sec_webauthn.android_package` | `com.perfecthr.perfect_hr_mobile` |
| `sec_webauthn.android_sha256` | the fingerprint above |
| `web.base.url` | `https://dev.perfecthr.net` |

`rp_id` is **permanent**. Changing it invalidates every enrolled passkey. It does
*not* affect paired devices, which do not use it.

---

## 10. Testing

### Automated

```bash
cd perfect_hr_mobile && flutter test          # 294 tests
```

Server tests (**never yet run**):

```
odoo -d Test_2 -u sec_webauthn_auth --test-enable --stop-after-init
```

The device-binding suite deliberately concentrates on the ways a signature must
**not** be accepted: replayed, rebound to a different action, stale counter,
another person's device, forged. It is our own protocol rather than a standard
someone else has already attacked, so that emphasis is on purpose.

### Manual, in priority order

1. **Override approvals** — the untested path.
   Raise an override on the web (**Security Suite → Overrides → Override
   Requests**), make the test account a reviewer on a tier, then approve from
   **More → Override approvals** on the phone. Expect a fingerprint prompt naming
   the specific override. Afterwards check `override.approval` records the
   **paired device**, not a passkey.
2. Attendance check-in/out, and confirm it on the web.
3. Leave: balances, apply, cancel.
4. **Negative cases, which matter more than the happy path:**
   - Dismiss the fingerprint prompt → no error shown, not signed in
     (cancelling is a decision, not a fault)
   - Wrong password → refused, and **no fingerprint prompt at all**
   - Unpair, then sign in → told where to get a pairing code
   - Reject an override → **no** fingerprint prompt

---

## 11. Source control state

```
branch: main
commits: 2ff8d2a "Mobile App Added", 8e66675 "Ready Scaffold"
uncommitted: ~60 files
```

**Nothing from any of the device-binding work is committed.** All of section 4 —
`device_binding.py`, `device.py`, `device_key_service.dart`,
`pair_device_screen.dart`, the wizard, the tests — is untracked or modified in
the working tree only.

The user has never asked for a commit, which is why there is none. **Committing
should be an early action in the next session**, because right now a single bad
`git checkout` loses several days of work.

Also untracked: `All Addons/` (large, reference copies) and `.idea/`. Decide
whether those belong in the repo before a blanket `git add`.

---

## 12. Landmines

Every one of these has already cost real time.

**`MainActivity` must extend `FlutterFragmentActivity`.**
`local_auth` raises `androidx.biometric.BiometricPrompt`, a Fragment, which needs
a `FragmentManager`. `FlutterActivity` extends `android.app.Activity` and has
none, so every `authenticate()` call fails instantly with `no_fragment_activity`
and **no prompt ever appears**. Changing this back silently disables the second
factor on every Android handset.

**Never treat an unrecognised platform error as a cancellation.**
An earlier `_confirmPresence` returned `false` for any unknown error, which
upstream reads as "the user changed their mind" — shown silently, by design. The
result was a Sign in button that did nothing and said nothing, and it hid the
bug above for a whole round. Silence must mean a decision. There is a regression
test named for this.

**Odoo module names here are Open HRMS, not Enterprise.**
`hr_payroll_community` not `hr_payroll`; `oh_appraisal` not `hr_appraisal`. Get
one wrong and the capability matrix silently drops the feature. A server test
checks every name in `FEATURE_MATRIX` against `ir.module.module` — keep it.

**`--` is illegal inside an XML comment.** It has broken data files twice. Use
an em dash.

**`ref()` to a module not in `depends` fails at install.** `sec_plaza_rbac`
depends only on `base` and `mail`, so HR group refs are unsafe there. `sec_core`
depends on `sec_plaza_rbac`, so Plaza refs **are** safe in `sec_webauthn_auth`.

**An anomaly written just before `raise` is rolled back with it.** Use
`self.pool.cursor()`. See `freeze_mixin._raise_anomaly_out_of_band`.
**Known outstanding instance:** `override_approval.py:181` writes its
"approval attempted without WebAuthn" alert on the same cursor and then raises,
so that alert is lost. Found but not fixed — out of scope at the time.

**Heredocs and `\n`.** Writing Dart/Python/XML through shell heredocs repeatedly
corrupted files by turning `\n` into literal newlines or literal backslash-n.
Use a file-writing tool, or a quoted (`<<'EOF'`) heredoc containing a Python
script that does exact string replacement.

**Do not ship a button that cannot work.** "Add this device" ran the native
passkey ceremony and always returned `[50152]`. It made the app look broken
rather than differently configured. It has been removed; the comment explaining
why is in `security_screen.dart` so it does not come back.

**The Plaza RBAC access matrix is declarative.** It never writes
`ir.model.access`. Gate UI on Odoo's own `has_access`, never on the catalog. The
catalog supplies duty semantics only (tier, create-vs-approve).

---

## 13. Open questions

These need a decision from the product owner and block specific work:

1. **Is `dev.perfecthr.net` the permanent host?**
   `rp_id` is permanent — changing it discards every enrolled passkey. If
   production will be `perfecthr.net` or a different host, settle that *before*
   more passkeys are enrolled. Paired devices are unaffected either way.

2. **Is iOS in scope, and when?**
   The device-binding design is cross-platform by construction but has never been
   built or run on Apple hardware. If iOS matters, budget for signing, Info.plist
   entries, and a Keychain review — and test it before assuming it works.

3. **Which of the placeholder screens actually matter?**
   Thirteen empty feature directories is a plan, not a backlog. The stated
   intent was *"whatever modules are installed on the server, everything should
   be there in the app"*, built gradually — `/me/capabilities` already reports
   what the server has, so that list is the natural starting point.

4. **Should `All Addons/` be committed?**
   It is large and consists of reference copies of third-party modules. Decide
   before the first real commit.
