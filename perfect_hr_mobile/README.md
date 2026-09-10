# Perfect HR Mobile

Flutter client for the Perfect HR AI-powered workforce platform.

**This app is an API consumer, not an independent business application.** No
business logic, authorisation decision or payroll calculation belongs here. All
of it lives behind APISIX → FastAPI → Odoo CE v18 / AI Services (Instructions
§7). The mobile app renders authorised outcomes and captures user intent.

```
Flutter → APISIX → Keycloak (OIDC) / FastAPI → Odoo · AI · Analytics → PostgreSQL
```

## Status

Tasks 1–2 of Release 1 complete: design system, application shell, routing,
session scaffolding, global UX states, AI component set, networking layer,
failure mapping, and the cache/offline layer. Screens are placeholders that
name their Blueprint ID and the task that will build them.

Authoritative status lives in `PERFECT_HR_MOBILE_PROJECT_STATE.md` at the
repository root. Read it before starting any work.

## Running

```bash
flutter create .                    # first run only: generates android/ and ios/
flutter pub get
dart run build_runner build         # required: Drift generates app_database.g.dart
flutter run --dart-define=FLAVOR=dev
```

`build_runner` is not optional. `core/storage/app_database.dart` declares
`part 'app_database.g.dart'`, so the project does not compile until code
generation has run. Re-run it after changing any Drift table.

Flavours are `dev`, `qa`, `uat`, `prod` (Tech-Stack §25). Endpoints are never
hard-coded; they resolve from the flavour in `core/config/app_config.dart`.

In `dev` and `qa` builds the welcome screen shows a **role switcher** that
enters the shell as Employee, Manager, HR, CHRO, CEO or Super Admin without
authenticating. This exists so the role-aware experience can be reviewed before
Keycloak integration lands, and it is inert in `uat` and `prod`.

```bash
flutter analyze
flutter test
```

## Structure

```
lib/
├── core/          Cross-cutting infrastructure
│   ├── config/    Build flavours and environment resolution
│   ├── constants/ Blueprint screen IDs
│   ├── errors/    AppFailure — user-safe messages, never raw errors
│   ├── routing/   GoRouter config and role-aware navigation profiles
│   ├── session/   Role, permissions, session state
│   └── theme/     Design tokens (colour, type, spacing, radius, motion)
├── features/      Feature-first modules, each split presentation /
│                  application / domain / data
└── shared/        Reusable widgets, AI components, UX states, extensions
```

Each feature owns its four layers and does not reach into another feature's
internals. Anything genuinely shared moves to `shared/`, not to a catch-all
service (Instructions §9).

## Conventions

**Design tokens only.** No hard-coded colour, font size, spacing or radius at a
call site. Read tokens through `context.palette`, `context.styles`,
`AppSpacing`, `AppRadius`, `AppSizes`, `AppMotion` (Instructions §12). Adding a
token is correct; inlining a value is not.

**Screen IDs are contracts.** Every route is named for its Blueprint screen ID
(`E-01`, `M-04`, `X-01`…), so navigation logs, analytics and tests all read
against the specification (Instructions §20). Keep the ID in the screen's
doc comment and its test name.

**Six states, always.** Every screen handles loading, loaded, empty, error,
offline and permission-denied (Blueprint §52). `AsyncStateView` derives five of
them from the failure type, so a screen supplies only its loaded content. A
feature is not complete when the UI renders — see Instructions §45.

**Errors are user-safe by construction.** `AppFailure` carries a `userMessage`
for display and `technical` for logs. Never render an exception. Never show an
HTTP status code.

**AI must declare itself.** Use `AiInsightCard` for descriptive output and
`AiRecommendationCard` where a human decision follows. The recommendation card
requires both `reasons` and `decisionAuthority`, so an unexplained or
unaccountable AI recommendation cannot be built (Instructions §14). Predicted
risk requires a confidence value.

**Authorisation is server-side.** `PermissionSet` decides what to *render*.
It grants nothing. Hiding a widget is not access control (Instructions §15).

**Tenant context is received, never asserted.** The client never sets, infers
or alters the tenant, and deliberately sends no tenant header — see
`core/networking/api_headers.dart` (Instructions §16).

**No layer above `ApiClient` sees a status code.** `ApiClient` converts every
transport error into an `AppFailure` via `DioFailureMapper`. Repositories and
screens never handle a `DioException`. Server-supplied error text is distrusted
by default; only the `user_message` field is rendered, and only after
length/shape checks.

**Mutations are not retried without an idempotency key.** Pass
`idempotencyKey:` to `ApiClient.post/put/patch` for any submission that would
be harmful to duplicate. See `RetryPolicy` for why.

**Cache policy decides what may be stored.** Use a `CachePolicy` constant
(`dashboard`, `activityList`, `profile`, `reference`, `sensitive`). Payroll and
similar data use `CachePolicy.sensitive`, which is never written to disk and
fails cleanly offline instead of serving a stale amount. Reads return a
`DataSnapshot<T>` carrying origin and sync time, so the UI can honour the
Live vs Last-synchronized distinction.

**Analytics parameters are filtered at the sink.** `TelemetryGuard` drops keys
and values that could carry personal or compensation data. Do not work around
it; add a categorical dimension instead (Instructions §27).

## Testing

```
test/core/routing/nav_profile_test.dart        Bottom navigation per role
test/core/routing/app_router_test.dart         Router builds; unique route names
test/core/networking/dio_failure_mapper_test.dart  Status mapping; no leakage
test/core/networking/retry_policy_test.dart    Mutations are never replayed
test/core/data/cached_resource_test.dart       Cache strategy; scope isolation
test/core/analytics/telemetry_guard_test.dart  Sensitive fields are dropped
test/shared/components/ux_states_test.dart     Six UX states; safe error mapping
test/shared/ai/ai_trust_rules_test.dart        AI trust rules cannot be bypassed
```

The navigation and AI trust tests are deliberately literal. Both encode
approved product decisions, so changing the behaviour should break a test and
prompt a specification conversation rather than passing quietly.

The mapper, retry and cache tests target failure paths that manual testing does
not reproduce: a leaked stack trace appears only in the error condition nobody
exercises by hand, and a duplicate check-in happens only on a flaky network.

## Specifications

Four documents are authoritative, in this precedence order when they conflict:
Functional Blueprint → Screen & Wireframe Blueprint → UI/UX Specification →
Tech-Stack. A conflict that materially affects architecture, security or UX is
raised rather than silently resolved (Instructions §3).
