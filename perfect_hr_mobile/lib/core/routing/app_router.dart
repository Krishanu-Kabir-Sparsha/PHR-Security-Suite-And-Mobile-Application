import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/authentication/presentation/welcome_screen.dart';
import '../../features/attendance/presentation/attendance_screen.dart';
import '../../features/leave/presentation/leave_screen.dart';
import '../../features/dashboard/presentation/employee_home_screen.dart';
import '../../shared/components/app_shell.dart';
import '../../shared/screens/screen_placeholder.dart';
import '../constants/screen_ids.dart';
import '../session/session_controller.dart';
import '../session/session_state.dart';
import '../session/user_role.dart';
import 'app_routes.dart';
import '../../features/authentication/presentation/login_screen.dart';
import '../../features/settings/presentation/more_screen.dart';
import '../../features/settings/presentation/security_screen.dart';
import 'nav_profile.dart';

/// Application router.
///
/// The router instance is rebuilt only when [SessionState.navigationSignature]
/// changes — that is, on sign-in, sign-out, tenant change or role change. Token
/// refreshes and profile edits leave navigation untouched.
///
/// Rebuilding per role lets the shell's branch set be derived from the role's
/// [NavProfile], which keeps the navigation contract in exactly one place
/// (Instructions §11) instead of being duplicated across a static branch list.
final routerProvider = Provider<GoRouter>((ref) {
  final signature = ref.watch(
    sessionControllerProvider.select((s) => s.navigationSignature),
  );
  final session = ref.read(sessionControllerProvider);
  final role = session is SessionAuthenticated ? session.role : null;

  return _buildRouter(ref, role: role, signature: signature);
});

GoRouter _buildRouter(
  Ref ref, {
  required UserRole? role,
  required String signature,
}) {
  final profile = role == null ? null : navProfileFor(role);

  return GoRouter(
    debugLogDiagnostics: false,
    initialLocation: profile?.initialLocation ?? AppRoutes.welcome,
    restorationScopeId: 'perfect_hr_router_$signature',
    redirect: (context, state) {
      final current = ref.read(sessionControllerProvider);
      final target = state.matchedLocation;
      final isAuthRoute = target.startsWith('/welcome') ||
          target.startsWith('/login');

      // Unauthenticated users may only reach authentication routes.
      if (current is! SessionAuthenticated) {
        return isAuthRoute ? null : AppRoutes.welcome;
      }
      // Authenticated users are pushed out of the authentication flow.
      if (isAuthRoute) return AppRoutes.home;
      return null;
    },
    routes: [
      // ---- Authentication (outside the shell) ----------------------------
      GoRoute(
        path: AppRoutes.welcome,
        name: ScreenIds.authWelcome,
        builder: (_, __) => const WelcomeScreen(),
      ),
      GoRoute(
        path: AppRoutes.login,
        name: ScreenIds.authLogin,
        builder: (_, __) => const LoginScreen(),
        routes: [
          GoRoute(
            path: 'mfa',
            name: ScreenIds.authMfa,
            builder: (_, __) => const ScreenPlaceholder(
              screenId: ScreenIds.authMfa,
              title: 'Verification',
              purpose: 'Four-digit code sent to the registered device.',
              plannedTask: 'Task 3 — Authentication',
            ),
          ),
          GoRoute(
            path: 'biometric',
            name: ScreenIds.authBiometric,
            builder: (_, __) => const ScreenPlaceholder(
              screenId: ScreenIds.authBiometric,
              title: 'Welcome Back',
              purpose: 'Biometric re-authentication for returning users.',
              plannedTask: 'Task 3 — Authentication',
            ),
          ),
        ],
      ),

      // ---- Role-aware shell ----------------------------------------------
      if (profile != null)
        StatefulShellRoute.indexedStack(
          builder: (context, state, navigationShell) => AppShell(
            profile: profile,
            navigationShell: navigationShell,
          ),
          branches: [
            for (final destination in profile.destinations)
              StatefulShellBranch(
                navigatorKey: GlobalKey<NavigatorState>(
                  debugLabel: 'branch-${destination.path}',
                ),
                routes: [
                  GoRoute(
                    path: destination.path,
                    name: destination.screenId,
                    builder: (_, __) => _screenFor(destination.screenId),
                    routes: _nestedRoutesFor(destination.path),
                  ),
                ],
              ),
          ],
        ),

      // ---- Full-screen routes above the shell ----------------------------
      // N-01 is registered here for roles that reach notifications from the
      // header. The Executive profile already owns N-01 as its Alerts branch,
      // and GoRouter requires unique route names within a router instance, so
      // the top-level registration is skipped in that case.
      if (!_profileOwnsNotifications(profile))
        GoRoute(
          path: AppRoutes.notifications,
          name: ScreenIds.notifications,
          builder: (_, __) => const ScreenPlaceholder(
            screenId: ScreenIds.notifications,
            title: 'Notifications',
            purpose:
                'Critical / Action Required / Insight / Informational grouping.',
            plannedTask: 'Task 8 — Notifications',
          ),
        ),
      GoRoute(
        path: AppRoutes.search,
        name: ScreenIds.globalSearch,
        builder: (_, __) => const ScreenPlaceholder(
          screenId: ScreenIds.globalSearch,
          title: 'Search Perfect HR',
          purpose: 'Keyword and semantic search across people, requests, docs.',
          plannedTask: 'Release 1, late — Global Search',
        ),
      ),
    ],
    errorBuilder: (context, state) => ScreenPlaceholder(
      screenId: '—',
      title: 'Page unavailable',
      purpose: "We couldn't open that screen.",
      plannedTask: 'Route: ${state.uri}',
    ),
  );
}

