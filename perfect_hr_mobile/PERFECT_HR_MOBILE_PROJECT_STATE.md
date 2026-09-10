# PERFECT HR MOBILE — PROJECT STATE

> Continuity file per Project Instructions §32–34.
> **Read this before starting any work.** Commit it with the code; it is the
> only continuity mechanism across conversation threads.

---

## PROJECT STATUS

**Session 4 complete — Task 4 (E-01 Employee Home), plus build tooling and a toolchain-free static checker.**

| Field | Value |
| --- | --- |
| CURRENT PHASE | Phase 1 — Mobile Foundation (Tech-Stack §31) |
| CURRENT SPRINT | Sprint 1 — Foundation |
| CURRENT FEATURE | — |
| CURRENT SCREEN | — |
| LAST COMPLETED TASK | **Task 4** — E-01 Employee Home: domain model, PROPOSED `GET /me/home`, live + mock repositories, providers, five sections, all six states, 1 test suite (~30 cases). Also: CI/build tooling, `scripts/static_checks.py` |
| CURRENT TASK | None in flight |
| NEXT TASK | **Task 5 — E-02/E-03 Attendance.** Blocked on Q7 (which attendance modes are in Release 1). Task 3 (auth) remains blocked on Q5. |
| LAST UPDATE DATE | 2026-09-07 |

**Cumulative:** 56 Dart files — ~7,600 lines in `lib/`, ~2,400 in `test/`, 9 suites.

**Task order note:** Task 3 (authentication) was skipped, not forgotten. It is
blocked on Q5 and cannot be built against placeholder Keycloak coordinates.
Task 4 was brought forward because it has no external dependency — the dev role
switcher supplies a session, and the mock repository supplies data.

---

## ENVIRONMENT / REPOSITORY

- Flutter project at `perfect_hr_mobile/`
- Minimum Flutter 3.27 / Dart 3.6
- **No Dart/Flutter toolchain in the authoring environment.** `flutter analyze`
  and `flutter test` have still NOT been executed for Task 1 or Task 2 (R7).
- **Drift code generation is now required to compile.**
  `core/storage/app_database.dart` declares `part 'app_database.g.dart'`, so
  `dart run build_runner build` must run after `flutter pub get`.

### Continuity Mechanism Warning

The authoring environment's filesystem does not persist between conversations.
At the end of every session: **commit the code** to GitHub, and **re-upload
this file** into the Claude Project.

---

## COMPLETED FEATURES

### Task 1 — Design System & Application Shell ✅

Design tokens (`AppPalette`, `AppTextStyles`, spacing/radius/elevation/motion),
light and dark themes, role-aware shell and bottom navigation for all five
profiles, GoRouter with every Release 1 screen ID reachable, session and
permission scaffolding, the six global UX states with `AsyncStateView`, base
components (`AppCard`, `KpiCard`, `StatusBadge`, `TrendIndicator`,
`AppProgressBar`), and the AI component set with trust rules enforced by
constructor contract. Zero hard-coded colour literals outside the token file.
See AD-11…AD-16.

### Task 2 — Networking, Error Mapping & Local Persistence ✅

**Networking** (`lib/core/networking/`)
- `api_client.dart` — `buildDio()` assembling base options (12s connect, 30s
  receive for AI endpoints, 20s send) and the interceptor chain. A separate
  bare `Dio` handles replays so refresh and retry cannot recurse through their
  own interceptors. `ApiClient` is the typed wrapper, and its single guarantee
  is that **every** error crossing into the app is an `AppFailure` — no
  repository or screen ever sees a `DioException` or a status code.
- `dio_failure_mapper.dart` — the one place HTTP becomes domain language.
  400→Validation, 401→SessionExpired, 403→Permission, 404→NotFound,
  409→Validation ("already been updated"), 422→Validation with field errors,
  429→Network ("too many requests"), 503→Server ("temporarily unavailable"),
  other 5xx→Server, unexpected→Unknown. Timeouts→Network; connection error→
  Offline when connectivity reports offline, else Network; bad certificate→
  Server and not retryable, since retrying through a hostile network is not a
  remedy. **Server error text is distrusted by default:** only `user_message`
  renders, and only after length, newline and pattern checks that reject
  tracebacks, SQL, `odoo.`/`psycopg` strings and over-long free text.
  Diagnostics record method, path, status and type — never the request body.
- `retry_interceptor.dart` — retry split into a pure `RetryPolicy` so the rule
  is directly testable. GET/HEAD/OPTIONS retry on timeouts, connection errors
  and 429/502/503/504. **Mutations are never replayed without an
  `Idempotency-Key`**, and even with one are not replayed once a response
  arrived, because the server may have applied the change before failing to
  report it. Exponential backoff with full jitter.
