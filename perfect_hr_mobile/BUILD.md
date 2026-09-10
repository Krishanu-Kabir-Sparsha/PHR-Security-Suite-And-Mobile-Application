# Building the Perfect HR Mobile APK

Two routes. Use CI if you don't want to install anything.

---

## What this build currently shows

Read this first, so the APK isn't a surprise.

Tasks 1 and 2 built the **foundation**, not the screens. Installing today's APK
gives you:

- **AUTH-01 Welcome** — logo, product statement, Get Started and Sign In.
  Both buttons are inert: real authentication is Task 3 and needs the Keycloak
  configuration (Q5).
- **A dev role switcher** on that screen (dev and qa builds only) with buttons
  for Employee, Manager, HR, CHRO, CEO and Super Admin. Tapping one enters the
  app as that role.
- **The role-aware shell** — the bottom navigation changes correctly per role:
  Employee gets Home / Attendance / Requests / AI / More, Manager gets Home /
  Team / Approvals / AI / More, and so on. Tabs keep their own navigation
  stacks. This is the part genuinely worth trying.
- **Placeholder screens** behind every destination. Each names its Blueprint
  screen ID (E-01, M-04, X-01…), what the screen is for, and which task will
  build it. They are deliberately obvious placeholders so nothing looks
  finished that isn't.

So the APK demonstrates navigation, theming and role behaviour. It does not
yet show attendance, leave, payroll, approvals or AI, because those screens
have not been written. Task 4 onward builds them.

---

## Route 1 — GitHub Actions (no local toolchain)

1. Push this repository to GitHub.
2. Open the **Actions** tab → **Build** → **Run workflow**, or just push a
   commit; it runs automatically.
3. When the run finishes, download the **`perfect-hr-mobile-debug-apk`**
   artifact from the run summary.
4. Unzip and install on an Android device (enable "install from unknown
   sources" for your file manager or browser).

`flutter analyze` and `flutter test` both run, but are **deliberately
non-blocking for now**, so you get an installable APK on the first run even
though this code has never been compiled (Project State R7). Findings appear in
the run log with exact file and line numbers.

**Flip both to blocking once they are green.** Until then the workflow reports
on the codebase rather than protecting it. The `continue-on-error: true` lines
in `.github/workflows/build.yml` are marked with that instruction.

A genuine compile error still fails the build — the APK step cannot succeed
without compiling — so a green run means the code builds.

---

## Route 2 — Local build

**Prerequisites**

- Flutter **3.27 or newer** (the design system uses `Color.withValues` and the
  `*ThemeData` component theme classes, which do not exist in 3.24)
- Android Studio or the Android command-line SDK, with a platform and
  build-tools installed
- JDK 17
- `flutter doctor` showing no Android toolchain errors

**Build**

```bash
./scripts/build_apk.sh
```

That script handles first-run setup and is safe to re-run. Or step through it
manually:

```bash
flutter create --platforms=android,ios \
  --project-name perfect_hr_mobile --org com.perfecthr .
python3 scripts/configure_android.py
flutter pub get
dart run build_runner build --delete-conflicting-outputs
flutter analyze                                   # findings expected
flutter test                                      # findings expected
flutter build apk --debug --dart-define=FLAVOR=dev
```

**Install**

```bash
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```

Or run directly on a connected device with hot reload:

```bash
flutter run --dart-define=FLAVOR=dev
```

---

## Things that will trip you up

**`android/` and `ios/` are deliberately not committed.** They are
`flutter create` output, they differ between Flutter versions, and committing
them causes a merge conflict on every SDK bump. Both CI and
`scripts/build_apk.sh` generate them, then apply Perfect HR's required
configuration with `scripts/configure_android.py`. See `.gitignore` for the
trade-off and when to revisit it.

**`configure_android.py` is not optional.** A default `flutter create` project
will not run this app correctly. It fixes four things, the first of which is
the one that costs people a day:

- **`INTERNET` permission.** Flutter adds it to the debug and profile manifests
  only. A release build has no network access at all, and the failure is
  silent — every request times out on a device that is plainly online.
- **`minSdk 23`**, required by `local_auth` for the biometric prompt.
- **`appAuthRedirectScheme`**, without which `flutter_appauth` fails the Gradle
  build outright.
- Location, camera and `POST_NOTIFICATIONS` permissions that attendance,
  document capture and FCM will need — declared now, requested at point of use,
  never at launch (Instructions §18).

The script is idempotent: run it after every `flutter create` and after any SDK
upgrade that regenerates the folder.

**Code generation is mandatory.** `core/storage/app_database.dart` declares
`part 'app_database.g.dart'`. Without `build_runner` the project does not
compile, and the error message points at the missing part file rather than the
real cause. Re-run it after changing any Drift table.

**`--dart-define=FLAVOR` is required.** Endpoints are never hard-coded
(Tech-Stack §25). Omitting it defaults to `dev`, which points at placeholder
hosts that do not exist — fine for reviewing the UI, since no screen calls an
API yet.

**Redirect scheme must match Keycloak.** `configure_android.py` sets
`appAuthRedirectScheme` to `com.perfecthr.mobile`. That is the value the app
will claim; it has to match the redirect URI registered for the mobile client
in the realm. Confirm it before Task 3 integration testing (Project State Q5).

---

## Release builds and signing

`flutter build apk --release` needs the Perfect HR upload keystore. It is
**not** in this repository and must never be committed — `.gitignore` already
excludes `*.jks`, `*.keystore` and `key.properties`.

When you're ready to distribute:

1. Generate an upload key and store it outside the repository.
2. Create `android/key.properties` locally (gitignored) with the store path,
   passwords and alias.
3. Reference it from `android/app/build.gradle.kts` signing config.
4. For CI, put the keystore in GitHub Secrets as base64 and decode it in a
   build step. Since `android/` is generated rather than committed, the signing
   config also has to be applied by `configure_android.py` — extend it rather
   than hand-editing a folder that gets regenerated.

Debug APKs are the right choice for internal review. They are self-signed,
install without configuration, and cannot be mistaken for a production build.
