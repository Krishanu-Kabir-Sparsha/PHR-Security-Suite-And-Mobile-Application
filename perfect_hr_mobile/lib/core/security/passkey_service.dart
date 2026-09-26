import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Why a passkey ceremony did not produce a credential.
///
/// Separated from a plain failure because three of these are not errors at all
/// and must not be reported as one: a cancellation is a decision, a missing
/// credential means "go and enrol", and an already-registered device means "use
/// a different one". Collapsing them into "something went wrong" is how a user
/// ends up retrying the one thing that cannot work.
enum PasskeyFailureKind {
  /// The user dismissed the system sheet.
  cancelled,

  /// No passkey for this account exists on this device. Route to enrolment.
  noCredential,

  /// This device already holds a passkey for this account, and the server
  /// excluded it. Expected when adding a second device; the remedy is another
  /// device or a security key.
  alreadyRegistered,

  /// Passkeys are not usable here — an old device, no screen lock, or a
  /// platform the bridge does not cover.
  unsupported,

  /// Anything else. [PasskeyFailure.message] carries something readable.
  failed,
}

@immutable
class PasskeyFailure implements Exception {
  const PasskeyFailure(this.kind, this.message);

  final PasskeyFailureKind kind;
  final String message;

  bool get isCancellation => kind == PasskeyFailureKind.cancelled;

  @override
  String toString() => 'PasskeyFailure($kind): $message';
}

/// Creates and uses passkeys through the platform's own credential store.
///
/// **This app is never the authenticator.** The credential is created and held
/// by the phone, in secure hardware. This asks Android to create one or use
/// one, and Android only agrees because the server publishes
/// `/.well-known/assetlinks.json` naming this app's signing certificate.
///
/// Request and response are **WebAuthn JSON, passed through untouched**. The
/// server builds the request and parses the response exactly as it does for the
/// browser, so there is one WebAuthn implementation rather than two that can
/// drift apart. Nothing here inspects or rewrites the payload — the only reason
/// this class knows it is JSON at all is that the platform channel carries a
/// string.
class PasskeyService {
  const PasskeyService({MethodChannel? channel})
      : _channel = channel ?? const MethodChannel('com.perfecthr/passkey');

  final MethodChannel _channel;

  /// Whether a ceremony can be attempted at all.
  ///
  /// Android only, for now. iOS needs Associated Domains and its own bridge;
  /// returning false there is honest, and the caller falls back to the browser.
  Future<bool> get isAvailable async {
    if (!_isSupportedPlatform) return false;
    try {
      return await _channel.invokeMethod<bool>('isAvailable') ?? false;
    } on PlatformException {
      return false;
    } on MissingPluginException {
      // An older build of the app, or a hot reload against one. Not an error
      // worth surfacing — the caller uses the browser instead.
      return false;
    }
  }

  /// What Android sees about this app: package name and signing fingerprint.
  ///
  /// Exists because "RP ID cannot be validated" is unfalsifiable from the
  /// outside. Android refuses when the installed build is not the one the
  /// server's `assetlinks.json` authorises, and the two things that decide
  /// that are invisible to everybody looking at the problem. Reading them off
  /// the handset turns a sequence of guesses about which APK is actually
  /// installed into one glance.
  ///
  /// Neither value is a secret: the fingerprint is published in the server's
  /// own `assetlinks.json`, and anyone can read it off the APK with
  /// `apksigner`.
  Future<Map<String, String>> diagnostics() async {
    if (!_isSupportedPlatform) return const {};
    try {
      final raw = await _channel.invokeMapMethod<String, String>('diagnostics');
      return raw ?? const {};
    } on PlatformException {
      return const {};
    } on MissingPluginException {
      // A build that predates this method. Empty is the honest answer.
      return const {};
    }
  }

  /// Enrol a new passkey. [optionsJson] is the server's creation options.
  ///
  /// Returns the attestation response as JSON, to be posted back verbatim.
  Future<Map<String, dynamic>> create(Map<String, dynamic> optionsJson) {
    return _invoke('create', optionsJson);
  }

  /// Confirm with an existing passkey. [optionsJson] is the server's request
  /// options. Returns the assertion as JSON, to be posted back verbatim.
  Future<Map<String, dynamic>> get(Map<String, dynamic> optionsJson) {
    return _invoke('get', optionsJson);
  }

  Future<Map<String, dynamic>> _invoke(
    String method,
    Map<String, dynamic> optionsJson,
  ) async {
    if (!_isSupportedPlatform) {
      throw const PasskeyFailure(
        PasskeyFailureKind.unsupported,
        'Security keys are not available on this device.',
      );
    }

    try {
      final raw = await _channel.invokeMethod<String>(
        method,
        {'requestJson': jsonEncode(optionsJson)},
      );
      if (raw == null || raw.isEmpty) {
        throw const PasskeyFailure(
          PasskeyFailureKind.failed,
          'Your device did not complete the security check.',
        );
      }
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) {
        throw const PasskeyFailure(
          PasskeyFailureKind.failed,
          'Your device returned something unexpected.',
        );
      }
      return decoded;
    } on PlatformException catch (error) {
      throw PasskeyFailure(_kindFor(error.code), _messageFor(error));
    } on MissingPluginException {
      throw const PasskeyFailure(
        PasskeyFailureKind.unsupported,
        'This version of the app cannot use security keys.',
      );
    } on FormatException {
      throw const PasskeyFailure(
        PasskeyFailureKind.failed,
        'Your device returned something unexpected.',
      );
    }
  }

  static bool get _isSupportedPlatform {
    // Guarded so a widget test, which reports neither, does not attempt a
    // platform call and hang on a channel nothing answers.
    if (kIsWeb) return false;
    return Platform.isAndroid;
  }

  /// Exposed so the mapping can be tested without a platform.
  ///
  /// The guard above refuses on any non-Android host, so a test running on a
  /// desktop never reaches the channel — which makes this the only way to
  /// verify that the three codes which are *not* failures stay distinguishable
  /// from the ones that are.
  @visibleForTesting
  static PasskeyFailureKind kindForCode(String code) => _kindFor(code);

  static PasskeyFailureKind _kindFor(String code) => switch (code) {
        'cancelled' => PasskeyFailureKind.cancelled,
        'no_credential' => PasskeyFailureKind.noCredential,
        'already_registered' => PasskeyFailureKind.alreadyRegistered,
        'no_activity' => PasskeyFailureKind.failed,
        _ => PasskeyFailureKind.failed,
      };

  static String _messageFor(PlatformException error) {
    final message = error.message;
    if (message != null && message.isNotEmpty) return message;
    return 'Your device could not complete the security check.';
  }
}
