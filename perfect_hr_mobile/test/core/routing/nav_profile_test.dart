import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/constants/screen_ids.dart';
import 'package:perfect_hr_mobile/core/routing/app_routes.dart';
import 'package:perfect_hr_mobile/core/routing/nav_profile.dart';
import 'package:perfect_hr_mobile/core/session/user_role.dart';

/// Regression tests for a signed-in session that showed nothing real.
///
/// A super admin signing in against the live server was given the SaaS
/// navigation — Home (SA-00), Tenants (SA-01), Monitoring (SA-02), AI, More.
/// None of those five screens has been built, so every tab rendered a
/// placeholder and the one screen that shows real attendance and leave data
/// (E-01, wired to `GET /me/home`) was unreachable for that role.
///
/// The app looked disconnected from its own backend when authentication,
/// tokens and the data layer were all working correctly.
///
/// The rule these tests hold: **Home must resolve to a screen that exists, for
/// every role.** When a role's own home screen is built, that role's profile
/// can diverge again — and the test for that role changes with it, which is the
/// point of asserting per-role rather than on one profile.

void main() {
  group('every role lands on a screen that exists', () {
    for (final role in UserRole.values) {
      test('${role.wireValue} gets an implemented home', () {
        final profile = navProfileFor(role);

        expect(
          profile.destinations.first.screenId,
          ScreenIds.employeeHome,
          reason: 'E-01 is the only home screen implemented so far',
        );
        expect(profile.initialLocation, AppRoutes.home);
      });

      test('${role.wireValue} can reach More', () {
        // More carries sign-out and the route into security-key enrolment.
        // A role without it is a role that cannot sign out.
        final profile = navProfileFor(role);

        expect(
          profile.destinations.map((d) => d.screenId),
          contains(ScreenIds.more),
        );
      });
    }
  });

  group('branch resolution', () {
    test('a nested path selects its own branch, not Home', () {
      // /more/security must highlight More. indexOfLocation scans in reverse
      // so that a longer path cannot be captured by a shorter prefix.
      final profile = navProfileFor(UserRole.employee);
      final moreIndex = profile.destinations
          .indexWhere((d) => d.screenId == ScreenIds.more);

      expect(profile.indexOfLocation(AppRoutes.security), moreIndex);
      expect(profile.indexOfLocation(AppRoutes.more), moreIndex);
    });

    test('an unknown location falls back to the first branch', () {
      final profile = navProfileFor(UserRole.hr);
      expect(profile.indexOfLocation('/nowhere'), 0);
    });
  });
}
