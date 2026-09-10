/// HTTP header and Dio `extra` keys used by the networking layer.
abstract final class ApiHeaders {
  static const String authorization = 'Authorization';
  static const String accept = 'Accept';
  static const String contentType = 'Content-Type';
  static const String acceptLanguage = 'Accept-Language';

  /// Correlates a mobile request with backend traces and Crashlytics reports.
  static const String correlationId = 'X-Correlation-Id';

  /// Client build identification, for gateway-side diagnostics and for
  /// supporting minimum-version enforcement later.
  static const String clientApp = 'X-Client-App';
  static const String clientVersion = 'X-Client-Version';
  static const String clientPlatform = 'X-Client-Platform';

  /// Makes a non-idempotent request safely retryable. Set per-request by
  /// features that submit (leave, corrections, approvals); without it, the
  /// retry interceptor refuses to replay a mutation.
  static const String idempotencyKey = 'Idempotency-Key';

  // --- Dio `extra` keys (not sent over the wire) ---------------------------

  /// Marks a request that must not carry an Authorization header, e.g. the
  /// token endpoint itself.
  static const String skipAuthExtra = 'perfect_hr_skip_auth';

  /// Opts a request out of automatic retry.
  static const String skipRetryExtra = 'perfect_hr_skip_retry';

  /// DELIBERATELY ABSENT: a tenant header.
  ///
  /// Instructions §16 and Tech-Stack §26 require tenant context to be
  /// established through the identity layer and resolved by the gateway from
  /// verified token claims. A client-supplied tenant header would be an
  /// attacker-controlled value on the tenant-isolation path, so the mobile app
  /// sends none. If a future gateway configuration appears to need one, that is
  /// a backend design question to raise, not a header to add here.
}
