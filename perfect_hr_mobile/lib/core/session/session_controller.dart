import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/app_config.dart';
import 'permissions.dart';
import 'session_state.dart';
import 'user_role.dart';

/// Holds the active session.
///
/// Task 1 scope: state container plus transitions only. Real token exchange
/// (Keycloak OIDC + PKCE), secure storage and refresh land in Task 3
/// (`features/authentication`), which will call [establish] with a session
/// built from verified token claims — never from client-side assumptions.
class SessionController extends Notifier<SessionState> {
  @override
  SessionState build() => const SessionUnauthenticated();

  /// Promotes to an authenticated session. Called only by the authentication
  /// feature after the identity provider and application API have both
  /// confirmed the principal.
  void establish(SessionUser user) {
    state = SessionAuthenticated(user: user);
  }

  void requireMfa(String challengeId) {
    state = SessionAwaitingMfa(challengeId: challengeId);
  }

  /// Clears the session. Task 3 extends this to revoke tokens, purge secure
  /// storage and clear cached data (Instructions §15 — secure logout).
  void signOut({String? reason}) {
    state = SessionUnauthenticated(reason: reason);
  }

  /// DEV/QA ONLY — swaps the active role so the role-aware shell can be
  /// exercised before authentication exists.
  ///
  /// Instructions §22: mock data must be clearly separated and replaceable.
  /// This method is a no-op in UAT and production builds, so it cannot become
  /// a privilege-escalation path if a call site is left behind by accident.
  void devSwitchRole(UserRole role) {
    if (!AppConfig.current.allowsDevTools) {
      assert(
        false,
        'devSwitchRole called in a non-dev flavour. Remove the call site.',
      );
      return;
    }
    state = SessionAuthenticated(user: _devUserFor(role));
  }

  static SessionUser _devUserFor(UserRole role) {
    return SessionUser(
      employeeId: 'DEV-${role.wireValue.toUpperCase()}',
      displayName: switch (role) {
        UserRole.employee => 'Rahim Ahmed',
        UserRole.manager => 'Hasan Rahman',
        UserRole.hr => 'Nabila Islam',
        UserRole.chro => 'Farhana Karim',
        UserRole.executive => 'Tanvir Chowdhury',
        UserRole.superAdmin => 'Platform Admin',
      },
      jobTitle: switch (role) {
        UserRole.employee => 'Software Engineer',
        UserRole.manager => 'Engineering Manager',
        UserRole.hr => 'HR Executive',
        UserRole.chro => 'Chief Human Resources Officer',
        UserRole.executive => 'Chief Executive Officer',
        UserRole.superAdmin => 'SaaS Administrator',
      },
      role: role,
      tenantId: 'dev-tenant',
      tenantName: 'Perfect HR Demo Co.',
      permissions: PermissionSet(_devPermissionsFor(role)),
    );
  }

  /// Approximates the Role × Module matrix (Functional Blueprint §4) for local
  /// development. The production set always arrives from the backend.
  static Set<Permission> _devPermissionsFor(UserRole role) {
    const employee = {
      Permission.attendanceSelfRead,
      Permission.attendanceSelfWrite,
      Permission.leaveSelfWrite,
      Permission.requestSelfWrite,
      Permission.payrollSelfRead,
      Permission.performanceSelfRead,
      Permission.aiAssistant,
    };
    const manager = {
      ...employee,
      Permission.attendanceTeamRead,
      Permission.leaveApprove,
      Permission.performanceTeamRead,
    };
    const hr = {
      ...manager,
      Permission.attendanceOrgRead,
      Permission.requestProcess,
      Permission.workforceRead,
      Permission.recruitmentRead,
      Permission.recruitmentAction,
      Permission.payrollOrgRead,
    };
    const executive = {
      ...hr,
      Permission.executiveIntelligenceRead,
      Permission.attritionIntelligenceRead,
    };

    return switch (role) {
      UserRole.employee => employee,
      UserRole.manager => manager,
      UserRole.hr => hr,
      UserRole.chro || UserRole.executive => executive,
      UserRole.superAdmin => {Permission.tenantAdmin, Permission.aiAssistant},
    };
  }
}

final sessionControllerProvider =
    NotifierProvider<SessionController, SessionState>(SessionController.new);

/// Convenience selector for the active role. Null when unauthenticated.
final activeRoleProvider = Provider<UserRole?>((ref) {
  final session = ref.watch(sessionControllerProvider);
  return session is SessionAuthenticated ? session.role : null;
});

/// Convenience selector for the authenticated user. Null when unauthenticated.
final activeUserProvider = Provider<SessionUser?>((ref) {
  final session = ref.watch(sessionControllerProvider);
  return session is SessionAuthenticated ? session.user : null;
});

/// Whether the UI should render a control guarded by [permission].
///
/// A false result hides affordances. A true result does NOT authorise
/// anything — the backend decides (Instructions §15).
final hasPermissionProvider = Provider.family<bool, Permission>((ref, perm) {
  final user = ref.watch(activeUserProvider);
  return user?.permissions.has(perm) ?? false;
});
