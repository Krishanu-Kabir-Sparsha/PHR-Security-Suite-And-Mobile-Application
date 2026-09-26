import 'package:flutter/foundation.dart';
import '../../../core/utilities/server_time.dart';

/// One enrolled security key or passkey.
@immutable
class EnrolledAuthenticator {
  const EnrolledAuthenticator({
    required this.id,
    required this.label,
    this.enrolledAt,
    this.backedUp = false,
    this.mechanism = 'webauthn',
  });

  final String id;
  final String label;
  final DateTime? enrolledAt;

  /// `webauthn` for a passkey, `bound_device` for a paired app.
  ///
  /// Shown because the two are not interchangeable from where the user is
  /// standing. A passkey can be used by a browser on any machine it has synced
  /// to; a paired app's key exists on exactly one handset and can be used only
  /// by this app. A list that rendered both as "security key" left someone
  /// unable to tell which of their three entries was the phone in their hand.
  final String mechanism;

  bool get isPairedApp => mechanism == 'bound_device';

  /// What to call it on screen.
  String get kindLabel => isPairedApp ? 'Paired app' : 'Passkey';

  /// The authenticator reports itself synced to a cloud keychain.
  ///
  /// Surfaced rather than hidden because it changes what possession proves: a
  /// synced passkey is not bound to one piece of hardware, which matters for
  /// the final-approval role. The server sends it; the UI says so plainly.
  final bool backedUp;

  factory EnrolledAuthenticator.fromJson(Map<String, Object?> json) {
    return EnrolledAuthenticator(
      id: json['id'] as String? ?? '',
      label: json['label'] as String? ?? 'Security key',
      enrolledAt: _parseDate(json['enrolled_at']),
      backedUp: json['backed_up'] as bool? ?? false,
      mechanism: json['mechanism'] as String? ?? 'webauthn',
    );
  }

  static DateTime? _parseDate(Object? value) {
    if (value is! String || value.isEmpty) return null;
    return parseServerTime(value);
  }
}

/// Enrolment status for the signed-in user, from `GET /me/authenticators`.
@immutable
class AuthenticatorStatus {
  const AuthenticatorStatus({
    required this.enrolled,
    required this.required_,
    required this.sufficient,
    required this.configured,
    required this.devices,
    this.relyingParty,
    this.enrolUrl,
    this.requiresWebSession = true,
    this.pairedDevices = 0,
  });

  final int enrolled;

  /// How many this user needs. Two for the final-approval role, one for other
  /// approval tiers, zero otherwise. The server decides, so the rule lives in
  /// exactly one place.
  final int required_;

  final bool sufficient;

  /// False when the server has no WebAuthn relying party configured yet, in
  /// which case opening the enrolment page would only show an error block.
  final bool configured;

  final List<EnrolledAuthenticator> devices;
  final String? relyingParty;
  final String? enrolUrl;

  /// The enrolment page is session-authenticated, so the browser will ask for
  /// a sign-in even though the app already holds a token.
  final bool requiresWebSession;

  /// How many paired apps this account has, from the server's own count.
  final int pairedDevices;

  bool get canEnrol => configured && (enrolUrl ?? '').isNotEmpty;

  /// How many more devices are needed, never negative.
  int get outstanding => (required_ - enrolled).clamp(0, required_);

  factory AuthenticatorStatus.fromJson(Map<String, Object?> json) {
    return AuthenticatorStatus(
      enrolled: (json['enrolled'] as num?)?.toInt() ?? 0,
      required_: (json['required'] as num?)?.toInt() ?? 0,
      sufficient: json['sufficient'] as bool? ?? false,
      configured: json['configured'] as bool? ?? false,
      relyingParty: json['relying_party'] as String?,
      enrolUrl: json['enrol_url'] as String?,
      requiresWebSession: json['requires_web_session'] as bool? ?? true,
      pairedDevices: (json['paired_devices'] as num?)?.toInt() ?? 0,
      devices: ((json['devices'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => EnrolledAuthenticator.fromJson(e.cast<String, Object?>()))
          .toList(growable: false),
    );
  }
}
