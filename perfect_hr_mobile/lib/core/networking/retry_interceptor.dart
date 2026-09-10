import 'dart:async';
import 'dart:math';

import 'package:dio/dio.dart';

import 'api_headers.dart';

/// Decides whether a failed request may be replayed.
///
/// Extracted from the interceptor as a pure function so it can be tested
/// directly. Getting this wrong is expensive in an HR system, so the rule is
/// asserted by tests rather than inferred from interceptor behaviour.
class RetryPolicy {
  const RetryPolicy({this.maxAttempts = 3});

  /// Total attempts including the first. 3 means at most two retries.
  final int maxAttempts;

  static const Set<String> idempotentMethods = {'GET', 'HEAD', 'OPTIONS'};

  /// Transient server and gateway conditions, safe to repeat for a read.
  static const Set<int> retryableStatuses = {429, 502, 503, 504};

  bool shouldRetry({
    required String method,
    required DioExceptionType type,
    int? statusCode,
    bool hasIdempotencyKey = false,
    int attempt = 1,
    bool optedOut = false,
  }) {
    if (optedOut) return false;
    if (attempt >= maxAttempts) return false;

    final normalisedMethod = method.toUpperCase();
    final isIdempotentMethod = idempotentMethods.contains(normalisedMethod);

    // A mutation may only be replayed when the backend can collapse duplicates
    // via an idempotency key. Without one, a retried check-in creates a second
    // attendance record, a retried leave submission double-books balance, and
    // a retried approval actions a request twice and pollutes the audit trail.
    if (!isIdempotentMethod && !hasIdempotencyKey) return false;

    return switch (type) {
      DioExceptionType.connectionTimeout ||
      DioExceptionType.sendTimeout ||
      DioExceptionType.receiveTimeout ||
      DioExceptionType.connectionError =>
        true,

      // A response arrived. For a mutation that means the server received the
      // request and may already have applied it before failing to report
      // success, so replaying is unsafe even for a 503.
      DioExceptionType.badResponse => isIdempotentMethod &&
          statusCode != null &&
          retryableStatuses.contains(statusCode),

      // Certificate errors and cancellations are never transient.
      DioExceptionType.badCertificate ||
      DioExceptionType.cancel ||
      DioExceptionType.unknown =>
        false,
    };
  }
}

/// Retries transient transport failures with exponential backoff and jitter.
///
/// Spec: Instructions §21 (retry behaviour), §25 (performance).
///
/// Replay eligibility is decided entirely by [RetryPolicy]; this class handles
/// only the mechanics of delaying and re-issuing.
class RetryInterceptor extends Interceptor {
  RetryInterceptor({
    required Dio client,
    this.policy = const RetryPolicy(),
    this.baseDelay = const Duration(milliseconds: 400),
    Random? random,
  })  : _client = client,
        _random = random ?? Random();

  /// A Dio instance without this interceptor, so replays cannot recurse.
  final Dio _client;

  final RetryPolicy policy;
  final Duration baseDelay;
  final Random _random;

  static const String _attemptExtra = 'perfect_hr_retry_attempt';

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    final options = err.requestOptions;
    final attempt = (options.extra[_attemptExtra] as int?) ?? 1;

    final retry = policy.shouldRetry(
      method: options.method,
      type: err.type,
      statusCode: err.response?.statusCode,
      hasIdempotencyKey: options.headers.containsKey(
        ApiHeaders.idempotencyKey,
      ),
      attempt: attempt,
      optedOut: options.extra[ApiHeaders.skipRetryExtra] == true,
    );

    if (!retry) return handler.next(err);

    await Future<void>.delayed(delayFor(attempt));

    try {
      final next = options..extra[_attemptExtra] = attempt + 1;
      final response = await _client.fetch<dynamic>(next);
      return handler.resolve(response);
    } on DioException catch (retryError) {
      return handler.next(retryError);
    }
  }

  /// Exponential backoff with full jitter, so a fleet of clients recovering
  /// from an outage does not resynchronise into a thundering herd.
  Duration delayFor(int attempt) {
    final ceiling = baseDelay.inMilliseconds * pow(2, attempt - 1);
    return Duration(milliseconds: _random.nextInt(ceiling.toInt() + 1));
  }
}
