import 'package:dio/dio.dart';

import '../errors/app_failure.dart';

/// Maps transport-level errors onto the domain failure model.
///
/// Spec: Instructions §24 (never expose raw technical errors), §15 (server-side
/// authorisation), Screen & Wireframe Blueprint §52 (six UX states).
///
/// This is the single boundary at which HTTP becomes domain language. Nothing
/// above this layer should know what a status code is. Two rules hold here:
///
/// 1. **Status codes and transport detail go to [AppFailure.technical] only.**
///    Every user-facing string originates from [AppFailure]'s own defaults or
///    from an explicitly-designated safe server field — never from a raw
///    response body, exception message or URL.
/// 2. **Server messages are distrusted by default.** A backend error body can
///    contain stack traces, SQL, internal hostnames or Odoo model names. Only
///    the [_safeMessageField] key is treated as intended for display, because
///    the API contract designates it as such.
class DioFailureMapper {
  const DioFailureMapper({this.isOffline});

  /// Optional connectivity probe. When it reports offline, connection-class
  /// errors become [OfflineFailure] rather than [NetworkFailure], which is the
  /// difference between "you're offline" and "we couldn't reach Perfect HR".
  final bool Function()? isOffline;

  /// The only response field the client will render verbatim. The application
  /// API must guarantee it is user-safe and localisable.
  static const String _safeMessageField = 'user_message';

  /// Field-level validation errors, e.g. `{"errors": {"from_date": "..."}}`.
  static const String _fieldErrorsField = 'errors';

  /// True when the error is a caller-initiated cancellation.
  ///
  /// Cancellations are not user-facing: a screen disposed mid-request has
  /// nothing to report. Callers using a [CancelToken] must check this before
  /// rendering any failure.
  static bool isCancellation(Object error) =>
      error is DioException && error.type == DioExceptionType.cancel;

  AppFailure map(Object error, [StackTrace? stackTrace]) {
    if (error is AppFailure) return error;
    if (error is! DioException) return asAppFailure(error, stackTrace);

    final technical = _technicalSummary(error);

    return switch (error.type) {
      DioExceptionType.badResponse => _mapResponse(error, technical),

      // transformTimeout is Dio's response-transformer timeout. It is a timeout
      // like the others and reads the same way to a user, so it joins this
      // group. Listed explicitly rather than caught by a wildcard: an
      // unmatched DioExceptionType should keep failing analysis, so a future
      // Dio release cannot quietly fall into a generic bucket.
      DioExceptionType.connectionTimeout ||
      DioExceptionType.sendTimeout ||
      DioExceptionType.receiveTimeout ||
      DioExceptionType.transformTimeout =>
        NetworkFailure(
          userMessage:
              'Perfect HR is taking longer than usual to respond. '
              'Please try again.',
          technical: technical,
        ),

      DioExceptionType.connectionError => (isOffline?.call() ?? false)
          ? OfflineFailure(technical: technical)
          : NetworkFailure(technical: technical),

      // A certificate failure may indicate interception. Do not offer a retry:
      // retrying through a hostile network is not a remedy.
      DioExceptionType.badCertificate => const ServerFailure(
          userMessage: "We couldn't establish a secure connection. "
              'Please try again on a trusted network.',
          isRetryable: false,
        ).withTechnical(technical),

      DioExceptionType.cancel => UnknownFailure(
          userMessage: 'Request cancelled.',
          technical: technical,
        ),

      DioExceptionType.unknown => (isOffline?.call() ?? false)
          ? OfflineFailure(technical: technical)
          : UnknownFailure(technical: technical),
    };
  }