/// Returns the implemented screen for a branch root, or a placeholder.
///
/// Each feature task replaces one entry here. When the switch has no default
/// left to fall through to, Release 1 route coverage is complete.
Widget _screenFor(String screenId) {
  return switch (screenId) {
    ScreenIds.employeeHome => const EmployeeHomeScreen(),
    ScreenIds.attendanceHome => const AttendanceScreen(),
    ScreenIds.more => const MoreScreen(),
    _ => ScreenPlaceholder(
        screenId: screenId,
        title: _branchTitle(screenId),
        purpose: _branchPurpose(screenId),
        plannedTask: _branchTask(screenId),
      ),
  };
}

String _branchTitle(String screenId) => switch (screenId) {
      ScreenIds.managerHome ||
      ScreenIds.hrDashboard ||
      ScreenIds.executiveHome ||
      ScreenIds.saasHome =>
        'Home',
      ScreenIds.attendanceHome => 'Attendance',
      ScreenIds.requestCenter => 'Requests',
      ScreenIds.myTeam => 'Team',
      ScreenIds.approvalInbox || ScreenIds.hrRequestCenter => 'Approvals',
      ScreenIds.workforce => 'Workforce',
      ScreenIds.workforceIntelligence => 'Insights',
      ScreenIds.notifications => 'Alerts',
      ScreenIds.tenantList => 'Tenants',
      ScreenIds.saasMonitoring => 'Monitoring',
      ScreenIds.aiHome => 'Perfect HR AI',
      ScreenIds.more => 'More',
      _ => 'Perfect HR',
    };

/// Whether the role's bottom navigation already exposes N-01 as a branch.
bool _profileOwnsNotifications(NavProfile? profile) {
  if (profile == null) return false;
  return profile.destinations
      .any((d) => d.screenId == ScreenIds.notifications);
}