- `auth_interceptor.dart` — bearer injection plus **single-flight** refresh on
  401 (a dashboard fanning out on resume must trigger one refresh, not one per
  request, or refresh-token rotation invalidates the whole set), with exactly
  one retry. `AuthTokenStore` is the seam Task 3 implements; the default
  `UnauthenticatedTokenStore` sends no header rather than silently bypassing.
- `logging_interceptor.dart` — installed only in the dev flavour, and redacts
  even there: `Authorization`/cookies masked, body keys matching ~20 sensitive
  fragments (salary, bank, nid, dob, phone, email, otp…) masked recursively,
  bodies size-capped.
- `api_headers.dart` — correlation ID, client app/version/platform, idempotency
  key, and Dio `extra` keys. Documents why **no tenant header is sent**: a
  client-supplied tenant value would be attacker-controlled input on the
  tenant-isolation path.
- `connectivity_service.dart` — interface, `connectivity_plus` implementation
  and `FakeConnectivityService`; optimistic-online default; idempotent
  `initialise()`. Documents that the plugin reports interface availability, not
  reachability. `requireLiveConnection()` guards actions that must not succeed
  offline (check-in, approvals, submissions).

**Data layer** (`lib/core/data/`)
- `cache_policy.dart` — `CachePolicy.ttl` / `.revalidate` / `.never`, plus
  conventional constants: `dashboard` (2 min), `activityList` (5 min),
  `profile` (12 h), `reference` (1 day), `sensitive` (never). Expressing "never
  cache payroll" as a policy rather than a rule each feature must remember is
  what makes it enforceable.
- `cache_store.dart` — `CacheStore` contract, `CacheScope` (tenant + user),
  `CacheKeys`, and `InMemoryCacheStore` that round-trips through JSON so tests
  cannot pass on object identity alone.
- `cached_resource.dart` — read strategy: fresh cache → live fetch →
  stale-cache fallback on transport failure → propagate. **Permission and
  validation failures never fall back to cache**, because the server has given
  an authoritative answer and access may have been revoked since the write. A
  `CachePolicy.never` resource is neither written nor served, and fails offline
  with `ConnectionRequiredFailure`. Undecodable entries are dropped, not
  raised, so a schema change cannot block a working online read.
- `data_providers.dart` — database/store/scope providers, `DataSourceMode`
  (live by default even in dev; mock is opt-in and dev/qa only), and
  `cacheLifecycleProvider`, which **purges cached data on sign-out and when a
  different principal signs in on the same device**, plus a 7-day sweep at
  start-up.

**Storage** (`lib/core/storage/app_database.dart`)
- Drift `CacheEntries` table keyed on (scope, entryKey) with JSON payload and
  `syncedAt`; `DriftCacheStore` implements `CacheStore`.
- Deliberately a generic key/JSON table rather than ten typed schemas: the
  mobile API contracts do not exist yet (Q4), and designing schemas against
  unknown endpoints would be inventing requirements. Typed tables arrive per
  feature, with migrations.
- **Not encrypted at rest**, acceptable only because cache policy keeps
  sensitive data out of it. Documented in-file and raised as Q8.

**Analytics** (`lib/core/analytics/telemetry.dart`)
- Closed `AnalyticsEvent` taxonomy covering the UI-UX §60 adoption metrics.
- `TelemetryGuard` filters at the sink: denylisted key fragments
  (compensation, identity, banking, credentials, free text) plus a value-shape
  check that rejects structured values and strings over 40 characters, since
  free text is where personal data hides. Drops rather than throws — an
  over-eager analytics call should lose a dimension, not break a check-in.
- Sinks: `DebugTelemetry` (dev, local log only) and `NoopTelemetry`. No
  production sink yet, pending Firebase project files (Q9).

**Wiring**
- `main.dart` resolves connectivity before the first frame. `app.dart` holds
  `cacheLifecycleProvider` alive for the app run — without a holder the
  provider would never be created and cached HR data would survive logout —
  and emits `app_opened`.

**Tests added** (~1,080 lines)
- `dio_failure_mapper_test.dart` — every status code; timeout, offline and
  certificate handling; and a leakage group asserting that user-facing strings
  contain no status code, no request path, no traceback, no `psycopg2` and no
  over-long free text, while diagnostics retain method/path/status but not the
  payload.