  AppFailure _mapResponse(DioException error, String technical) {
    final response = error.response;
    final status = response?.statusCode ?? 0;
    final safeMessage = _extractSafeMessage(response);

    return switch (status) {
      // Malformed request. Surface field errors where the server supplied them.
      400 => ValidationFailure(
          userMessage: safeMessage ??
              'Please check the information you entered and try again.',
          technical: technical,
          fieldErrors: _extractFieldErrors(response),
        ),

      // Token missing, expired or rejected. Task 3's refresh interceptor gets
      // first attempt; reaching here means re-authentication is required.
      401 => SessionExpiredFailure(technical: technical),

      // Authorisation denied server-side. Never retryable.
      403 => PermissionFailure(
          userMessage: safeMessage ??
              "You don't have permission to view this information.",
          technical: technical,
        ),

      // The safe message matters more here than anywhere else. A 404 from this
      // API is not always "that page does not exist": /me/home returns one when
      // the signed-in user has no hr.employee record linked yet, and says so in
      // user_message along with what to do about it. Dropping that left the
      // user with "We couldn't find what you were looking for", which explains
      // nothing and suggests the app is at fault.
      404 => NotFoundFailure(
          userMessage:
              safeMessage ?? "We couldn't find what you were looking for.",
          technical: technical,
        ),

      // Workflow conflict, e.g. already checked in, or approving a request
      // another approver has already actioned.
      409 => ValidationFailure(
          userMessage: safeMessage ??
              'This has already been updated. Please refresh and try again.',
          technical: technical,
        ),

      422 => ValidationFailure(
          userMessage: safeMessage ??
              'Please check the highlighted fields and try again.',
          technical: technical,
          fieldErrors: _extractFieldErrors(response),
        ),

      // Gateway rate limit (APISIX). Retryable, but not immediately.
      429 => NetworkFailure(
          userMessage: 'Too many requests. Please wait a moment and try again.',
          technical: technical,
        ),

      503 => ServerFailure(
          userMessage:
              'Perfect HR is temporarily unavailable. Please try again shortly.',
          technical: technical,
        ),

      _ => status >= 500
          ? ServerFailure(technical: technical)
          // 3xx and unhandled 4xx: deliberately opaque. Inventing a specific
          // message for an unexpected status risks misinforming the user.
          : UnknownFailure(technical: technical),
    };
  }

  /// Reads the designated safe message, if present and sane.
  ///
  /// Length-capped and newline-stripped: a multi-line or very long value is a
  /// strong signal that a stack trace has been placed in the field by mistake,
  /// and it is safer to fall back to our own copy than to render it.
  String? _extractSafeMessage(Response<dynamic>? response) {
    final data = response?.data;
    if (data is! Map) return null;

    final raw = data[_safeMessageField];
    if (raw is! String) return null;

    final message = raw.trim();
    if (message.isEmpty || message.length > 200) return null;
    if (message.contains('\n')) return null;
    // Reject anything that looks like transport or infrastructure detail.
    if (RegExp(r'(HTTP|Exception|Traceback|odoo\.|psycopg|SQL|at 0x)',
            caseSensitive: false)
        .hasMatch(message)) {
      return null;
    }
    return message;
  }

  Map<String, String> _extractFieldErrors(Response<dynamic>? response) {
    final data = response?.data;
    if (data is! Map) return const {};

    final errors = data[_fieldErrorsField];
    if (errors is! Map) return const {};

    final result = <String, String>{};
    errors.forEach((key, value) {
      if (key is! String) return;
      final message = switch (value) {
        String s => s,
        List l when l.isNotEmpty && l.first is String => l.first as String,
        _ => null,
      };
      if (message == null) return;
      // Same distrust applied per field.
      final trimmed = message.trim();
      if (trimmed.isEmpty || trimmed.length > 200) return;
      result[key] = trimmed;
    });
    return result;
  }

  /// Diagnostic string for logs and Crashlytics.
  ///
  /// Includes method, path and status. Deliberately excludes the request body
  /// and query string, which can carry employee identifiers and other HR data
  /// (Instructions §27).
  String _technicalSummary(DioException error) {
    final method = error.requestOptions.method;
    final path = error.requestOptions.path;
    final status = error.response?.statusCode;
    final type = error.type.name;
    return [
      '$method $path',
      if (status != null) 'status=$status',
      'type=$type',
      if (error.message != null) 'message=${error.message}',
    ].join(' ');
  }
}

extension on ServerFailure {
  /// Attaches diagnostics to a const-declared failure without duplicating copy.
  ///
  /// isRetryable must be carried across. Omitting it silently reset the flag to
  /// its default of true, which is how the certificate case ended up offering a
  /// Try Again despite being constructed with isRetryable: false.
  ServerFailure withTechnical(String technical) => ServerFailure(
        userMessage: userMessage,
        technical: technical,
        isRetryable: isRetryable,
      );
}
