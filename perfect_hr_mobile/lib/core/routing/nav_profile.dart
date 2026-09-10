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
/// destination changes. Do not alter without a documented product reason.
///
///   Employee  Home | Attendance | Requests  | AI | More
///   Manager   Home | Team       | Approvals | AI | More
///   HR        Home | Workforce  | Approvals | AI | More
///   Executive Home | Insights   | Alerts    | AI | More
///   SuperAdmin Home | Tenants   | Monitoring| AI | More
NavProfile navProfileFor(UserRole role) {
  return switch (role) {
    UserRole.employee => NavProfile(
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
      ),
    UserRole.manager => NavProfile(
        role: role,
        destinations: [
          _home(ScreenIds.managerHome),
          const AppNavDestination(
            label: 'Team',
            path: AppRoutes.team,
            screenId: ScreenIds.myTeam,
            icon: Icons.groups_outlined,
            selectedIcon: Icons.groups,
            semanticLabel: 'My team',
          ),
          const AppNavDestination(
            label: 'Approvals',
            path: AppRoutes.approvals,
            screenId: ScreenIds.approvalInbox,
            icon: Icons.fact_check_outlined,
            selectedIcon: Icons.fact_check,
            semanticLabel: 'Approvals',
          ),
          _ai(),
          _more(),
        ],
      ),
    UserRole.hr => NavProfile(
        role: role,
        destinations: [
          _home(ScreenIds.hrDashboard),
          const AppNavDestination(
            label: 'Workforce',
            path: AppRoutes.workforce,
            screenId: ScreenIds.workforce,
            icon: Icons.badge_outlined,
            selectedIcon: Icons.badge,
            semanticLabel: 'Workforce',
          ),
          const AppNavDestination(
            label: 'Approvals',
            path: AppRoutes.approvals,
            screenId: ScreenIds.hrRequestCenter,
            icon: Icons.fact_check_outlined,
            selectedIcon: Icons.fact_check,
            semanticLabel: 'HR requests and approvals',
          ),
          _ai(),
          _more(),
        ],
      ),
    UserRole.chro || UserRole.executive => NavProfile(
        role: role,
        destinations: [
          _home(ScreenIds.executiveHome),
          const AppNavDestination(
            label: 'Insights',
            path: AppRoutes.insights,
            screenId: ScreenIds.workforceIntelligence,
            icon: Icons.insights_outlined,
            selectedIcon: Icons.insights,
            semanticLabel: 'Workforce insights',
          ),
          const AppNavDestination(
            label: 'Alerts',
            path: AppRoutes.alerts,
            screenId: ScreenIds.notifications,
            icon: Icons.notifications_outlined,
            selectedIcon: Icons.notifications,
            semanticLabel: 'Alerts',
          ),
          _ai(),
          _more(),
        ],
      ),
    UserRole.superAdmin => NavProfile(
        role: role,
        destinations: [
          // Must differ from the Tenants destination below: GoRouter requires
          // route names to be unique within a router instance.
          _home(ScreenIds.saasHome),
          const AppNavDestination(
            label: 'Tenants',
            path: AppRoutes.tenants,
            screenId: ScreenIds.tenantList,
            icon: Icons.apartment_outlined,
            selectedIcon: Icons.apartment,
            semanticLabel: 'Tenants',
          ),
          const AppNavDestination(
            label: 'Monitoring',
            path: AppRoutes.monitoring,
            screenId: ScreenIds.saasMonitoring,
            icon: Icons.monitor_heart_outlined,
            selectedIcon: Icons.monitor_heart,
            semanticLabel: 'Platform monitoring',
          ),
          _ai(),
          _more(),
        ],
      ),
  };
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