- `retry_policy_test.dart` — reads retry, mutations do not, idempotency-keyed
  POSTs retry on connection failure but not after a response arrived,
  certificates and cancellations never retry, attempt budget, jitter bounds.
- `cached_resource_test.dart` — cold read, fresh hit avoids the network,
  expiry, forceRefresh, stale fallback preserving the original `syncedAt`,
  permission and validation failures not masked, payroll never written / never
  served / failing offline with custom copy, cross-scope isolation, prefix
  invalidation, age sweep, JSON round-trip, undecodable-entry recovery, and the
  live-connection guard.
- `telemetry_guard_test.dart` — compensation, identity, banking, credential and
  free-text keys dropped; categorical keys kept; `query_category` allowed while
  `ai_query` is not; long strings and structured values rejected.

---

### Task 4 — E-01 Employee Home ✅

The first real screen, and the first of the four flagship experiences
(Instructions §50). Its promise is "manage my HR life".

**Domain** (`features/dashboard/domain/employee_home_summary.dart`)
- `EmployeeHomeSummary` aggregate with `TodayAttendance`, `LeaveBalanceSummary`,
  `PerformanceSummary`, `PendingItem` and `HomeAiInsight`.
- Hand-written `fromJson`/`toJson` rather than Freezed, to avoid adding a
  second code-generation dependency to the build. The JSON round-trip is what
  the cache uses, and it is covered by tests.
- Unknown enum values fall back instead of throwing, so a newer backend cannot
  break an older client.
- `workedMinutes` comes from the server and is deliberately **not** derived on
  the client: break handling, shift rules and rounding are payroll-adjacent
  business logic (Instructions §7).
- `performance` and `delta_points` are nullable by design — a new joiner must
  not be shown a misleading 0% or 0-point change.

**Data** (`features/dashboard/data/employee_home_repository.dart`)
- `EmployeeHomeRepository` interface; `ApiEmployeeHomeRepository` over
  `ApiClient` + `CachedResource` with `CachePolicy.dashboard`.
- **PROPOSED API `GET /me/home`** fully documented in the class doc comment:
  auth, tenant, permission, pagination, cache, a complete example response, and
  five notes for the backend team.
- One aggregate endpoint rather than six parallel calls: a home screen that
  fans out is slow on the target market's networks and cannot be cached
  coherently (Instructions §25).
- `MockEmployeeHomeRepository` with values matching the Blueprint E-01
  wireframe exactly, so the rendered screen can be diffed against the spec. It
  also exposes `emptySample()` (first-day employee) and a `failWith` hook, so
  the empty and error paths can be exercised — the paths a demo dataset always
  hides.

**Application** (`features/dashboard/application/employee_home_providers.dart`)
- Mock/live selection happens once, in the repository provider, rather than
  feature code branching on a flag.
- Reading the provider without an authenticated session throws rather than
  writing to an unscoped cache namespace.
- `refresh()` keeps current data visible while refetching, so pull-to-refresh
  does not collapse the screen to a skeleton.

**Presentation**
- `TodayAttendanceCard`, `QuickActionsGrid`, `MyHrStrip`, `PendingItemsList`.
- `EmployeeHomeScreen` assembles them in the UI-UX §55 order:
  TODAY → Quick Actions → My HR → AI Insight → Pending.
- Actions route to the owning screen rather than posting from home: check-in
  belongs to E-02/E-03 where location verification and policy live, and a
  submission with no visible confirmation would be worse than a tap extra.
- The AI insight degrades a prediction that arrives without confidence to a
  descriptive insight, rather than crashing on the `AiInsightCard` assertion or
  overstating certainty (UI-UX §39).
- Header is outside the scroll area; the state view fills the rest and is
  wrapped in `RefreshIndicator`, so pull-to-refresh works from the error and
  offline states too.

**Tests** (~30 cases)
Section order and presence; greeting and job title; status, check-in time and
worked duration; check-in vs check-out affordance by state; notification count;
performance tile shown with a record and **omitted rather than zeroed**
without one; AI labelling for descriptive, predicted and
prediction-without-confidence cases; all six states including the
last-synchronized banner; empty pending reading as reassurance; full and
minimal payload parsing; unknown enum fallback; JSON round-trip; score
clamping; duration formatting; state-to-action gating.

### Build tooling ✅

- `.github/workflows/build.yml` (pre-existing, retained) — generates platform
  folders, applies Android config, runs codegen, uploads a debug APK.
- `scripts/configure_android.py` (pre-existing, retained) — the
  release-manifest `INTERNET` fix, `minSdk 23`, `appAuthRedirectScheme`,
  permissions.
