import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/networking/retry_interceptor.dart';

/// Covers Instructions §21 (retry behaviour must be defined) and the safety
/// rule that a mutation is never blindly replayed.
///
/// This is the highest-consequence logic in the networking layer. A duplicate
/// GET is invisible; a duplicate check-in, leave submission or approval
/// corrupts attendance records, leave balances and the audit trail — and it
/// only happens on a flaky network, which is exactly the condition manual
/// testing does not reproduce.
void main() {
  const policy = RetryPolicy();

  group('idempotent reads retry on transport failure', () {
    test('GET retries on timeouts and connection errors', () {
      for (final type in [
        DioExceptionType.connectionTimeout,
        DioExceptionType.sendTimeout,
        DioExceptionType.receiveTimeout,
        DioExceptionType.connectionError,
      ]) {
        expect(
          policy.shouldRetry(method: 'GET', type: type),
          isTrue,
          reason: type.name,
        );
      }
    });

    test('GET retries on transient gateway statuses', () {
      for (final status in RetryPolicy.retryableStatuses) {
        expect(
          policy.shouldRetry(
            method: 'GET',
            type: DioExceptionType.badResponse,
            statusCode: status,
          ),
          isTrue,
          reason: 'status $status',
        );
      }
    });

    test('GET does not retry a definitive client error', () {
      for (final status in [400, 401, 403, 404, 409, 422]) {
        expect(
          policy.shouldRetry(
            method: 'GET',
            type: DioExceptionType.badResponse,
            statusCode: status,
          ),
          isFalse,
          reason: 'status $status',
        );
      }
    });

    test('GET does not retry a 500 — it is not transient', () {
      expect(
        policy.shouldRetry(
          method: 'GET',
          type: DioExceptionType.badResponse,
          statusCode: 500,
        ),
        isFalse,
      );
    });
  });

  group('mutations are not replayed without an idempotency key', () {
    test('POST does not retry, even on a pure connection failure', () {
      expect(
        policy.shouldRetry(
          method: 'POST',
          type: DioExceptionType.connectionError,
        ),
        isFalse,
      );
    });

    test('PUT, PATCH and DELETE do not retry', () {
      for (final method in ['PUT', 'PATCH', 'DELETE']) {
        expect(
          policy.shouldRetry(
            method: method,
            type: DioExceptionType.connectionTimeout,
          ),
          isFalse,
          reason: method,
        );
      }
    });

    test('POST with an idempotency key retries on a connection failure', () {
      expect(
        policy.shouldRetry(
          method: 'POST',
          type: DioExceptionType.connectionError,
          hasIdempotencyKey: true,
        ),
        isTrue,
      );
    });

    test(
        'POST with an idempotency key still does not retry once a response '
        'arrived — the server may already have applied it', () {
      expect(
        policy.shouldRetry(
          method: 'POST',
          type: DioExceptionType.badResponse,
          statusCode: 503,
          hasIdempotencyKey: true,
        ),
        isFalse,
      );
    });
  });

  group('never-retryable conditions', () {
    test('certificate failures are not retried', () {
      expect(
        policy.shouldRetry(
          method: 'GET',
          type: DioExceptionType.badCertificate,
        ),
        isFalse,
      );
    });

    test('cancellations are not retried', () {
      expect(
        policy.shouldRetry(method: 'GET', type: DioExceptionType.cancel),
        isFalse,
      );
    });

    test('an explicit opt-out wins over everything', () {
      expect(
        policy.shouldRetry(
          method: 'GET',
          type: DioExceptionType.connectionError,
          optedOut: true,
        ),
        isFalse,
      );
    });
  });

  group('attempt budget', () {
    test('stops at maxAttempts', () {
      expect(
        policy.shouldRetry(
          method: 'GET',
          type: DioExceptionType.connectionError,
          attempt: 2,
        ),
        isTrue,
      );
      expect(
        policy.shouldRetry(
          method: 'GET',
          type: DioExceptionType.connectionError,
          attempt: 3,
        ),
        isFalse,
      );
    });

    test('a single-attempt policy never retries', () {
      const once = RetryPolicy(maxAttempts: 1);
      expect(
        once.shouldRetry(
          method: 'GET',
          type: DioExceptionType.connectionError,
        ),
        isFalse,
      );
    });
  });

  group('backoff', () {
    test('delay ceiling grows exponentially and stays bounded', () {
      final interceptor = RetryInterceptor(
        client: Dio(),
        baseDelay: const Duration(milliseconds: 100),
      );

      // Full jitter means each delay is in [0, ceiling]; assert the bound
      // rather than an exact value.
      for (var attempt = 1; attempt <= 3; attempt++) {
        final ceiling = 100 * (1 << (attempt - 1));
        for (var i = 0; i < 25; i++) {
          final delay = interceptor.delayFor(attempt);
          expect(delay.inMilliseconds, inInclusiveRange(0, ceiling));
        }
      }
    });
  });
}
