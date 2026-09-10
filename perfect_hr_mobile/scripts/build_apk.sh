#!/usr/bin/env bash
#
# Perfect HR Mobile — local APK build.
#
#   ./scripts/build_apk.sh            debug APK, dev flavour
#   ./scripts/build_apk.sh qa         debug APK, qa flavour
#
# Mirrors .github/workflows/build.yml, so a local build and a CI build produce
# the same thing. Handles first-run setup and is safe to re-run.
#
# analyze and test run but DO NOT block the build, matching the CI decision:
# Tasks 1-2 were authored without a toolchain, so findings are expected and an
# installable APK is more useful right now than a hard stop. Flip both to
# blocking here and in CI once they are green.

set -uo pipefail

FLAVOR="${1:-dev}"
cd "$(dirname "$0")/.."

step() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33mWARNING:\033[0m %s\n' "$1"; }
fail() { printf '\n\033[1;31mERROR:\033[0m %s\n' "$1" >&2; exit 1; }

command -v flutter >/dev/null 2>&1 || fail \
  "Flutter not found. Install 3.27 or newer: https://docs.flutter.dev/get-started/install"

step "Toolchain"
flutter --version

# The design system uses Color.withValues and the *ThemeData component theme
# classes, both 3.27+. An older SDK fails with misleading errors.
version_line="$(flutter --version | head -1)"
major="$(echo "$version_line" | sed -E 's/.*Flutter ([0-9]+)\.([0-9]+).*/\1/')"
minor="$(echo "$version_line" | sed -E 's/.*Flutter ([0-9]+)\.([0-9]+).*/\2/')"
if [ "${major:-0}" -lt 3 ] || { [ "${major:-0}" -eq 3 ] && [ "${minor:-0}" -lt 27 ]; }; then
  fail "Flutter 3.27 or newer required (found ${major}.${minor}). See pubspec.yaml."
fi

# Platform folders are generated, not committed. See .gitignore.
if [ ! -d android ]; then
  step "Generating platform folders"
  flutter create --platforms=android,ios \
    --project-name perfect_hr_mobile \
    --org com.perfecthr . || fail "flutter create failed"
fi

step "Applying Perfect HR Android configuration"
python3 scripts/configure_android.py || fail "configure_android.py failed"

step "Resolving dependencies"
flutter pub get || fail "pub get failed"

# Not optional: core/storage/app_database.dart declares
# part 'app_database.g.dart', so the project will not compile without this.
step "Running code generation (Drift)"
dart run build_runner build --delete-conflicting-outputs \
  || fail "code generation failed — the project cannot compile without it"

step "Analyzing (non-blocking)"
flutter analyze || warn "analyze reported findings — see above"

step "Testing (non-blocking)"
flutter test || warn "tests reported failures — see above"

step "Building debug APK (flavour: ${FLAVOR})"
flutter build apk --debug --dart-define=FLAVOR="$FLAVOR" \
  || fail "APK build failed — fix the errors above, they are real compile errors"

step "Done"
ls -lh build/app/outputs/flutter-apk/*.apk
cat <<NOTE

Install on a connected device:
  adb install -r build/app/outputs/flutter-apk/app-debug.apk

Or run with hot reload:
  flutter run --dart-define=FLAVOR=${FLAVOR}
NOTE