- `scripts/build_apk.sh` — local equivalent of the CI pipeline.
- `BUILD.md` — both routes, what the current APK actually shows, and the traps.
- `scripts/static_checks.py` — toolchain-free checks for delimiter balance,
  named arguments against our own constructors, interface completeness, `part`
  directives and import resolution. **Not a substitute for `flutter analyze`**;
  it exists because this code is authored without a Dart SDK.

## IN-PROGRESS FEATURES

None.

## PENDING FEATURES

**Phase 1 — Foundation (remaining)**
- [ ] Task 3 — Keycloak OIDC + PKCE, secure storage, MFA, biometrics
      (AUTH-01…04, SET-02). **Blocked on Q5.**
- [ ] FCM registration and notification routing (with Task 8)
- [ ] Production telemetry / Crashlytics sink (blocked on Q9)
- [x] CI — GitHub Actions `build.yml`: generates platform folders, applies Android config, codegen, debug APK artifact
- [x] Android configuration script (`scripts/configure_android.py`) and local build script
- [ ] CI/CD — release signing, security scan, store deployment, blocking analyze/test

**Phase 2 — Employee:** E-01 … E-11, E-16, N-01, SET-01, AI-01, AI-02
**Phase 3 — Manager:** M-01 … M-06
**Phase 4 — HR:** H-01 … H-06 (scope pending Q1)
**Phase 5 — Executive:** X-01 … X-03 (scope pending Q1)

## IMPLEMENTED SCREENS

**E-01 Employee Home** — complete against Instructions §45: UI, five sections
in the §55 order, mock repository behind the production interface, PROPOSED API
contract documented, all six states, stale-data banner, permission model
considered (performance tile omitted when out of scope), telemetry, and ~30
test cases. Live API integration is the only outstanding item, and it is
blocked on Q4.

AUTH-01 has visual structure only. Every other Release 1 screen ID has a
reachable placeholder route — route coverage, not screen completion.

## PENDING SCREENS

All Release 1 screens. Deferred: E-12…E-15, M-07, M-08, H-07, AI-04
(Release 2); AI-05 and agentic workflows (Release 3).

---

## API IMPLEMENTED

None. The transport layer is ready; no endpoint is called yet.

## API PROPOSED

No endpoints formally specified. Task 2 established the contract *shape* the
backend must satisfy, which should be confirmed with the API team:

1. **Error envelope.** Non-2xx responses may carry `user_message` (a
   display-safe, localisable sentence) and `errors` (field → message, or field
   → [message]). The client renders `user_message` only; other body text is
   discarded. **If the backend cannot guarantee `user_message` is
   display-safe, it should omit the field** and the client will use its own
   copy.
2. **Status semantics.** 401 authentication, 403 authorisation, 409 workflow
   conflict, 422 validation. The client's UX depends on this separation — in
   particular 403 must not be used for "not in your data scope", which should
   be 404, or users will see a permission message for missing records.
3. **Idempotency.** The client sends `Idempotency-Key` on retryable mutations
   and expects the backend to collapse duplicates. Without server support the
   client will not retry submissions at all — safe, but a lost check-in on a
   flaky network becomes a user-visible failure.
4. **Correlation.** `X-Correlation-Id` is sent on every request; surfacing it
   in APISIX logs makes mobile issues traceable.

## DATABASE / LOCAL STORAGE STATUS

Drift schema v1: one scoped `CacheEntries` table. Not encrypted (Q8). Payroll,
bank and identity data excluded by cache policy. Purged on sign-out, on
principal change, and swept at 7 days.

## AUTHENTICATION STATUS

Seam defined (`AuthTokenStore`); interceptor with single-flight refresh ready.
No token handling, no secure storage yet — Task 3.

## AI FEATURES IMPLEMENTED

Component layer with trust rules enforced. No AI backend calls. SSE streaming
transport not built (arrives with Task 9).

## TESTING STATUS

8 suites, ~1,840 lines, **none executed** (R7).
Not covered: `AppShell` tab behaviour, `DriftCacheStore` against a real
database (needs codegen), the interceptor chain end-to-end against a mock
adapter, goldens, any integration test.

## KNOWN BUGS

None known. Task 2 self-review found and fixed:

