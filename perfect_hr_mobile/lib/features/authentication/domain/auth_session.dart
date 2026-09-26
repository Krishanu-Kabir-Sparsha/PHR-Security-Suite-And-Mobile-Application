import 'package:flutter/foundation.dart';

import '../../../core/session/session_state.dart';
import '../../../core/session/user_role.dart';
import '../../../core/utilities/server_time.dart';

/// What signing in did to today's attendance.
///
/// Always present on a completed sign-in, always carrying a status, so the app
/// never has to guess. The statuses are the server's — see
/// `models/mobile_checkin.py` — and the ones that mean "nothing happened" are
/// as important as the one that means it did: a person who expected to be
/// checked in and was not needs to know why, and "you are already checked in"
/// is a different answer from "your company does not do this".
@immutable
class SignInAttendance {
  const SignInAttendance({required this.status, this.checkInAt, this.message});

  final String status;
  final DateTime? checkInAt;
  final String? message;

  bool get wasRecorded => status == 'recorded';

  /// True when a person might reasonably wonder why nothing happened. Drives
  /// whether the home screen bothers explaining itself.
  bool get isWorthExplaining =>
      status == 'on_leave' || status == 'no_employee' || status == 'skipped';

  /// Copy for each outcome, written here so one place decides the wording.
  String get describe => switch (status) {
        'recorded' => 'You were checked in automatically.',
        'already_in' => 'You are already checked in.',
        'already_today' => 'Today\'s attendance is already recorded.',
        'on_leave' => 'You are on approved leave today, so no attendance was '
            'recorded.',
        'disabled' => '',
        'no_employee' => 'No employee record is linked to your account yet, so '
            'attendance could not be recorded. Please ask HR.',
        'skipped' => 'Attendance could not be recorded automatically. You can '
            'check in from the Attendance screen.',
        _ => '',
      };

  static SignInAttendance? fromJson(Object? raw) {
    if (raw is! Map) return null;
    final json = raw.cast<String, Object?>();
    final status = json['status'] as String?;
    if (status == null) return null;
    return SignInAttendance(
      status: status,
      checkInAt: parseServerTime(json['check_in_at']),
      message: json['message'] as String?,
    );
  }
}

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
    this.enrolmentRequired = false,
    this.authMode = 'advance',
    this.attendance,
  });

  final String accessToken;
  final String refreshToken;
  final SessionUser user;

  /// Absolute, not a duration. A stored duration is meaningless after the
  /// process is killed and relaunched an hour later.
  final DateTime expiresAt;

  /// This session was issued on a password alone, because the account has no
  /// security device enrolled yet.
  ///
  /// The server restricts such a token to the enrolment endpoints, so the app
  /// must take the user there rather than to Home: everything else answers 403,
  /// and a user bouncing off permission errors with no explanation would
  /// reasonably conclude the app was broken.
  final bool enrolmentRequired;

  /// `advance` or `basic`. Not the same question as [enrolmentRequired]:
  /// enrolment is about whether a device exists, this is about which proof was
  /// actually given.
  final String authMode;

  /// Present on a fresh sign-in, absent on a refresh — a refresh is the app
  /// renewing a token, not a person arriving at work.
  final SignInAttendance? attendance;

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
      enrolmentRequired: json['enrolment_required'] as bool? ?? false,
      // Defaults to the stronger value, so a server too old to report it is
      // not described as weaker than it is. The app only ever *offers* an
      // upgrade off the capabilities endpoint, which is authoritative.
      authMode: json['auth_mode'] as String? ?? 'advance',
      attendance: SignInAttendance.fromJson(json['attendance']),
    );
  }

  /// Persisted shape. The user block is stored too, so the app can restore a
  /// session on launch without a network round trip — otherwise every cold
  /// start would show a sign-in screen to somebody already signed in.
  ///
  /// [attendance] is deliberately not persisted. It describes one moment this
  /// morning; restoring it tomorrow would tell somebody they had just been
  /// checked in when they had not.
  Map<String, Object?> toJson() => {
        'access_token': accessToken,
        'refresh_token': refreshToken,
        'expires_at': expiresAt.toIso8601String(),
        'user': sessionUserToJson(user),
        'enrolment_required': enrolmentRequired,
        'auth_mode': authMode,
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
      // Must survive a restart. Without it a returning user is restored
      // straight to Home holding a token the server restricts to enrolment,
      // and every screen answers 403 with no explanation.
      enrolmentRequired: json['enrolment_required'] as bool? ?? false,
      authMode: json['auth_mode'] as String? ?? 'advance',
    );
  }

  AuthSession copyWith({
    String? accessToken,
    String? refreshToken,
    DateTime? expiresAt,
    SessionUser? user,
    bool? enrolmentRequired,
    String? authMode,
    SignInAttendance? attendance,
  }) {
    return AuthSession(
      accessToken: accessToken ?? this.accessToken,
      refreshToken: refreshToken ?? this.refreshToken,
      expiresAt: expiresAt ?? this.expiresAt,
      enrolmentRequired: enrolmentRequired ?? this.enrolmentRequired,
      authMode: authMode ?? this.authMode,
      attendance: attendance ?? this.attendance,
      user: user ?? this.user,
    );
  }
}

/// Builds a [SessionUser] from the server's `user` block.
///
/// Every field falls back rather than throwing. A sign-in that succeeded must
/// not be undone by a missing job title.
SessionUser sessionUserFromJson(Map<String, Object?> json) {
  final employmentJson = (json['employment'] as Map?)?.cast<String, Object?>();
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
    companyId: '${json['company_id'] ?? ''}',
    companyName: json['company_name'] as String? ?? '',
    companies: ((json['companies'] as List?) ?? const [])
        .whereType<Map>()
        .map((c) => SessionCompany(
              id: '${c['id'] ?? ''}',
              name: '${c['name'] ?? ''}',
            ))
        .toList(growable: false),
    jobTitle: json['job_title'] as String?,
    avatarUrl: json['avatar_url'] as String?,
    employment:
        employmentJson == null ? null : Employment.fromJson(employmentJson),
  );
}

Map<String, Object?> sessionUserToJson(SessionUser user) => {
      'employee_id': user.employeeId,
      'display_name': user.displayName,
      'role': user.role.wireValue,
      'tenant_id': user.tenantId,
      'tenant_name': user.tenantName,
      'company_id': user.companyId,
      'company_name': user.companyName,
      'companies': [
        for (final company in user.companies)
          {'id': company.id, 'name': company.name},
      ],
      'job_title': user.jobTitle,
      'avatar_url': user.avatarUrl,
      'employment': user.employment?.toJson(),
    };
