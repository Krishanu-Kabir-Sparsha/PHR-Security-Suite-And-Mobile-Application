import 'package:flutter/foundation.dart';

import 'permissions.dart';
import 'user_role.dart';

/// The authenticated principal as reported by the application API.
///
/// Deliberately minimal: only what the shell and headers need. Feature-level
/// profile data belongs to the `authentication`/`dashboard` features and is
/// fetched per screen, so sensitive fields are not held in global state.
@immutable
class SessionUser {
  const SessionUser({
    required this.employeeId,
    required this.displayName,
    required this.role,
    required this.tenantId,
    required this.tenantName,
    this.jobTitle,
    this.avatarUrl,
    this.permissions = PermissionSet.empty,
  });

  final String employeeId;
  final String displayName;
  final UserRole role;

  /// Tenant is established by the identity/application layer and echoed back.
  /// Instructions §16 — the client must never assert or alter tenant context.
  final String tenantId;
  final String tenantName;

  final String? jobTitle;
  final String? avatarUrl;
  final PermissionSet permissions;

  /// First name for greeting copy, e.g. "Good morning, Rahim"
  /// (UI-UX §11, Screen Blueprint E-01).
  String get greetingName => displayName.trim().split(' ').first;
}

/// Global session state.
sealed class SessionState {
  const SessionState();

  /// Value the router keys on. The router is rebuilt only when this changes,
  /// so token refreshes and profile edits never disturb navigation.
  String get navigationSignature;
}

/// No valid session. The router redirects everything to AUTH-01.
class SessionUnauthenticated extends SessionState {
  const SessionUnauthenticated({this.reason});

  /// Optional user-safe reason, e.g. after a session expiry.
  final String? reason;

  @override
  String get navigationSignature => 'unauthenticated';
}

/// Credentials accepted, second factor outstanding (AUTH-03).
class SessionAwaitingMfa extends SessionState {
  const SessionAwaitingMfa({required this.challengeId});

  final String challengeId;

  @override
  String get navigationSignature => 'awaiting-mfa';
}

/// Fully authenticated session.
class SessionAuthenticated extends SessionState {
  const SessionAuthenticated({required this.user});

  final SessionUser user;

  UserRole get role => user.role;

  @override
  String get navigationSignature =>
      'authenticated:${user.role.wireValue}:${user.tenantId}';
}