| ID | Defect | Fix |
| --- | --- | --- |
| F4 | `AnalyticsEvent` declared a field named `name`, shadowing the `EnumName` extension getter every Dart enum already has | Renamed to `wireName`, consistent with `UserRole.wireValue` |
| F5 | A comment on `validateStatus` claimed the client never throws on status — the opposite of what it does, and of what the mapper needs | Comment corrected |
| F6 | `api_headers.dart` held a placeholder constant that existed only to carry a doc comment | Removed; the comment stands alone |
| F7 | `PlatformConnectivityService.initialise()` could run twice (provider body and `main()`), creating a duplicate subscription that would double-emit every change | Made idempotent with a guard |
| F8 | Two overlapping CI workflows existed after a duplicate `build-apk.yml` was authored alongside the pre-existing `build.yml`; both would run on every push and produce competing artifacts | Duplicate removed; `build.yml` kept as the single workflow |
| F9 | `.gitignore` assumed `android/` was committed (ignoring `android/.gradle/`) while `build.yml` deliberately does not commit it | `.gitignore` aligned with AD-28, with the trade-off and revisit condition documented |
| F10 | `configure_android.py` referenced `docs/FIRST_BUILD.md`, which does not exist | Repointed to `BUILD.md` |
| F11 | `PermissionSet` was an extension type with a **private** representation field (`_values`) but was constructed from another library by `SessionController`. Whether that implicit constructor is reachable across libraries is a language edge not worth depending on in authorisation-adjacent code | Rewritten as a plain immutable class with `==`, `hashCode` and an unmodifiable `values` view |
| F12 | `EmployeeHomeScreen` placed a `ListView` inside `SliverFillRemaining`, nesting two independent scrollables so the header would never scroll away, and leaving the centred message states unbounded | Header moved outside the scroll area; state view in an `Expanded` wrapped by `RefreshIndicator` |
| F13 | `TodayAttendanceCard._statusFor` took an untyped `palette` parameter — implicitly `dynamic`, which `strict-raw-types` rejects — and never used it | Parameter removed |
| F14 | `PendingItemsList` separated rows using `item != items.last`; `PendingItem` has no value equality, so this compared identity and would misbehave if two items ever compared equal | Rewritten to index-based iteration |

Task 1 fixes F1–F3 are recorded in the Session 1 handoff (super-parameter
misuse, duplicate route names, Flutter version constraint).

---

## KNOWN RISKS

| ID | Risk | Impact | Mitigation |
| --- | --- | --- | --- |
| R1 | Backend API availability unconfirmed; Odoo CE v18 exposes no mobile-shaped aggregates natively | Blocks Phase 2+ | Mock repositories behind API-compatible interfaces; contract shape now documented for the API team |
| R2 | Continuity depends on committing code and re-uploading this file | Lost work | Handoff every session |
| R3 | Release 1 spans four roles | Schedule | Strict phase delivery |
| R4 | Attrition/performance AI carries employment-decision consequences | Legal, ethical | Trust rules enforced in shared components with tests |
| R5 | Device variability in the Bangladesh SME market | Performance | Performance budget; mid-range Android in test matrix |
| R6 | Localisation not specified | Rework | Strings externalised from the start |
| **R7** | **Task 1 and Task 2 code has never been compiled or tested** — no toolchain in the authoring environment | **Compile errors may remain despite manual review** | **First action next session: platform folders, pub get, build_runner, analyze, test. Fix before new feature work.** |
| R8 | Dependency versions are caret ranges resolved for the first time | Version conflicts on first `pub get` | Commit `pubspec.lock` |
| **R9** | Cache database is unencrypted. Correct today only because policy excludes sensitive data — a future feature that caches sensitive records without changing storage would create exposure at rest | Data at rest on a lost device | Documented in-file; Q8 raises SQLCipher. **Review whenever a new `CachePolicy` is chosen.** |
| **R10** | If the backend places internal detail in `user_message`, the client discards it and shows generic copy — correct, but users may see unhelpful messages until the contract is agreed | Support load | API contract item 1 |

---

## ARCHITECTURAL DECISIONS

AD-01…AD-10 as originally recorded: Flutter/Dart; Riverpod; Clean Architecture
with feature-first modularisation; GoRouter/Dio/Freezed; Drift + SQLite with
platform secure storage; Keycloak OIDC + PKCE with server-side authorisation;
mobile as API consumer; REST + SSE; single role-aware app; route names are
screen IDs.

