#!/usr/bin/env python3
"""Applies Perfect HR's Android configuration to a generated android/ folder.

`flutter create` produces a default Android project that will NOT run this app:

  * INTERNET permission is added only to the debug and profile manifests by
    Flutter. A release build has no network access at all — and the failure is
    silent, appearing as every request timing out on a device that is plainly
    online. This is the single most common cause of "works in debug, broken in
    release" in Flutter projects.
  * minSdk defaults below what local_auth (biometrics) requires.
  * flutter_appauth needs an `appAuthRedirectScheme` manifest placeholder or
    the Gradle build fails outright.
  * The permissions attendance and document capture will need (location,
    camera, notifications) are absent.

Run after `flutter create`, and again after any Flutter SDK upgrade that
regenerates the folder. Safe to run repeatedly: every edit checks first.

Usage:  python3 scripts/configure_android.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANDROID = ROOT / "android"
MANIFEST = ANDROID / "app" / "src" / "main" / "AndroidManifest.xml"

# Minimum for local_auth biometric prompt. flutter_secure_storage is happy at
# 18, but there is no reason to support below 23 for a 2026 enterprise app.
MIN_SDK = 23

# Must match the redirect URI registered for the mobile client in Keycloak.
# Pending Q5 — this is the value the app will claim; confirm it against the
# realm configuration before Task 3 integration testing.
REDIRECT_SCHEME = "com.perfecthr.mobile"

PERMISSIONS = [
    # Required in the main manifest, not just debug. See module docstring.
    ("android.permission.INTERNET", None),
    ("android.permission.ACCESS_NETWORK_STATE", "connectivity_plus"),
    # Task 3 — biometric re-authentication.
    ("android.permission.USE_BIOMETRIC", "local_auth"),
    # Task 5 — attendance location verification. Requested at point of use,
    # never at launch (Instructions §18).
    ("android.permission.ACCESS_FINE_LOCATION", "attendance geofencing"),
    ("android.permission.ACCESS_COARSE_LOCATION", "attendance geofencing"),
    # Task 8 — push notifications on Android 13+.
    ("android.permission.POST_NOTIFICATIONS", "FCM on Android 13+"),
]

# Declared rather than required: the app must install on devices without them.
FEATURES = [
    ("android.hardware.camera", "document and attendance capture"),
    ("android.hardware.location.gps", "attendance geofencing"),
]

changes: list[str] = []
warnings: list[str] = []


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def patch_manifest() -> None:
    if not MANIFEST.exists():
        fail(f"{MANIFEST.relative_to(ROOT)} not found. Run `flutter create .` first.")

    text = MANIFEST.read_text()
    original = text

    lines: list[str] = []
    for permission, reason in PERMISSIONS:
        if permission in text:
            continue
        comment = f"    <!-- {reason} -->\n" if reason else ""
        lines.append(f'{comment}    <uses-permission android:name="{permission}" />')

    for feature, reason in FEATURES:
        if feature in text:
            continue
        lines.append(
            f"    <!-- {reason}; not required so the app still installs "
            f"without it -->\n"
            f'    <uses-feature android:name="{feature}" '
            f'android:required="false" />'
        )

    if lines:
        block = "\n".join(lines)
        text = text.replace("<manifest", f"<manifest", 1)
        # Insert immediately after the opening <manifest ...> tag.
        match = re.search(r"<manifest[^>]*>", text)
        if not match:
            fail("could not locate the <manifest> opening tag")
        insert_at = match.end()
        text = text[:insert_at] + "\n" + block + "\n" + text[insert_at:]
        changes.append(f"AndroidManifest.xml: added {len(lines)} declaration(s)")

    if text != original:
        MANIFEST.write_text(text)


def patch_gradle() -> None:
    kts = ANDROID / "app" / "build.gradle.kts"
    groovy = ANDROID / "app" / "build.gradle"

    if kts.exists():
        patch_gradle_kts(kts)
    elif groovy.exists():
        patch_gradle_groovy(groovy)
    else:
        fail("neither android/app/build.gradle.kts nor build.gradle found")


def patch_gradle_kts(path: Path) -> None:
    text = path.read_text()
    original = text

    if "minSdk = " in text and f"minSdk = {MIN_SDK}" not in text:
        text = re.sub(
            r"minSdk = [^\n]+",
            f"minSdk = {MIN_SDK} // local_auth biometric prompt requires 23",
            text,
            count=1,
        )
        changes.append(f"build.gradle.kts: minSdk -> {MIN_SDK}")

    if "appAuthRedirectScheme" not in text:
        # Insert into the existing defaultConfig block.
        marker = "defaultConfig {"
        index = text.find(marker)
        if index == -1:
            warnings.append(
                "build.gradle.kts: no defaultConfig block found; add "
                "manifestPlaceholders manually (see BUILD.md)"
            )
        else:
            insert_at = index + len(marker)
            placeholder = (
                "\n        // Required by flutter_appauth; must match the "
                "redirect URI\n        // registered for the mobile client in "
                "Keycloak (Project State Q5).\n"
                f'        manifestPlaceholders["appAuthRedirectScheme"] = '
                f'"{REDIRECT_SCHEME}"\n'
            )
            text = text[:insert_at] + placeholder + text[insert_at:]
            changes.append("build.gradle.kts: added appAuthRedirectScheme")

    if text != original:
        path.write_text(text)


def patch_gradle_groovy(path: Path) -> None:
    text = path.read_text()
    original = text

    if "minSdkVersion" in text and f"minSdkVersion {MIN_SDK}" not in text:
        text = re.sub(
            r"minSdkVersion [^\n]+",
            f"minSdkVersion {MIN_SDK} // local_auth biometric prompt requires 23",
            text,
            count=1,
        )
        changes.append(f"build.gradle: minSdkVersion -> {MIN_SDK}")

    if "appAuthRedirectScheme" not in text:
        marker = "defaultConfig {"
        index = text.find(marker)
        if index == -1:
            warnings.append(
                "build.gradle: no defaultConfig block found; add "
                "manifestPlaceholders manually (see BUILD.md)"
            )
        else:
            insert_at = index + len(marker)
            placeholder = (
                "\n        // Required by flutter_appauth; must match the "
                "redirect URI\n        // registered for the mobile client in "
                "Keycloak (Project State Q5).\n"
                f"        manifestPlaceholders += "
                f"[appAuthRedirectScheme: '{REDIRECT_SCHEME}']\n"
            )
            text = text[:insert_at] + placeholder + text[insert_at:]
            changes.append("build.gradle: added appAuthRedirectScheme")

    if text != original:
        path.write_text(text)


def main() -> None:
    if not ANDROID.exists():
        fail("android/ not found. Run `flutter create --platforms=android,ios .` first.")

    patch_manifest()
    patch_gradle()

    if changes:
        print("Applied Android configuration:")
        for change in changes:
            print(f"  - {change}")
    else:
        print("Android configuration already up to date.")

    for warning in warnings:
        print(f"WARNING: {warning}")

    print(
        "\nReminder: INTERNET permission must live in the main manifest, not "
        "only the\ndebug one, or release builds have no network access and "
        "every request times\nout silently."
    )


if __name__ == "__main__":
    main()
