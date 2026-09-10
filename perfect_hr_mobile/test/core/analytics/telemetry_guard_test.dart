import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/analytics/telemetry.dart';

/// Covers Instructions §27 and UI-UX §59.
///
/// A telemetry leak is silent: nothing in the app reveals that a salary figure
/// or a leave reason was attached to an analytics event. So the guard is
/// tested against the specific fields most likely to be added carelessly.
void main() {
  group('sensitive keys are dropped', () {
    test('compensation fields', () {
      for (final key in [
        'salary',
        'net_salary',
        'netSalary',
        'basic_salary',
        'gross_pay',
        'wage',
        'compensation',
      ]) {
        expect(TelemetryGuard.isSafeKey(key), isFalse, reason: key);
      }
    });

    test('identity and contact fields', () {
      for (final key in [
        'employee_name',
        'full_name',
        'email',
        'phone',
        'mobile_number',
        'address',
        'nid',
        'national_id',
        'passport_number',
        'date_of_birth',
        'dob',
      ]) {
        expect(TelemetryGuard.isSafeKey(key), isFalse, reason: key);
      }
    });

    test('banking fields', () {
      for (final key in [
        'bank_account',
        'account_number',
        'iban',
        'routing_number',
      ]) {
        expect(TelemetryGuard.isSafeKey(key), isFalse, reason: key);
      }
    });

    test('credentials and second factors', () {
      for (final key in ['password', 'access_token', 'secret', 'otp']) {
        expect(TelemetryGuard.isSafeKey(key), isFalse, reason: key);
      }
    });

    test('free-text fields that commonly hold personal detail', () {
      for (final key in [
        'reason',
        'leave_reason',
        'comment',
        'note',
        'message',
        'ai_query',
      ]) {
        expect(TelemetryGuard.isSafeKey(key), isFalse, reason: key);
      }
    });
  });

  group('non-identifying keys are allowed', () {
    test('categorical and count dimensions', () {
      for (final key in [
        'screen_id',
        'role',
        'leave_type',
        'duration_days',
        'request_type',
        'decision',
        'source',
        'attempt_count',
        'is_offline',
        'confidence_band',
      ]) {
        expect(TelemetryGuard.isSafeKey(key), isTrue, reason: key);
      }
    });

    test('the AI query *category* is allowed while the query text is not', () {
      expect(TelemetryGuard.isSafeKey('query_category'), isTrue);
      expect(TelemetryGuard.isSafeKey('ai_query'), isFalse);
    });
  });

  group('value shape', () {
    test('primitives are allowed', () {
      expect(TelemetryGuard.isSafeValue(null), isTrue);
      expect(TelemetryGuard.isSafeValue(true), isTrue);
      expect(TelemetryGuard.isSafeValue(42), isTrue);
      expect(TelemetryGuard.isSafeValue(3.5), isTrue);
      expect(TelemetryGuard.isSafeValue('E-01'), isTrue);
    });

    test('long strings are rejected as probable free text', () {
      expect(TelemetryGuard.isSafeValue('x' * 41), isFalse);
      expect(
        TelemetryGuard.isSafeValue(
          'I need leave because my mother is in hospital in Sylhet',
        ),
        isFalse,
      );
    });

    test('structured values are rejected — a map can hide anything', () {
      expect(TelemetryGuard.isSafeValue({'salary': 1}), isFalse);
      expect(TelemetryGuard.isSafeValue([1, 2, 3]), isFalse);
    });
  });

  group('sanitise', () {
    test('keeps safe parameters and drops the rest', () {
      final result = TelemetryGuard.sanitise({
        'screen_id': 'E-07',
        'leave_type': 'annual',
        'duration_days': 3,
        'reason': 'family matter',
        'net_salary': 42500,
        'employee_name': 'Rahim Ahmed',
      });

      expect(result, {
        'screen_id': 'E-07',
        'leave_type': 'annual',
        'duration_days': 3,
      });
    });

    test('drops rather than throws, so analytics cannot break a workflow', () {
      expect(
        () => TelemetryGuard.sanitise({'net_salary': 42500}),
        returnsNormally,
      );
      expect(TelemetryGuard.sanitise({'net_salary': 42500}), isEmpty);
    });

    test('a realistic check-in event survives sanitisation intact', () {
      final result = TelemetryGuard.sanitise({
        'screen_id': 'E-03',
        'attendance_mode': 'office_geofence',
        'location_verified': true,
        'is_offline': false,
      });
      expect(result.length, 4);
    });
  });

  group('event taxonomy', () {
    test('event names are unique and snake_case', () {
      final names = AnalyticsEvent.values.map((e) => e.wireName).toList();
      expect(names.toSet().length, names.length);
      for (final name in names) {
        expect(name, matches(RegExp(r'^[a-z]+(_[a-z]+)*$')), reason: name);
      }
    });

    test('the AI adoption metrics in UI-UX §60 are trackable', () {
      final names = AnalyticsEvent.values.map((e) => e.wireName).toSet();
      expect(names, contains('ai_query_sent'));
      expect(names, contains('ai_recommendation_accepted'));
      expect(names, contains('ai_explainability_opened'));
    });
  });

  group('sinks', () {
    test('the no-op sink accepts anything without throwing', () {
      const telemetry = NoopTelemetry();
      expect(
        () => telemetry.track(
          AnalyticsEvent.payslipViewed,
          parameters: {'net_salary': 42500},
        ),
        returnsNormally,
      );
      expect(() => telemetry.trackScreen('E-11'), returnsNormally);
      expect(
        () => telemetry.recordError(StateError('x'), StackTrace.empty),
        returnsNormally,
      );
    });
  });
}