| ID | Decision | Rationale |
| --- | --- | --- |
| AD-11 | Design tokens as `ThemeExtension`s | One substitution for light/dark and future tenant theming |
| AD-12 | Router built per role, keyed on navigation signature | Single source of truth for navigation; no conditional branch logic in the router |
| AD-13 | Failure type determines UX state | Makes all six states the default for every screen |
| AD-14 | AI trust rules enforced by constructor contract | Review-based enforcement would drift as screens multiply |
| AD-15 | Provisional Super Admin screen IDs (`SA-00`…`SA-02`) | Blueprint assigns none |
| AD-16 | Text scale clamped 0.9–1.6× | Honours preference without breaking dense KPI layouts |
| **AD-17** | **`ApiClient` is the only HTTP-aware type**; everything above receives `AppFailure` | Makes Instructions §24 structural rather than a review item |
| **AD-18** | **Server error text is distrusted; only `user_message` renders, after shape checks** | Backend bodies can carry tracebacks, SQL and Odoo model names; the client is the last line of defence |
| **AD-19** | **Mutations are never retried without an idempotency key** | A retried check-in, leave submission or approval corrupts attendance, balances and the audit trail — and only on a flaky network, which manual testing does not reproduce |
| **AD-20** | **Refresh is single-flight** | Concurrent 401s would otherwise trigger parallel refreshes, and refresh-token rotation would invalidate the set |
| **AD-21** | **No tenant header is sent** | A client-supplied tenant value is attacker-controlled input on the tenant-isolation path; the gateway resolves tenant from verified token claims |
| **AD-22** | **Cacheability is a policy, and `CachePolicy.never` is refused at the repository** | Turns "don't cache payroll" from a rule each feature must remember into something the code cannot do |
| **AD-23** | **Authoritative failures (403/422) never fall back to cache** | Access may have been revoked since the write; contradicting the server would show data the user has lost rights to |
| **AD-24** | **Cache scoped by tenant + user, purged on sign-out and principal change** | Shared devices and multi-tenancy make an unscoped cache a cross-account read |
| **AD-25** | **Generic key/JSON cache table now; typed tables per feature later** | The mobile API contracts do not exist yet; designing ten schemas against unknown endpoints would be inventing requirements |
| **AD-26** | **Telemetry filtered at the sink, dropping rather than throwing** | Analytics calls are added quickly and reviewed lightly, and a leak here is silent |
| **AD-27** | **Reads return `DataSnapshot<T>` (data + origin + syncedAt), not bare `T`** | The Live vs Last-synchronized distinction in UI-UX §48 is impossible to honour if provenance is discarded at the repository boundary |
| **AD-28** | **`android/` and `ios/` are generated, not committed**; required customisation is applied by the idempotent `scripts/configure_android.py` | Platform folders are `flutter create` output that differs per SDK version and conflicts on every bump. **Revisit when branding or signing lands** — icons are binary assets a script cannot generate (see `.gitignore`) |
| **AD-29** | **`INTERNET` permission is written into the main manifest, not only debug** | Flutter's default puts it in debug/profile only, so release builds have no network and every request times out silently on a device that is plainly online |
| **AD-30** | **CI analyze/test are non-blocking until the first green run**, then flipped | Tasks 1–2 were authored without a toolchain; an installable APK is more useful now than a red run. A real compile error still fails the build, since the APK step cannot succeed without compiling |

---

## ASSUMPTIONS

A1–A9 as previously recorded: Attendance as employee nav tab 2; E-03
policy-driven; Request Center three tabs; payroll masked with biometric reveal;
strings externalised; BDT and date formats; brand palette and typeface
provisional; system theme mode.

| ID | Assumption | Basis | Needs confirmation |
| --- | --- | --- | --- |
| **A10** | The API returns errors as `{user_message, errors}` | No error contract documented; this shape is conventional and the client degrades safely without it | **Yes — API team** |
| **A11** | The backend will support `Idempotency-Key` on submissions | Required for safe retry of mutations | **Yes — API team** |
| **A12** | Timeouts of 12s connect / 30s receive / 20s send suit the target market and AI endpoints | Judgement: AI endpoints do real work, and target-market networks are slow rather than absent | Revisit with real latency data |
| **A13** | Cache TTLs: dashboard 2 min, lists 5 min, profile 12 h, reference 1 day | Judgement balancing freshness against spinners | Revisit after usage data |
| **A14** | Caching only non-sensitive data makes an unencrypted database acceptable | Tech-Stack §11 | **Yes — Q8** |

---

## OPEN QUESTIONS

**Q1 — Release 1 role scope. [MATERIAL]** All four roles in Release 1,
delivered in phases (Employee → Manager → HR → Executive), each shippable?
Functional Blueprint §34 and Blueprint §70 disagree.

**Q2 — Performance screens in Release 1. [MATERIAL]** Read-only score and trend
embedded in E-01/M-03 for Release 1, full E-12/M-07 in Release 2?

**Q3 — AI explainability in Release 1. [MATERIAL]** Built and enforced in
Task 1, because M-05 ships in Release 1 showing an AI recommendation.
Confirmation of the scope addition still wanted.

