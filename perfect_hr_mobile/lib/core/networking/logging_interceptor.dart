import 'dart:developer' as developer;

import 'package:dio/dio.dart';

import 'api_headers.dart';

/// Request logging for development.
///
/// Spec: Instructions §27 (never send sensitive HR data to telemetry
/// unnecessarily), Tech-Stack §21.
///
/// Two protections, because a payroll payload in a log file is a data incident
/// regardless of how it got there:
///
/// 1. **Off outside the dev flavour.** `AppConfig.allowsVerboseLogging` is
///    false everywhere else, and the client simply does not install this
///    interceptor.
/// 2. **Redaction even in dev.** Developer machines get shoulder-surfed,
///    screenshared and screen-recorded. Tokens and known sensitive fields are
///    masked, and bodies are size-capped.
class LoggingInterceptor extends Interceptor {
  const LoggingInterceptor({this.maxBodyChars = 1500});

  final int maxBodyChars;

  /// Header values never printed.
  static const Set<String> _redactedHeaders = {
    'authorization',
    'cookie',
    'set-cookie',
    'x-api-key',
  };

  /// Body keys never printed, matched case-insensitively as substrings so
  /// `net_salary`, `basicSalary` and `salary` are all covered.
  static const Set<String> _sensitiveKeyFragments = {
    'password',
    'token',
    'secret',
    'salary',
    'wage',
    'compensation',
    'bank',
    'account_number',
    'accountnumber',
    'iban',
    'routing',
    'nid',
    'national_id',
    'passport',
    'tin',
    'tax_id',
    'dob',
    'date_of_birth',
    'address',
    'phone',
    'mobile',
    'email',
    'biometric',
    'otp',
    'mfa',
  };

  static const String _mask = '***redacted***';

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    _log(
      '→ ${options.method} ${options.path}',
      headers: options.headers,
      body: options.data,
      correlationId: options.headers[ApiHeaders.correlationId]?.toString(),
    );
    handler.next(options);
  }

  @override
  void onResponse(
    Response<dynamic> response,
    ResponseInterceptorHandler handler,
  ) {
    _log(
      '← ${response.statusCode} ${response.requestOptions.method} '
      '${response.requestOptions.path}',
      body: response.data,
      correlationId: response.requestOptions.headers[ApiHeaders.correlationId]
          ?.toString(),
    );
    handler.next(response);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    _log(
      '✗ ${err.response?.statusCode ?? err.type.name} '
      '${err.requestOptions.method} ${err.requestOptions.path}',
      body: err.response?.data,
      correlationId:
          err.requestOptions.headers[ApiHeaders.correlationId]?.toString(),
    );
    handler.next(err);
  }

  void _log(
    String summary, {
    Map<String, dynamic>? headers,
    Object? body,
    String? correlationId,
  }) {
    final buffer = StringBuffer(summary);
    if (correlationId != null) buffer.write('  [$correlationId]');
    if (headers != null) {
      buffer.write('\n  headers: ${_redactHeaders(headers)}');
    }
    if (body != null) {
      buffer.write('\n  body: ${_truncate(_redactBody(body).toString())}');
    }
    developer.log(buffer.toString(), name: 'PerfectHR.http');
  }

  Map<String, Object?> _redactHeaders(Map<String, dynamic> headers) {
    return {
      for (final entry in headers.entries)
        entry.key: _redactedHeaders.contains(entry.key.toLowerCase())
            ? _mask
            : entry.value,
    };
  }

  /// Recursively masks sensitive values, preserving structure so the shape of
  /// a payload stays debuggable.
  Object? _redactBody(Object? body) {
    if (body is Map) {
      return {
        for (final entry in body.entries)
          entry.key: _isSensitiveKey(entry.key.toString())
              ? _mask
              : _redactBody(entry.value),
      };
    }
    if (body is List) return body.map(_redactBody).toList();
    if (body is FormData) {
      return {
        'fields': {
          for (final field in body.fields)
            field.key: _isSensitiveKey(field.key) ? _mask : field.value,
        },
        'files': body.files.map((f) => f.key).toList(),
      };
    }
    return body;
  }

  bool _isSensitiveKey(String key) {
    final lower = key.toLowerCase();
    return _sensitiveKeyFragments.any(lower.contains);
  }

  String _truncate(String value) {
    if (value.length <= maxBodyChars) return value;
    return '${value.substring(0, maxBodyChars)}… '
        '[${value.length - maxBodyChars} more chars]';
  }
}
