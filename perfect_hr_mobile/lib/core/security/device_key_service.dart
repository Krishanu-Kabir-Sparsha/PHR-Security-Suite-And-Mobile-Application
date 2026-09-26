import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:local_auth/local_auth.dart';
import 'package:local_auth/error_codes.dart' as auth_error;

/// This installation's own signing key, and the fingerprint prompt that
/// releases it.
///
/// ## Why not a passkey
///
/// A passkey is the better mechanism and the app still uses one where the
/// platform will cooperate. But a *native* app can only reach passkeys for a
/// domain if the operating system vendor validates an app-to-domain
/// association on the handset itself. When that validation fails it fails
/// closed, with no server-side fault to find and a message that names nothing
/// actionable. Putting it in the path of daily sign-in means a signing
/// certificate, a store listing and a vendor's cache all sit between a user and
/// the product.
///
/// So this holds a keypair of its own, issued through pairing, and the platform
/// is never asked to vouch for anything.
///
/// ## What is actually protected
///
/// * The private key is generated **here** and never transmitted. Pairing sends
///   the public half; the server stores that and nothing else.
/// * At rest it is in the platform keystore — Keychain on Apple platforms,
///   EncryptedSharedPreferences over Android Keystore, DPAPI on Windows.
/// * It is never read without [LocalAuthentication] succeeding first, so a
///   signature requires the handset *and* the person who can unlock it.
/// * Each signature carries a counter that only ever increases. The server
///   refuses a repeat, which is how a key copied to a second installation shows
///   up rather than quietly working.
///
/// Stated plainly, because it is the real limit: the key is decrypted into
/// process memory for the moment it signs. A secure-element passkey is not.
/// That is a genuine difference on a rooted or jailbroken device, and no
/// difference at all on a device whose lock screen has been handed over, which
/// is the threat this is for.
///
/// ## Platforms
///
/// Android, iOS, macOS and Windows all support both plugins, so one code path
/// covers them. `local_auth` has no Linux or web implementation; there
/// [isSupported] answers false rather than signing without a presence check,
/// because a silent signature would be this control turned off while still
/// appearing to be on.
enum DeviceKeyFailureKind {
  /// No biometric or device-credential check is available on this platform.
  unsupported,

  /// The device has no screen lock, so there is nothing to check against.
  noScreenLock,

  /// The user dismissed the prompt. A decision, not a fault.
  cancelled,

  /// Nothing is paired on this installation yet.
  notPaired,

  /// Too many wrong fingerprints. The platform has stopped accepting them for
  /// now, which is its own lockout and not something this app can retry past.
  lockedOut,

  /// The host Activity cannot raise a biometric prompt. A build fault rather
  /// than anything the user did, and it must be loud: a silent version of this
  /// is the second factor switched off while still appearing to be on.
  unavailableOnThisBuild,

  /// Anything else: a plugin error, a corrupt stored key.
  failed,
}

class DeviceKeyFailure implements Exception {
  const DeviceKeyFailure(this.kind, this.message);

  final DeviceKeyFailureKind kind;
  final String message;

  @override
  String toString() => 'DeviceKeyFailure($kind, $message)';
}

/// What this installation knows about its own pairing.
class DeviceBinding {
  const DeviceBinding({
    required this.handle,
    required this.login,
    required this.label,
    required this.counter,
  });

  /// Server-issued opaque identifier for this device.
  final String handle;

  /// The account this device was paired to, shown so a user can tell.
  final String login;

  final String label;

  /// Last counter used. The next signature uses this plus one.
  final int counter;
}

/// One signature, ready to be posted to the server.
class DeviceSignature {
  const DeviceSignature({
    required this.deviceHandle,
    required this.challenge,
    required this.counter,
    required this.signature,
  });

  final String deviceHandle;
  final String challenge;
  final int counter;
  final String signature;

  Map<String, dynamic> toJson() => {
        'device_handle': deviceHandle,
        'challenge': challenge,
        'counter': counter,
        'signature': signature,
      };
}

abstract class DeviceKeyService {
  /// Whether this platform can gate a key on the user being present.
  Future<bool> get isSupported;

  /// What this installation is paired to, or null.
  Future<DeviceBinding?> get binding;

  /// Generate a keypair and return its public half, base64url unpadded.
  ///
  /// Does **not** store anything: the key is only kept once the server has
  /// accepted it, so a failed pairing cannot leave a private key behind with no
  /// counterpart on the server.
  Future<String> generateKeyPair();