**Q4 — Backend readiness.** Which mobile endpoints exist behind APISIX/FastAPI?
Is there an OpenAPI spec or Postman collection? Also: can the API team confirm
the four contract items under API PROPOSED?

**Q5 — Environment access. [BLOCKS TASK 3]** Keycloak base URL, realm, mobile
client ID, redirect URI scheme, and a dev tenant with test users per role.
`app_config.dart` holds placeholder hosts.

**Q6 — Brand identity.** Existing palette, logo and font licence to inherit? If
not, please review the proposed palette in `core/theme/app_colors.dart`.

**Q7 — Attendance policy modes. [BLOCKS TASK 5]** Which of Office
(GPS + geofence) / Remote / Field (GPS + photo) / Factory (QR + location) are
in Release 1?

**Q8 — Cache encryption at rest. [NEW]** The cache database is unencrypted,
safe only while policy keeps sensitive data out. Adopt SQLCipher
(`sqlcipher_flutter_libs`, key in Keystore/Keychain) now as defence in depth,
or accept the current position and enforce it by review? Likely to come up in
enterprise security questionnaires.

**Q9 — Firebase project. [NEW]** `google-services.json` and
`GoogleService-Info.plist` are needed for FCM and Crashlytics. Which Firebase
project, and who owns it? Until then telemetry logs locally in dev and
discards elsewhere.

**Q10 — Minimum app version enforcement. [NEW]** The client sends
`X-Client-Version`. Should the gateway be able to reject outdated clients, and
if so what should the app show? Relevant once payroll or policy logic changes
shape.

---

## TECHNICAL DEBT

| ID | Item | Priority |
| --- | --- | --- |
| TD-1 | `flutter analyze` / `flutter test` never run. Mitigated but not resolved by `scripts/static_checks.py` | **High — clear first** |
| TD-2 | `AppShell` has no widget test for tab switching and stack preservation | Medium |
| TD-3 | No golden tests | Low |
| TD-4 | `pubspec.lock` not generated or committed | Medium |
| TD-5 | Android/iOS platform folders not generated | **High — blocks first run** |
| TD-6 | CI added: `.github/workflows/build.yml` produces a debug APK artifact. **analyze and test are non-blocking** until the first green run — flip them once clean. Release signing unconfigured | Medium |
| **TD-7** | No end-to-end interceptor test against a Dio mock adapter — chain order and replay behaviour unverified | Medium |
| **TD-8** | `DriftCacheStore` untested (needs codegen); only `InMemoryCacheStore` is covered | Medium |
| **TD-9** | No production telemetry sink | Medium |
| **TD-10** | Certificate pinning not implemented; OWASP MASVS network requirements not yet reviewed against the client | Medium — before UAT |

---

## NEXT EXACT TASK

**Before anything else — get the toolchain green (R7, TD-1, TD-4, TD-5):**

```bash
cd perfect_hr_mobile
flutter create --platforms=android,ios \
  --project-name perfect_hr_mobile --org com.perfecthr .
python3 scripts/configure_android.py
flutter pub get
dart run build_runner build --delete-conflicting-outputs
flutter analyze
flutter test
```

Or push to GitHub and let `.github/workflows/build.yml` do it and hand back an
APK. `python3 scripts/static_checks.py` is clean, but it only covers delimiter
balance, named arguments, interface completeness and imports — it cannot see
type errors, exhaustiveness or null safety, so expect analyze findings.

**Then Task 5 — E-02/E-03 Attendance.** Needs Q7 answered: which of Office
(GPS + geofence) / Remote / Field (GPS + photo) / Factory (QR + location) are in
Release 1. The screen can be built for the Office mode alone and extended, but
the permission flow and the check-in payload differ per mode, so building all
four speculatively would be inventing requirements.

Scope once Q7 is answered:

1. `features/attendance/domain/` — attendance record, month summary, correction
   request. Reuse `AttendanceState` from the dashboard domain rather than
   redeclaring it; consider promoting it to `shared/models/`.
2. **PROPOSED APIs**: `GET /me/attendance/today`,
   `GET /me/attendance/month/{yyyy-mm}`, `POST /me/attendance/check-in`,
   `POST /me/attendance/check-out`, `POST /me/attendance/corrections`.
   Check-in and check-out **must** carry an `Idempotency-Key` — `RetryPolicy`
   will not replay them otherwise, and duplicating an attendance record is
   exactly the harm AD-19 exists to prevent.
