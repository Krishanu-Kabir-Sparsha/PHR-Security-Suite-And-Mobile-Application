import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/capabilities/app_capabilities.dart';

/// The app must not decide its own feature list.
///
/// Which Odoo modules are installed, and which groups the user is in, both vary
/// per deployment and neither is knowable from the client. A hard-coded Leave
/// tab on a server without `hr_holidays` is a screen that can only ever fail,
/// and the user reads that as a broken app rather than as a module their
/// company does not run.
///
/// These tests are mostly about what happens when the server says something
/// unexpected, because that is where a feature flag turns into a crash.

void main() {
  group('parsing', () {
    test('reads the features the server reports', () {
      final capabilities = AppCapabilities.fromJson({
        'features': ['attendance', 'leave', 'security_keys'],
        'has_employee_record': true,
        'hr_modules_installed': ['hr', 'hr_attendance', 'hr_holidays'],
      });

      expect(capabilities.has(AppFeature.attendance), isTrue);
      expect(capabilities.has(AppFeature.leave), isTrue);
      expect(capabilities.has(AppFeature.payslips), isFalse);
      expect(capabilities.hrModulesInstalled, contains('hr_attendance'));
    });

    test('ignores a feature this build has never heard of', () {
      // A newer server may offer features an installed copy predates. It must
      // skip them, not fail to parse and lose the ones it does understand.
      final capabilities = AppCapabilities.fromJson({
        'features': ['attendance', 'time_travel'],
      });

      expect(capabilities.has(AppFeature.attendance), isTrue);
      expect(capabilities.features.length, 1);
    });

    test('survives a malformed or empty body', () {
      for (final body in <Map<String, dynamic>>[
        {},
        {'features': null},
        {'features': 'attendance'},
        {'features': <dynamic>[]},
      ]) {
        final capabilities = AppCapabilities.fromJson(body);
        expect(capabilities.features, isEmpty, reason: 'body: $body');
      }
    });

    test('assumes an employee record when the server does not say', () {
      // An older server that omits the field has not told us the record is
      // missing. Defaulting to false would put "ask HR to complete your
      // profile" in front of every user on that deployment.
      expect(
        AppCapabilities.fromJson({'features': <dynamic>[]}).hasEmployeeRecord,
        isTrue,
      );
      expect(
        AppCapabilities.fromJson({'has_employee_record': false})
            .hasEmployeeRecord,
        isFalse,
      );
    });
  });

  group('the unknown fallback', () {
    test('offers nothing rather than everything', () {
      // Used before the call returns and when it fails. An app that offers a
      // feature it cannot deliver is worse than one that reveals a feature a
      // moment late.
      for (final feature in AppFeature.values) {
        expect(AppCapabilities.unknown.has(feature), isFalse);
      }
    });
  });

  group('the wire contract', () {
    test('every feature key is unique', () {
      // Keys are matched against FEATURE_MATRIX in the Odoo module. A duplicate
      // would make fromWire return whichever came first, silently.
      final keys = AppFeature.values.map((f) => f.wireValue).toList();
      expect(keys.toSet().length, keys.length);
    });

    test('round-trips through the wire value', () {
      for (final feature in AppFeature.values) {
        expect(AppFeature.fromWire(feature.wireValue), feature);
      }
    });
  });
}