/// Nested routes belonging to a shell branch.
///
/// Registered now so that every Release 1 screen ID has a reachable route and
/// a stable deep link. Each feature task replaces its placeholder builder with
/// the real screen; no route restructuring is needed later.
List<RouteBase> _nestedRoutesFor(String branchPath) {
  return switch (branchPath) {
    AppRoutes.attendance => [
        _placeholderRoute(
          path: 'check-in',
          screenId: ScreenIds.checkInConfirmation,
          title: 'Check In',
          purpose: 'Location-verified attendance confirmation.',
          task: 'Task 5 — Attendance',
        ),
        _placeholderRoute(
          path: 'calendar',
          screenId: ScreenIds.attendanceCalendar,
          title: 'Attendance Calendar',
          purpose: 'Month grid with present/late/absent/leave markers.',
          task: 'Task 5 — Attendance',
        ),
        _placeholderRoute(
          path: 'correction',
          screenId: ScreenIds.attendanceCorrection,
          title: 'Attendance Correction',
          purpose: 'Request a correction with reason and attachment.',
          task: 'Task 5 — Attendance',
        ),
      ],
    AppRoutes.requests => [
        // 'leave' must precede ':requestId' so it is not swallowed as an ID.
        GoRoute(
          path: 'leave',
          name: ScreenIds.leaveDashboard,
          builder: (_, __) => const LeaveScreen(),
          routes: [
            // E-06 is a bottom sheet over E-05, not a page: applying is a
            // decision made while looking at a balance, and a full screen
            // hides the number being decided against. The route stays
            // registered so an existing deep link still resolves — it lands
            // on E-05, which is where the Apply button is.
            GoRoute(
              path: 'apply',
              name: ScreenIds.applyLeave,
              redirect: (_, __) => AppRoutes.leave,
            ),
          ],
        ),
        _placeholderRoute(
          path: ':requestId',
          screenId: ScreenIds.requestDetail,
          title: 'Request Detail',
          purpose: 'Approval timeline and document download.',
          task: 'Task 7 — Requests',
        ),
      ],
    AppRoutes.team => [
        _placeholderRoute(
          path: 'attendance',
          screenId: ScreenIds.teamAttendance,
          title: 'Team Attendance',
          purpose: 'Today plus trend and AI exception insight.',
          task: 'Task 10 — Manager',
        ),
        _placeholderRoute(
          path: ':employeeId',
          screenId: ScreenIds.employee360,
          title: 'Employee',
          purpose: 'Compact 360° profile with AI summary.',
          task: 'Task 10 — Manager',
        ),
      ],
    AppRoutes.approvals => [
        _placeholderRoute(
          path: ':approvalId',
          screenId: ScreenIds.approvalDetail,
          title: 'Approval',
          purpose:
              'Context, team impact, AI recommendation, human decision.',
          task: 'Task 11 — Approvals',
        ),
      ],
    AppRoutes.workforce => [
        _placeholderRoute(
          path: 'recruitment',
          screenId: ScreenIds.recruitmentDashboard,
          title: 'Recruitment',
          purpose: 'Pipeline counts and candidate list.',
          task: 'Task 13 — HR Recruitment',
          children: [
            _placeholderRoute(
              path: ':candidateId',
              screenId: ScreenIds.candidateDetail,
              title: 'Candidate',
              purpose: 'AI match score, strengths, gaps, interview focus.',
              task: 'Task 13 — HR Recruitment',
            ),
          ],
        ),
        _placeholderRoute(
          path: ':employeeId',
          screenId: ScreenIds.hrEmployeeDetail,
          title: 'Employee',
          purpose: 'Full HR record in collapsible sections.',
          task: 'Task 12 — HR Workforce',
        ),
      ],
    AppRoutes.insights => [
        _placeholderRoute(
          path: ':insightId',
          screenId: ScreenIds.executiveInsightDetail,
          title: 'Workforce Insight',
          purpose: 'Signal → Evidence → Impact → Recommendation → Action.',
          task: 'Task 14 — Executive Intelligence',
        ),
      ],
    AppRoutes.ai => [
        _placeholderRoute(
          path: 'conversation',
          screenId: ScreenIds.aiConversation,
          title: 'Perfect HR AI',
          purpose: 'Streaming conversational response with actions.',
          task: 'Task 9 — AI Assistant',
        ),
      ],
    AppRoutes.more => [
        _placeholderRoute(
          path: 'payroll',
          screenId: ScreenIds.payrollHome,
          title: 'Payroll',
          purpose: 'Masked net salary, breakdown, Ask Payroll AI.',
          task: 'Task 8 — Payroll',
          children: [
            _placeholderRoute(
              path: ':payslipId',
              screenId: ScreenIds.payslipDetail,
              title: 'Payslip',
              purpose: 'Earnings, deductions, net; download and share.',
              task: 'Task 8 — Payroll',
            ),
          ],
        ),
        _placeholderRoute(
          path: 'profile',
          screenId: ScreenIds.employeeProfile,
          title: 'My Profile',
          purpose: 'Personal, employment, skills, documents.',
          task: 'Task 7 — Profile',
        ),
        // SET-02. Real screen rather than a placeholder: security-key
        // enrolment is the one part of Task 3 that does not depend on the
        // authentication work, because the ceremony happens in the browser.
        GoRoute(
          path: 'security',
          name: ScreenIds.security,
          builder: (_, __) => const SecurityScreen(),
        ),
      ],
    _ => const [],
  };
}