3. Wrap check-in in `requireLiveConnection()`: it cannot be satisfied from
   cache and must not appear to succeed offline (Instructions §17).
4. E-02 Attendance Home, E-03 Check-In Confirmation (policy-driven per A2 —
   inline confirmation by default), E-04 Calendar, E-05 Correction.
5. Location permission requested at point of use, never at launch
   (Instructions §18). Handle permanent denial with a route to system settings.
6. Invalidate the E-01 cache after a successful check-in via
   `EmployeeHomeNotifier.invalidateAndReload()`, so home does not show a stale
   "not checked in" card immediately after the user checked in.
7. Tests: state transitions, idempotency key present on both mutations,
   offline check-in blocked before any request is attempted, correction
   validation, calendar rendering of the four-state legend.

---

## DO NOT REDO

- Design tokens, theme, typography, spacing, motion.
- Role-aware navigation profiles, shell, route table, screen-ID naming.
- The six UX state components and the `AppFailure` hierarchy.
- The AI component set and its trust enforcement.
- Session and permission scaffolding structure.
- **Networking layer:** Dio assembly, failure mapper, retry policy, auth
  interceptor seam, logging redaction, connectivity service.
- **Data layer:** cache policy, store, resource, scoping, purge lifecycle.
- **Drift schema v1** — extend with typed tables and a migration; do not
  restructure `CacheEntries`.
- **Telemetry guard.**

Extend rather than rebuild. If a change to navigation, AI trust behaviour,
retry safety or cache policy seems necessary, a test will fail — that is
deliberate. Raise it as a specification question rather than editing the test.

---

## SESSION HANDOFF

```text
PERFECT HR MOBILE — SESSION HANDOFF

Date: 2026-09-07
Project Phase: Phase 1 — Mobile Foundation

Completed:
- Task 1: design system, shell, routing, session scaffolding, UX states,
  AI component set (33 files)
- Task 2: networking, failure mapping, retry policy, connectivity, cache
  policy/store/resource, Drift schema v1, telemetry guard (17 files added)
- Cumulative: 50 Dart files, ~6,370 lib lines, ~1,840 test lines, 8 suites

Current Work:
- None in flight

Files Changed (Task 2):
- lib/core/networking/{api_client,api_headers,auth_interceptor,
  dio_failure_mapper,retry_interceptor,logging_interceptor,
  connectivity_service}.dart
- lib/core/data/{cache_policy,cache_store,cached_resource,data_providers}.dart
- lib/core/storage/app_database.dart
- lib/core/analytics/telemetry.dart
- lib/{app,main}.dart rewritten (cache lifecycle holder, connectivity warm-up)
- pubspec.yaml (added drift_flutter), README.md
- test/core/networking/{dio_failure_mapper,retry_policy}_test.dart
- test/core/data/cached_resource_test.dart
- test/core/analytics/telemetry_guard_test.dart

Screens Completed:
- None. Placeholder routes only.

APIs Added/Changed:
- None called. Four contract items documented for the API team under
  API PROPOSED: error envelope, status semantics, idempotency, correlation.

Tests Added:
- 4 suites, ~1,080 lines. NOT EXECUTED — no toolchain available.

Known Issues:
- R7/TD-1: code never compiled. R9: cache DB unencrypted (safe by policy only).
- TD-5: platform folders missing. Drift codegen is now a build prerequisite.

Architecture Decisions:
- AD-17 ApiClient is the only HTTP-aware type
- AD-18 server error text distrusted; only user_message renders
- AD-19 mutations never retried without an idempotency key
- AD-20 single-flight refresh
- AD-21 no tenant header sent
- AD-22 CachePolicy.never refused at the repository
- AD-23 authoritative failures never fall back to cache
- AD-24 cache scoped per tenant+user, purged on sign-out and principal change
- AD-25 generic cache table now, typed tables per feature later
- AD-26 telemetry filtered at the sink, dropping not throwing
- AD-27 reads return DataSnapshot (data + origin + syncedAt)

Pending:
- Task 3 authentication (blocked on Q5), then Phase 2 Employee screens

Next Exact Task:
- flutter create . -> pub get -> build_runner build -> analyze -> test -> fix
  -> commit pubspec.lock. Then Task 3 step 1 onward.

Important Context:
- New questions this session: Q8 cache encryption, Q9 Firebase project,
  Q10 minimum version enforcement.
- Q5 blocks Task 3. Q7 blocks Task 5. Q1-Q3 scope decisions still open.
- Drift codegen is now a hard build prerequisite.

Do Not Redo:
- See DO NOT REDO above. Networking and data layers are complete.
```
