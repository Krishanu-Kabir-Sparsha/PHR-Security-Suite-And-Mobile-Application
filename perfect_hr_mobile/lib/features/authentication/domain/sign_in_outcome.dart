import 'package:flutter/foundation.dart';

import '../../../core/security/second_factor.dart';
import 'auth_session.dart';

export '../../../core/security/second_factor.dart' show SecondFactorMethod;

/// What the server said in answer to a password.
///
/// A password alone is no longer a sign-in, so this is deliberately not
/// `AuthSession?`. There are two successful outcomes and they are not the same
/// thing: one is a session, the other is a demand for a second factor, and a
/// nullable session would have flattened them into "worked" and "did not".
sealed class SignInOutcome {
  const SignInOutcome();
}

/// Signed in. The second factor passed, or none was required.
class SignInComplete extends SignInOutcome {
  const SignInComplete(this.session);

  final AuthSession session;
}

/// The password was right; now prove it is you.
///
/// No token exists at this point, and none will until the device confirms. The
/// [mfaToken] is a handle to the half-finished sign-in and is worth nothing on
/// its own — it cannot read anything and expires in minutes.
@immutable
class SignInNeedsDevice extends SignInOutcome {
  const SignInNeedsDevice({
    required this.mfaToken,
    required this.method,
    this.challenge = const <String, dynamic>{},
    this.deviceChallenge = const <String, dynamic>{},
  });

  final String mfaToken;

  final SecondFactorMethod method;

  /// The server's WebAuthn request options, passed to the platform untouched.
  /// Empty when [method] is [SecondFactorMethod.device].
  final Map<String, dynamic> challenge;

  /// `{version, challenge, context_ref, devices}` for the paired-key path.
  /// Empty when [method] is [SecondFactorMethod.passkey].
  final Map<String, dynamic> deviceChallenge;

  /// The nonce this installation must sign.
  String get challengeValue => '${deviceChallenge['challenge'] ?? ''}';

  /// What the signature authorises. Signed alongside the nonce so a
  /// confirmation given to sign in cannot be replayed as an approval.
  String get contextRef => '${deviceChallenge['context_ref'] ?? ''}';

  factory SignInNeedsDevice.fromJson(Map<String, dynamic> json) {
    Map<String, dynamic> asMap(Object? value) =>
        value is Map ? value.cast<String, dynamic>() : const <String, dynamic>{};

    return SignInNeedsDevice(
      mfaToken: '${json['mfa_token'] ?? ''}',
      method: parseSecondFactorMethod(json['mfa_method']),
      challenge: asMap(json['challenge']),
      deviceChallenge: asMap(json['device_challenge']),
    );
  }
}
