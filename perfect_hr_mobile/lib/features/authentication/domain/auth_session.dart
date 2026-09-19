import 'package:flutter/foundation.dart';

import '../../../core/session/session_state.dart';
import '../../../core/session/user_role.dart';

/// The token pair plus the identity the server reported, as returned by
/// `POST /auth/login` and `POST /auth/refresh`.
///
/// The role and permissions here decide which navigation profile the app
/// builds. They are **advisory for the UI only**: every read and write is
/// authorised again server-side against the user's real Odoo groups, so a
/// tampered client can change what its own menus look like and nothing else.
@immutable
class AuthSession {
  const AuthSession({
    required this.accessToken,
    required this.refreshToken,
    required this.user,
    required this.expiresAt,
  });

  final String accessToken;
  final String refreshToken;
  final SessionUser user;

  /// Absolute, not a duration. A stored duration is meaningless after the
  /// process is killed and relaunched an hour later.
  final DateTime expiresAt;

  bool get isExpired => DateTime.now().isAfter(expiresAt);

  factory AuthSession.fromJson(Map<String, Object?> json) {
    final userJson =
        (json['user'] as Map?)?.cast<String, Object?>() ?? const {};
    // expires_in is seconds from now, per the OAuth convention the endpoint
    // follows. Converted to an absolute instant immediately.
    final seconds = (json['expires_in'] as num?)?.toInt() ?? 3600;
    return AuthSession(
      accessToken: json['access_token'] as String? ?? '',
      refreshToken: json['refresh_token'] as String? ?? '',
      expiresAt: DateTime.now().add(Duration(seconds: seconds)),
      user: sessionUserFromJson(userJson),
    );
  }

  /// Persisted shape. The user block is stored too, so the app can restore a
  /// session on launch without a network round trip — otherwise every cold
  /// start would show a sign-in screen to somebody already signed in.
  Map<String, Object?> toJson() => {
        'access_token': accessToken,
        'refresh_token': refreshToken,
        'expires_at': expiresAt.toIso8601String(),
        'user': sessionUserToJson(user),
      };

  factory AuthSession.fromStored(Map<String, Object?> json) {
    return AuthSession(
      accessToken: json['access_token'] as String? ?? '',
      refreshToken: json['refresh_token'] as String? ?? '',
      expiresAt:
          DateTime.tryParse(json['expires_at'] as String? ?? '') ??
              DateTime.fromMillisecondsSinceEpoch(0),
      user: sessionUserFromJson(
        (json['user'] as Map?)?.cast<String, Object?>() ?? const {},
      ),
    );
  }

  AuthSession copyWith({
    String? accessToken,
    String? refreshToken,
    DateTime? expiresAt,
    SessionUser? user,
  }) {
    return AuthSession(
      accessToken: accessToken ?? this.accessToken,
      refreshToken: refreshToken ?? this.refreshToken,
      expiresAt: expiresAt ?? this.expiresAt,
      user: user ?? this.user,
    );
  }
}

/// Builds a [SessionUser] from the server's `user` block.
///
/// Every field falls back rather than throwing. A sign-in that succeeded must
/// not be undone by a missing job title.
SessionUser sessionUserFromJson(Map<String, Object?> json) {
  return SessionUser(
    employeeId: json['employee_id'] as String? ?? '',
    displayName: json['display_name'] as String? ?? 'Colleague',
    role: UserRole.values.firstWhere(
      (r) => r.wireValue == json['role'],
      // An unknown role from a newer backend degrades to the least privileged
      // experience rather than crashing or, worse, guessing upward.
      orElse: () => UserRole.employee,
    ),
    tenantId: json['tenant_id'] as String? ?? '',
    tenantName: json['tenant_name'] as String? ?? '',
    jobTitle: json['job_title'] as String?,
    avatarUrl: json['avatar_url'] as String?,
  );
}

Map<String, Object?> sessionUserToJson(SessionUser user) => {
      'employee_id': user.employeeId,
      'display_name': user.displayName,
      'role': user.role.wireValue,
      'tenant_id': user.tenantId,
      'tenant_name': user.tenantName,
      'job_title': user.jobTitle,
      'avatar_url': user.avatarUrl,
    };