  /// Persist the pairing the server just confirmed.
  Future<void> rememberPairing({
    required String publicKey,
    required String handle,
    required String login,
    required String label,
  });

  /// Prompt for the fingerprint, then sign.
  Future<DeviceSignature> sign({
    required String challenge,
    required String contextRef,
    required String reason,
  });

  /// Forget this installation's pairing. Does not revoke it server-side.
  Future<void> forget();
}

class LocalAuthDeviceKeyService implements DeviceKeyService {
  LocalAuthDeviceKeyService({
    FlutterSecureStorage? storage,
    LocalAuthentication? localAuth,
  })  : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            ),
        _localAuth = localAuth ?? LocalAuthentication();

  /// Bumped only by a breaking change to what gets signed, and matched against
  /// the server's SIGNATURE_DOMAIN. A mismatch is a clear refusal rather than a
  /// signature that mysteriously fails to verify.
  static const String signatureDomain = 'perfecthr-device-v1';

  static const String _bindingKey = 'perfecthr.device.binding';
  static const String _privateKeyKey = 'perfecthr.device.privatekey';

  final FlutterSecureStorage _storage;
  final LocalAuthentication _localAuth;
  final Ed25519 _ed25519 = Ed25519();

  /// Held between [generateKeyPair] and [rememberPairing], never written until
  /// the server has accepted the public half.
  List<int>? _pendingSeed;

  @override
  Future<bool> get isSupported async {
    try {
      // isDeviceSupported covers "no hardware and no PIN"; canCheckBiometrics
      // alone would answer false on a perfectly usable PIN-only handset.
      return await _localAuth.isDeviceSupported();
    } catch (_) {
      return false;
    }
  }

  @override
  Future<DeviceBinding?> get binding async {
    final raw = await _read(_bindingKey);
    if (raw == null || raw.isEmpty) return null;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return null;
      return DeviceBinding(
        handle: decoded['handle'] as String? ?? '',
        login: decoded['login'] as String? ?? '',
        label: decoded['label'] as String? ?? '',
        counter: (decoded['counter'] as num?)?.toInt() ?? 0,
      );
    } catch (_) {
      // Unreadable is treated as unpaired rather than as a crash: the remedy
      // is to pair again, and the user can reach that screen.
      return null;
    }
  }

  @override
  Future<String> generateKeyPair() async {
    final keyPair = await _ed25519.newKeyPair();
    final seed = await keyPair.extractPrivateKeyBytes();
    final publicKey = await keyPair.extractPublicKey();
    _pendingSeed = seed;
    return _b64url(publicKey.bytes);
  }

  @override
  Future<void> rememberPairing({
    required String publicKey,
    required String handle,
    required String login,
    required String label,
  }) async {
    final seed = _pendingSeed;
    if (seed == null) {
      throw const DeviceKeyFailure(
        DeviceKeyFailureKind.failed,
        'No key was generated for this pairing.',
      );
    }
    await _storage.write(key: _privateKeyKey, value: _b64url(seed));
    await _storage.write(
      key: _bindingKey,
      value: jsonEncode({
        'handle': handle,
        'login': login,
        'label': label,
        'counter': 0,
      }),
    );
    _pendingSeed = null;
  }

  @override
  Future<DeviceSignature> sign({
    required String challenge,
    required String contextRef,
    required String reason,
  }) async {
    final current = await binding;
    if (current == null) {
      throw const DeviceKeyFailure(
        DeviceKeyFailureKind.notPaired,
        'This device is not paired to a Perfect HR account yet.',
      );
    }

    if (!await isSupported) {
      throw const DeviceKeyFailure(
        DeviceKeyFailureKind.unsupported,
        'This device cannot check that it is you.',
      );
    }

    final present = await _confirmPresence(reason);
    if (!present) {
      throw const DeviceKeyFailure(
        DeviceKeyFailureKind.cancelled,
        'Confirmation was cancelled.',
      );
    }

    final seedRaw = await _read(_privateKeyKey);
    if (seedRaw == null || seedRaw.isEmpty) {
      throw const DeviceKeyFailure(
        DeviceKeyFailureKind.notPaired,
        'This device\'s security key is missing. Pair the device again.',
      );
    }

    final counter = current.counter + 1;
    // Persisted *before* the signature is handed out. A crash between signing
    // and writing would otherwise let the same counter be used twice, which the
    // server reads as two installations sharing one key and refuses.
    await _storage.write(
      key: _bindingKey,
      value: jsonEncode({
        'handle': current.handle,
        'login': current.login,
        'label': current.label,
        'counter': counter,
      }),
    );

    final message = utf8.encode(
      [
        signatureDomain,
        challenge,
        contextRef,
        current.handle,
        '$counter',
      ].join('\n'),
    );

    try {
      final keyPair = await _ed25519.newKeyPairFromSeed(_b64urlDecode(seedRaw));
      final signature = await _ed25519.sign(message, keyPair: keyPair);
      return DeviceSignature(
        deviceHandle: current.handle,
        challenge: challenge,
        counter: counter,
        signature: _b64url(signature.bytes),
      );
    } catch (error) {
      throw DeviceKeyFailure(
        DeviceKeyFailureKind.failed,
        'This device could not sign the confirmation. $error',
      );
    }
  }

  @override
  Future<void> forget() async {
    await _storage.delete(key: _bindingKey);
    await _storage.delete(key: _privateKeyKey);
    _pendingSeed = null;
  }

  /// Raise the platform prompt. True only if the user actually passed it.
  ///
  /// Returning false means **the user dismissed it**, and nothing else. An
  /// earlier version returned false for every unrecognised error too, which
  /// read as a cancellation upstream and produced no message at all -- so a
  /// host Activity that could not raise a prompt looked exactly like a user
  /// who had changed their mind, and the sign-in button simply did nothing.
  /// Every failure that is not a dismissal now throws.
  Future<bool> _confirmPresence(String reason) async {
    try {
      return await _localAuth.authenticate(
        localizedReason: reason,
        options: const AuthenticationOptions(
          // A PIN or pattern is an acceptable fallback. biometricOnly would
          // lock out anyone whose sensor is wet, worn or absent, and the
          // property being asserted is "the person who can unlock this phone",
          // which a PIN establishes.
          biometricOnly: false,
          stickyAuth: true,
          useErrorDialogs: true,
        ),
      );
    } on PlatformException catch (error) {
      throw _failureFor(error);
    }
  }

  /// Map a platform error onto something the user can act on.
  ///
  /// The default case keeps the platform's own code in the message. It is not
  /// pretty, but an unmapped biometric failure is nearly impossible to
  /// diagnose from a screenshot without it, and a generic "something went
  /// wrong" here costs more than the ugliness does.
  DeviceKeyFailure _failureFor(PlatformException error) {
    switch (error.code) {
      case auth_error.passcodeNotSet:
        return const DeviceKeyFailure(
          DeviceKeyFailureKind.noScreenLock,
          'Set a screen lock on this device, then try again.',
        );
      case auth_error.notEnrolled:
        return const DeviceKeyFailure(
          DeviceKeyFailureKind.noScreenLock,
          'Add a fingerprint, face unlock or screen lock on this device, then '
          'try again.',
        );
      case auth_error.notAvailable:
        return const DeviceKeyFailure(
          DeviceKeyFailureKind.unsupported,
          'This device cannot check that it is you.',
        );
      case auth_error.lockedOut:
        return const DeviceKeyFailure(
          DeviceKeyFailureKind.lockedOut,
          'Too many attempts. Wait a moment, then try again.',
        );
      case auth_error.permanentlyLockedOut:
        return const DeviceKeyFailure(
          DeviceKeyFailureKind.lockedOut,
          'Fingerprint unlock is locked. Unlock this device with your PIN or '
          'password first, then try again.',
        );
      case 'no_fragment_activity':
        // The host Activity is not a FragmentActivity, so BiometricPrompt has
        // no FragmentManager to attach to. See MainActivity.kt -- this is a
        // build fault, and saying so is far more useful than a shrug.
        return const DeviceKeyFailure(
          DeviceKeyFailureKind.unavailableOnThisBuild,
          'This build of the app cannot show the fingerprint prompt. Please '
          'report this - the app needs updating.',
        );
      default:
        return DeviceKeyFailure(
          DeviceKeyFailureKind.failed,
          'The fingerprint check could not run (${error.code}).',
        );
    }
  }

  Future<String?> _read(String key) async {
    try {
      return await _storage.read(key: key);
    } catch (_) {
      return null;
    }
  }

  static String _b64url(List<int> bytes) =>
      base64Url.encode(bytes).replaceAll('=', '');

  static List<int> _b64urlDecode(String value) =>
      base64Url.decode(value + '=' * ((4 - value.length % 4) % 4));
}