GoRoute _placeholderRoute({
  required String path,
  required String screenId,
  required String title,
  required String purpose,
  required String task,
  List<RouteBase> children = const [],
}) {
  return GoRoute(
    path: path,
    name: screenId,
    builder: (_, __) => ScreenPlaceholder(
      screenId: screenId,
      title: title,
      purpose: purpose,
      plannedTask: task,
    ),
    routes: children,
  );
}

String _branchPurpose(String screenId) => switch (screenId) {
      ScreenIds.employeeHome =>
        'Today, quick actions, my HR status, AI insight, pending items.',
      ScreenIds.managerHome =>
        'Team snapshot, quick actions, AI team insight.',
      ScreenIds.hrDashboard =>
        'Workforce KPIs, exceptions, AI HR intelligence.',
      ScreenIds.executiveHome =>
        'Workforce health and today\'s HR intelligence.',
      ScreenIds.attendanceHome =>
        'Today\'s status, times, month summary, calendar and history.',
      ScreenIds.requestCenter => 'Request inbox: All / Pending / Completed.',
      ScreenIds.myTeam => 'Team roster with live status.',
      ScreenIds.approvalInbox =>
        'Unified approval inbox with AI recommendations.',
      ScreenIds.hrRequestCenter => 'HR request queue with SLA tracking.',
      ScreenIds.workforce => 'Employee directory, search and filters.',
      ScreenIds.workforceIntelligence =>
        'Headcount, attrition, productivity, workforce cost.',
      ScreenIds.notifications =>
        'Critical / Action Required / Insight / Informational.',
      ScreenIds.aiHome => 'Ask Perfect HR AI, role-specific suggested prompts.',
      ScreenIds.more => 'Profile, payroll, policies, security, settings.',
      ScreenIds.tenantList => 'Tenant list, subscription and usage.',
      ScreenIds.saasMonitoring => 'Platform alerts, AI and API usage.',
      _ => 'Screen scope defined in the Screen & Wireframe Blueprint.',
    };

String _branchTask(String screenId) => switch (screenId) {
      ScreenIds.employeeHome => 'Task 4 — Employee Home',
      ScreenIds.attendanceHome => 'Task 5 — Attendance',
      ScreenIds.requestCenter => 'Task 7 — Requests',
      ScreenIds.managerHome || ScreenIds.myTeam => 'Task 10 — Manager',
      ScreenIds.approvalInbox => 'Task 11 — Approvals',
      ScreenIds.hrDashboard || ScreenIds.workforce => 'Task 12 — HR',
      ScreenIds.hrRequestCenter => 'Task 12 — HR',
      ScreenIds.executiveHome || ScreenIds.workforceIntelligence =>
        'Task 14 — Executive Intelligence',
      ScreenIds.aiHome => 'Task 9 — AI Assistant',
      ScreenIds.notifications => 'Task 8 — Notifications',
      ScreenIds.more => 'Task 7 — Settings',
      _ => 'Release 2 or later',
    };
