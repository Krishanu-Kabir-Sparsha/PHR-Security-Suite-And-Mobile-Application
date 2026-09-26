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
    this.companyId = '',
    this.companyName = '',
    this.companies = const [],
    this.jobTitle,
    this.avatarUrl,
    this.employment,
    this.permissions = PermissionSet.empty,
  });

  final String employeeId;
  final String displayName;
  final UserRole role;

  /// The workspace — one database, one customer. Under host-based dbfilter this
  /// is the hostname.
  ///
  /// Established by the server and echoed back. Instructions §16 — the client
  /// must never assert or alter tenant context.
  final String tenantId;
  final String tenantName;

  /// The company *inside* that workspace this session is operating in.
  ///
  /// Separate from the tenant, and the distinction is load-bearing: a tenant
  /// has one database and may have several companies. These were conflated
  /// until the company step was added, which meant a two-company customer had
  /// no way to say which employment they were signing in to.
  final String companyId;
  final String companyName;

  /// Every company this person could switch to without signing out.
  final List<SessionCompany> companies;

  final String? jobTitle;
  final String? avatarUrl;

  /// Position and standing. Null when HR has not linked an employee record yet,
  /// which is a data task rather than a fault — the session still works.
  final Employment? employment;

  final PermissionSet permissions;

  /// True when there is more than one company to switch between. Drives whether
  /// the company switcher is drawn at all.
  bool get canSwitchCompany => companies.length > 1;

  /// First name for greeting copy, e.g. "Good morning, Rahim"
  /// (UI-UX §11, Screen Blueprint E-01).
  String get greetingName => displayName.trim().split(' ').first;
}

/// A company the user may operate in.
@immutable
class SessionCompany {
  const SessionCompany({required this.id, required this.name});

  final String id;
  final String name;
}

/// Who somebody is, as opposed to what they may do.
///
/// The authorisation half of the session is [SessionUser.permissions] and the
/// capabilities endpoint. This is the other half, and the app needs both: a
/// list of roles means very little to the person holding it until it sits next
/// to their own job title and department.
///
/// Every field is nullable. A new joiner whose record is half-filled must still
/// get a working session, so nothing here is ever required.
@immutable
class Employment {
  const Employment({
    this.employeeCode,
    this.jobPosition,
    this.jobTitle,
    this.department,
    this.manager,
    this.workLocation,
    this.shift,
    this.status,
  });

  /// The Employee ID / badge number — the same value the fingerprint terminals
  /// match punches on, and one of the two things somebody can sign in with.
  final String? employeeCode;

  final String? jobPosition;
  final String? jobTitle;
  final String? department;
  final String? manager;
  final String? workLocation;
  final String? shift;

  /// Contract state, where hr_contract is installed. Null rather than assumed:
  /// "active" asserted about somebody whose contract ended is worse than
  /// saying nothing.
  final String? status;

  bool get isEmpty =>
      employeeCode == null &&
      jobPosition == null &&
      jobTitle == null &&
      department == null &&
      manager == null;

  factory Employment.fromJson(Map<String, Object?> json) => Employment(
        employeeCode: json['employee_code'] as String?,
        jobPosition: json['job_position'] as String?,
        jobTitle: json['job_title'] as String?,
        department: json['department'] as String?,
        manager: json['manager'] as String?,
        workLocation: json['work_location'] as String?,
        shift: json['shift'] as String?,
        status: json['employment_status'] as String?,
      );

  Map<String, Object?> toJson() => {
        'employee_code': employeeCode,
        'job_position': jobPosition,
        'job_title': jobTitle,
        'department': department,
        'manager': manager,
        'work_location': workLocation,
        'shift': shift,
        'employment_status': status,
      };
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
  const SessionAuthenticated({
    required this.user,
    this.enrolmentRequired = false,
    this.authMode = 'advance',
  });

  final SessionUser user;

  /// Which proof produced this session: `advance` (password plus a signature
  /// from the paired handset) or `basic` (password alone).
  ///
  /// Carried in state rather than fetched where needed, because Settings shows
  /// it and because a basic session is a real reduction the user is entitled
  /// to see.
  final String authMode;

  bool get isBasicSession => authMode == 'basic';

  /// Signed in on a password alone, with no security device registered.
  ///
  /// The server restricts such a session to the enrolment endpoints, so the
  /// router must send the user there rather than to Home. Part of the
  /// navigation signature below for exactly that reason: finishing enrolment
  /// has to rebuild the router, or the person would stay stuck on the screen
  /// they have just satisfied.
  final bool enrolmentRequired;

  UserRole get role => user.role;

  // Company is part of the signature because switching it changes what every
  // screen shows. Without it the router would keep the tree it built for the
  // previous company and the switch would appear to do nothing.
  @override
  String get navigationSignature =>
      'authenticated:${user.role.wireValue}:${user.tenantId}:${user.companyId}'
      ':${enrolmentRequired ? 'enrolling' : 'ready'}';
}
