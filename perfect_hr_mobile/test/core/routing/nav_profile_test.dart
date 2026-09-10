import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/constants/screen_ids.dart';
import 'package:perfect_hr_mobile/core/routing/app_routes.dart';
import 'package:perfect_hr_mobile/core/routing/nav_profile.dart';
import 'package:perfect_hr_mobile/core/session/user_role.dart';

/// Guards the navigation contract in UI-UX Specification §5,
/// Functional Blueprint §3 and Instructions §11.
///
/// These assertions are intentionally literal. The navigation structure is an
/// approved product decision, so a change to it should fail a test and force a
/// deliberate spec conversation rather than passing silently.
void main() {
  group('navProfileFor — bottom navigation per role', () {
    test('Employee: Home | Attendance | Requests | AI | More', () {
      final labels = navProfileFor(UserRole.employee)
          .destinations
          .map((d) => d.label)
          .toList();
      expect(labels, ['Home', 'Attendance', 'Requests', 'AI', 'More']);
    });

    test('Manager: Home | Team | Approvals | AI | More', () {
      final labels = navProfileFor(UserRole.manager)
          .destinations
          .map((d) => d.label)
          .toList();
      expect(labels, ['Home', 'Team', 'Approvals', 'AI', 'More']);
    });

    test('HR: Home | Workforce | Approvals | AI | More', () {
      final labels =
          navProfileFor(UserRole.hr).destinations.map((d) => d.label).toList();
      expect(labels, ['Home', 'Workforce', 'Approvals', 'AI', 'More']);
    });

    test('Executive: Home | Insights | Alerts | AI | More', () {
      final labels = navProfileFor(UserRole.executive)
          .destinations
          .map((d) => d.label)
          .toList();
      expect(labels, ['Home', 'Insights', 'Alerts', 'AI', 'More']);
    });

    test('Super Admin: Home | Tenants | Monitoring | AI | More', () {
      final labels = navProfileFor(UserRole.superAdmin)
          .destinations
          .map((d) => d.label)
          .toList();
      expect(labels, ['Home', 'Tenants', 'Monitoring', 'AI', 'More']);
    });

    test('CHRO shares the executive navigation profile (UI-UX §5.4)', () {
      final chro = navProfileFor(UserRole.chro).destinations;
      final ceo = navProfileFor(UserRole.executive).destinations;
      expect(
        chro.map((d) => d.path).toList(),
        ceo.map((d) => d.path).toList(),
      );
    });
  });

  group('structural invariants', () {
    test('every role has exactly five destinations', () {
      for (final role in UserRole.values) {
        expect(
          navProfileFor(role).destinations.length,
          5,
          reason: '${role.name} must expose five destinations',
        );
      }
    });

    test('Home is always first and routes to /home', () {
      for (final role in UserRole.values) {
        final first = navProfileFor(role).destinations.first;
        expect(first.label, 'Home', reason: role.name);
        expect(first.path, AppRoutes.home, reason: role.name);
      }
    });

    test('AI is persistently accessible in position four (UI-UX §36)', () {
      for (final role in UserRole.values) {
        final ai = navProfileFor(role).destinations[3];
        expect(ai.label, 'AI', reason: role.name);
        expect(ai.screenId, ScreenIds.aiHome, reason: role.name);
      }
    });

    test('destination paths are unique within a role', () {
      for (final role in UserRole.values) {
        final paths = navProfileFor(role).destinations.map((d) => d.path);
        expect(paths.toSet().length, paths.length, reason: role.name);
      }
    });

    test('every destination carries a Blueprint screen ID', () {
      for (final role in UserRole.values) {
        for (final destination in navProfileFor(role).destinations) {
          expect(
            destination.screenId,
            matches(RegExp(r'^(E|M|H|X|AI|N|S|SET|SA|AUTH)-\d{2}$')),
            reason: '${role.name} → ${destination.label}',
          );
        }
      }
    });

    test('every destination has a non-empty accessible label', () {
      for (final role in UserRole.values) {
        for (final destination in navProfileFor(role).destinations) {
          expect(destination.semanticLabel, isNotEmpty, reason: role.name);
        }
      }
    });
  });

  group('indexOfLocation', () {
    test('resolves a branch root', () {
      final profile = navProfileFor(UserRole.employee);
      expect(profile.indexOfLocation(AppRoutes.attendance), 1);
      expect(profile.indexOfLocation(AppRoutes.requests), 2);
    });

    test('resolves a nested location to its owning branch', () {
      final profile = navProfileFor(UserRole.employee);
      expect(profile.indexOfLocation(AppRoutes.checkIn), 1);
      expect(profile.indexOfLocation(AppRoutes.applyLeave), 2);
      expect(profile.indexOfLocation(AppRoutes.payroll), 4);
    });

    test('falls back to Home for an unmatched location', () {
      final profile = navProfileFor(UserRole.employee);
      expect(profile.indexOfLocation('/unknown'), 0);
    });

    test('does not match a path that merely shares a prefix', () {
      final profile = navProfileFor(UserRole.manager);
      // '/teamwork' must not resolve to the '/team' branch.
      expect(profile.indexOfLocation('/teamwork'), 0);
    });
  });
}
