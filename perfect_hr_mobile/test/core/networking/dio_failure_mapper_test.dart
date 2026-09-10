import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/errors/app_failure.dart';
import 'package:perfect_hr_mobile/core/networking/dio_failure_mapper.dart';

/// Covers Instructions §24 (no raw technical errors reach the user), §15
/// (server-side authorisation) and Blueprint §52 (six UX states).
///
/// The leakage tests matter most. A wrong status-to-failure mapping produces a
/// slightly unhelpful message; a leaked stack trace or internal hostname is a
/// data exposure, and it would appear only in the exact error condition nobody
/// exercises manually.

DioException _response(
  int status, {
  Object? body,
  String method = 'GET',
  String path = '/me/dashboard',
}) {
  final options = RequestOptions(path: path, method: method);
  return DioException(
    requestOptions: options,
    type: DioExceptionType.badResponse,
    response: Response<dynamic>(
      requestOptions: options,
      statusCode: status,
      data: body,
    ),
  );
}

DioException _transport(
  DioExceptionType type, {
  String method = 'GET',
  String? message,
}) {
  return DioException(
    requestOptions: RequestOptions(path: '/me/dashboard', method: method),
    type: type,
    message: message,
  );
}

void main() {
  const mapper = DioFailureMapper();
  const offlineMapper = DioFailureMapper(isOffline: _alwaysOffline);

  group('status code mapping', () {
    test('400 → ValidationFailure', () {
      expect(mapper.map(_response(400)), isA<ValidationFailure>());
    });

    test('401 → SessionExpiredFailure, not retryable', () {
      final failure = mapper.map(_response(401));
      expect(failure, isA<SessionExpiredFailure>());
      expect(failure.isRetryable, isFalse);
    });

    test('403 → PermissionFailure, not retryable, permission UX state', () {
      final failure = mapper.map(_response(403));
      expect(failure, isA<PermissionFailure>());
      expect(failure.isRetryable, isFalse);
      expect(failure.uxState, FailureUxState.permissionDenied);
    });

    test('404 → NotFoundFailure, empty UX state', () {
      final failure = mapper.map(_response(404));
      expect(failure, isA<NotFoundFailure>());
      expect(failure.uxState, FailureUxState.empty);
    });

    test('409 → ValidationFailure with refresh guidance', () {
      final failure = mapper.map(_response(409));
      expect(failure, isA<ValidationFailure>());
      expect(failure.userMessage, contains('already been updated'));
    });

    test('422 → ValidationFailure', () {
      expect(mapper.map(_response(422)), isA<ValidationFailure>());
    });

    test('429 → NetworkFailure advising a pause', () {
      final failure = mapper.map(_response(429));
      expect(failure, isA<NetworkFailure>());
      expect(failure.userMessage, contains('Too many requests'));
    });

    test('500 → ServerFailure', () {
      expect(mapper.map(_response(500)), isA<ServerFailure>());
    });

    test('503 → ServerFailure noting temporary unavailability', () {
      final failure = mapper.map(_response(503));
      expect(failure, isA<ServerFailure>());
      expect(failure.userMessage, contains('temporarily unavailable'));
    });

    test('an unexpected status maps to UnknownFailure, not a guess', () {
      expect(mapper.map(_response(418)), isA<UnknownFailure>());
      expect(mapper.map(_response(301)), isA<UnknownFailure>());
    });
  });

  group('transport error mapping', () {
    test('timeouts → NetworkFailure', () {
      for (final type in [
        DioExceptionType.connectionTimeout,
        DioExceptionType.sendTimeout,
        DioExceptionType.receiveTimeout,
      ]) {
        expect(mapper.map(_transport(type)), isA<NetworkFailure>(),
            reason: type.name);
      }
    });

    test('connection error while online → NetworkFailure', () {
      final failure = mapper.map(_transport(DioExceptionType.connectionError));
      expect(failure, isA<NetworkFailure>());
    });

    test('connection error while offline → OfflineFailure', () {
      final failure =
          offlineMapper.map(_transport(DioExceptionType.connectionError));
      expect(failure, isA<OfflineFailure>());
      expect(failure.uxState, FailureUxState.offline);
    });

    test('certificate failure is not retryable', () {
      final failure = mapper.map(_transport(DioExceptionType.badCertificate));
      expect(failure.isRetryable, isFalse);
      expect(failure.userMessage, contains('secure connection'));
    });

    test('cancellation is detectable so callers can ignore it', () {
      final cancelled = _transport(DioExceptionType.cancel);
      expect(DioFailureMapper.isCancellation(cancelled), isTrue);
      expect(DioFailureMapper.isCancellation(_response(500)), isFalse);
    });

    test('an AppFailure passes through untouched', () {
      const original = PermissionFailure(scope: 'payroll.org.read');
      expect(mapper.map(original), same(original));
    });

    test('a non-Dio error is still wrapped safely', () {
      final failure = mapper.map(StateError('token decode failed'));
      expect(failure, isA<UnknownFailure>());
      expect(failure.userMessage, isNot(contains('token')));
    });
  });

  group('no technical leakage into user-facing strings', () {
    test('user messages never contain a status code', () {
      for (final status in [400, 401, 403, 404, 409, 422, 429, 500, 503, 418]) {
        final message = mapper.map(_response(status)).userMessage;
        expect(message, isNot(contains('$status')), reason: 'status $status');
        expect(message, isNot(contains('HTTP')), reason: 'status $status');
      }
    });

    test('user messages never contain the request path', () {
      final failure = mapper.map(
        _response(500, path: '/internal/odoo/hr.employee/read'),
      );
      expect(failure.userMessage, isNot(contains('odoo')));
      expect(failure.userMessage, isNot(contains('/internal')));
    });

    test('a server stack trace in the safe field is rejected', () {
      final failure = mapper.map(
        _response(500, body: {
          'user_message': 'Traceback (most recent call last):\n  File "x.py"',
        }),
      );
      expect(failure.userMessage, isNot(contains('Traceback')));
      expect(failure.userMessage, isNot(contains('.py')));
    });

    test('an internal error string in the safe field is rejected', () {
      final failure = mapper.map(
        _response(403, body: {
          'user_message': 'psycopg2.errors.InsufficientPrivilege on hr_payslip',
        }),
      );
      expect(failure.userMessage, isNot(contains('psycopg2')));
      expect(failure.userMessage, isNot(contains('hr_payslip')));
      expect(
        failure.userMessage,
        "You don't have permission to view this information.",
      );
    });

    test('an over-long safe field is rejected as probable free text', () {
      final failure = mapper.map(
        _response(400, body: {'user_message': 'x' * 400}),
      );
      expect(failure.userMessage, isNot(contains('xxxx')));
    });

    test('technical detail is retained for logs but excludes the body', () {
      final failure = mapper.map(
        _response(
          500,
          method: 'POST',
          path: '/leave/requests',
          body: {'employee_id': 'EMP-001', 'net_salary': 42500},
        ),
      );
      expect(failure.technical, contains('POST /leave/requests'));
      expect(failure.technical, contains('status=500'));
      // The payload must not be copied into diagnostics.
      expect(failure.technical, isNot(contains('EMP-001')));
      expect(failure.technical, isNot(contains('42500')));
    });
  });

  group('server-supplied safe message', () {
    test('a well-formed user_message is used', () {
      final failure = mapper.map(
        _response(409, body: {
          'user_message': 'You have already checked in today.',
        }),
      );
      expect(failure.userMessage, 'You have already checked in today.');
    });

    test('field errors are extracted for inline form display', () {
      final failure = mapper.map(
        _response(422, body: {
          'user_message': 'Please check the highlighted fields.',
          'errors': {
            'from_date': 'Must not be in the past.',
            'leave_type': ['Not available for your grade.'],
          },
        }),
      ) as ValidationFailure;

      expect(failure.fieldErrors['from_date'], 'Must not be in the past.');
      expect(
        failure.fieldErrors['leave_type'],
        'Not available for your grade.',
      );
    });

    test('a malformed error body degrades to defaults without throwing', () {
      expect(
        () => mapper.map(_response(422, body: 'not json at all')),
        returnsNormally,
      );
      final failure = mapper.map(_response(422, body: <String>['a', 'b']));
      expect(failure, isA<ValidationFailure>());
      expect((failure as ValidationFailure).fieldErrors, isEmpty);
    });
  });
}

bool _alwaysOffline() => true;
