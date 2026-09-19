import 'package:flutter/material.dart';

import '../constants/screen_ids.dart';
import '../session/user_role.dart';
import 'app_routes.dart';

/// One bottom-navigation destination.
@immutable
class AppNavDestination {
  const AppNavDestination({
    required this.label,
    required this.path,
    required this.screenId,
    required this.icon,
    required this.selectedIcon,
    required this.semanticLabel,
  });

  final String label;

  /// Root path of this navigation branch.
  final String path;

  /// Blueprint screen ID rendered at [path] (Instructions §20).
  final String screenId;

  final IconData icon;
  final IconData selectedIcon;

  /// Screen-reader label. UI-UX §49 requires meaningful accessible labels
  /// rather than relying on the icon alone.
  final String semanticLabel;
}

/// The navigation surface for one role.
@immutable
class NavProfile {
  const NavProfile({required this.role, required this.destinations});

  final UserRole role;
  final List<AppNavDestination> destinations;

  String get initialLocation => destinations.first.path;

  /// Index of the branch owning [location], or 0 when unmatched.
  int indexOfLocation(String location) {
    for (var i = destinations.length - 1; i >= 0; i--) {
      if (location == destinations[i].path ||
          location.startsWith('${destinations[i].path}/')) {
        return i;
      }
    }
    return 0;
  }
}

/// Resolves the bottom navigation for a role.
///
/// Spec: UI-UX Specification §5, Functional Blueprint §3, Instructions §11.
/// The structure stays visually constant across roles — five destinations,
/// with Home first and AI in position four — while the content behind each
/// destination changes. The target, once the role screens exist:
///
///   Employee   Home | Attendance | Requests   | AI | More
///   Manager    Home | Team       | Approvals  | AI | More
///   HR         Home | Workforce  | Approvals  | AI | More
///   Executive  Home | Insights   | Alerts     | AI | More
///   SuperAdmin Home | Tenants    | Monitoring | AI | More
///
/// **Every role currently gets the employee surface**, and that is deliberate
/// rather than an oversight.
///
/// Of the screens in the table above, exactly two are built: E-01 Employee Home
/// and SET-01 More. A super admin signing in was therefore shown SA-00, SA-01
/// and SA-02 — three placeholder screens — and never reached the one screen
/// that renders their real attendance and leave, because Home resolved to
/// SA-00 for their role. The app looked disconnected from its own backend when
/// in fact the data layer was working and the screens simply did not exist yet.
///
/// The employee surface is the honest common denominator: `GET /me/home` is
/// scoped to the authenticated user, so it returns real data for a super admin
/// exactly as it does for an employee. Role-specific navigation returns one
/// role at a time as each role's home screen is built — restore that role's
/// branch from the table above and from `_screenFor` in `app_router.dart`.
NavProfile navProfileFor(UserRole role) {
  return NavProfile(
    role: role,
    destinations: [
      _home(ScreenIds.employeeHome),
      const AppNavDestination(
        label: 'Attendance',
        path: AppRoutes.attendance,
        screenId: ScreenIds.attendanceHome,
        icon: Icons.schedule_outlined,
        selectedIcon: Icons.schedule,
        semanticLabel: 'Attendance',
      ),
      const AppNavDestination(
        label: 'Requests',
        path: AppRoutes.requests,
        screenId: ScreenIds.requestCenter,
        icon: Icons.assignment_outlined,
        selectedIcon: Icons.assignment,
        semanticLabel: 'My requests',
      ),
      _ai(),
      _more(),
    ],
  );
}

AppNavDestination _home(String screenId) => AppNavDestination(
      label: 'Home',
      path: AppRoutes.home,
      screenId: screenId,
      icon: Icons.home_outlined,
      selectedIcon: Icons.home,
      semanticLabel: 'Home',
    );

/// AI is persistently accessible for every role (UI-UX §36).
AppNavDestination _ai() => const AppNavDestination(
      label: 'AI',
      path: AppRoutes.ai,
      screenId: ScreenIds.aiHome,
      icon: Icons.auto_awesome_outlined,
      selectedIcon: Icons.auto_awesome,
      semanticLabel: 'Perfect HR AI assistant',
    );

AppNavDestination _more() => const AppNavDestination(
      label: 'More',
      path: AppRoutes.more,
      screenId: ScreenIds.more,
      icon: Icons.more_horiz_outlined,
      selectedIcon: Icons.more_horiz,
      semanticLabel: 'More',
    );
