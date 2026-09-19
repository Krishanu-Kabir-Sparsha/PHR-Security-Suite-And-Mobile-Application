/// Domain failure model.
///
/// Instructions §24 — raw technical errors must never reach the user.
/// Every failure carries a [userMessage] safe for display and a [technical]
/// detail intended only for logs and crash reporting.
///
/// Each variant maps to exactly one of the six global UX states defined in
/// Screen & Wireframe Blueprint §52, via [uxState].
sealed class AppFailure implements Exception {
  const AppFailure({
    required this.userMessage,
    this.technical,
    this.isRetryable = true,
  });

  /// Human-readable, non-technical, safe to render.
  final String userMessage;

  /// Diagnostic detail for logs/Crashlytics only. Never rendered.
  final String? technical;

  /// Whether offering a "Try Again" action makes sense.
  final bool isRetryable;

  /// Which global UX state should render for this failure.
  FailureUxState get uxState;

  @override
  String toString() => '$runtimeType(${technical ?? userMessage})';
}

/// Which of the six global UX states a failure resolves to.
enum FailureUxState { error, offline, permissionDenied, empty }

/// Device or network connectivity unavailable.
class OfflineFailure extends AppFailure {
  const OfflineFailure({
    super.userMessage =
        "You're offline. Showing your last synchronized data.",
    super.technical,
  });

  @override
  FailureUxState get uxState => FailureUxState.offline;
}

/// The action requires live connectivity and cannot use cached data.
/// UI-UX §48 — e.g. attendance check-in must be server-validated.
class ConnectionRequiredFailure extends AppFailure {
  const ConnectionRequiredFailure({
    super.userMessage = 'Connection required to complete this action.',
    super.technical,
  });

  @override
  FailureUxState get uxState => FailureUxState.offline;
}

/// Request reached the server but timed out or the network dropped.
class NetworkFailure extends AppFailure {
  const NetworkFailure({
    super.userMessage =
        "We couldn't reach Perfect HR just now. Please try again.",
    super.technical,
  });

  @override
  FailureUxState get uxState => FailureUxState.error;
}

/// Server-side error. Deliberately opaque to the user.
class ServerFailure extends AppFailure {
  // isRetryable is exposed and defaults to true: a 500 or 503 is usually worth
  // another attempt. It has to be *expressible*, though, because not every
  // ServerFailure is transient — a bad TLS certificate maps here and must not
  // offer a retry, since retrying through a possibly-intercepted network is not
  // a remedy. Before this parameter existed the certificate case documented
  // that intent in a comment and the test asserted it, but the type could not
  // represent it, so every certificate failure rendered a Try Again button.
  const ServerFailure({
    super.userMessage = "Something went wrong on our side. Please try again.",
    super.technical,
    super.isRetryable,
  });

  @override
  FailureUxState get uxState => FailureUxState.error;
}

/// Authorisation denied by the backend.
///
/// Instructions §15 — authorisation is enforced server-side; the client only
/// renders the outcome. Never retryable.
class PermissionFailure extends AppFailure {
  const PermissionFailure({
    String userMessage = "You don't have permission to view this information.",
    String? technical,
    this.scope,
  }) : super(
          userMessage: userMessage,
          technical: technical,
          isRetryable: false,
        );

  /// Optional permission or data scope that was denied, for logging.
  final String? scope;

  @override
  FailureUxState get uxState => FailureUxState.permissionDenied;
}

/// Session expired or token refresh failed; the user must re-authenticate.
class SessionExpiredFailure extends AppFailure {
  const SessionExpiredFailure({
    String userMessage = 'Your session has expired. Please sign in again.',
    String? technical,
  }) : super(
          userMessage: userMessage,
          technical: technical,
          isRetryable: false,
        );

  @override
  FailureUxState get uxState => FailureUxState.error;
}

/// Requested resource does not exist or is out of the user's data scope.
class NotFoundFailure extends AppFailure {
  const NotFoundFailure({
    String userMessage = "We couldn't find what you were looking for.",
    String? technical,
  }) : super(
          userMessage: userMessage,
          technical: technical,
          isRetryable: false,
        );

  @override
  FailureUxState get uxState => FailureUxState.empty;
}

/// Server rejected the submitted data. [fieldErrors] drives inline form
/// messages rather than a whole-screen error state.
class ValidationFailure extends AppFailure {
  const ValidationFailure({
    String userMessage = 'Please check the highlighted fields and try again.',
    String? technical,
    this.fieldErrors = const {},
  }) : super(
          userMessage: userMessage,
          technical: technical,
          isRetryable: false,
        );

  final Map<String, String> fieldErrors;

  @override
  FailureUxState get uxState => FailureUxState.error;
}

/// Fallback. Anything unmapped must still present a safe message.
class UnknownFailure extends AppFailure {
  const UnknownFailure({
    super.userMessage = 'Something went wrong. Please try again.',
    super.technical,
  });

  @override
  FailureUxState get uxState => FailureUxState.error;
}

/// Normalises an arbitrary thrown object into an [AppFailure].
///
/// The networking layer (Task 2) will add Dio-specific mapping; this base
/// guarantees that no widget ever receives an unmapped error.
AppFailure asAppFailure(Object error, [StackTrace? stackTrace]) {
  if (error is AppFailure) return error;
  return UnknownFailure(technical: '$error');
}
