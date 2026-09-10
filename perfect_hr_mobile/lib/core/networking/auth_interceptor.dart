import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_headers.dart';

/// Access to the current bearer token.
///
/// Task 3 implements this over `flutter_secure_storage` + `flutter_appauth`
/// (Keycloak, Authorization Code + PKCE). Declaring the seam now means the
/// networking layer never learns where tokens live, and no other layer can
/// reach for one directly.
abstract interface class AuthTokenStore {
  /// Current access token, or null when unauthenticated.
  Future<String?> readAccessToken();

  /// Exchanges the refresh token for a new access token.
  ///
  /// Returns the new access token, or null when refresh is impossible and the
  /// user must sign in again.
  Future<String?> refreshAccessToken();

  /// Clears all token material. Called on refresh failure and sign-out.
  Future<void> clear();
}

/// Default: unauthenticated. Requests carry no Authorization header, and the
/// backend rejects anything requiring one — which is the correct behaviour
/// before Task 3 lands, rather than a silent bypass.
class UnauthenticatedTokenStore implements AuthTokenStore {
  const UnauthenticatedTokenStore();

  @override
  Future<String?> readAccessToken() async => null;

  @override
  Future<String?> refreshAccessToken() async => null;

  @override
  Future<void> clear() async {}
}

final authTokenStoreProvider = Provider<AuthTokenStore>(
  (ref) => const UnauthenticatedTokenStore(),
);

/// Attaches the bearer token and recovers from a single expiry.
///
/// Spec: Tech-Stack §10, Instructions §15.
///
/// Design notes:
/// - **Refresh is single-flight.** Several requests failing 401 concurrently
///   (a dashboard fanning out on resume, say) must trigger one refresh, not
///   one per request — otherwise Keycloak sees a burst and refresh-token
///   rotation can invalidate the whole set.
/// - **One retry only.** A second 401 after a fresh token means the session is
///   genuinely finished; retrying further would loop.
/// - The interceptor never decides *what* the user may see. It only proves who
///   they are; authorisation stays server-side.
class AuthInterceptor extends Interceptor {
  AuthInterceptor({
    required AuthTokenStore tokenStore,
    required Dio retryClient,
    this.onSessionExpired,
  })  : _tokenStore = tokenStore,
        _retryClient = retryClient;

  final AuthTokenStore _tokenStore;

  /// Used to replay the original request after a successful refresh. Must be a
  /// Dio instance *without* this interceptor, to avoid recursion.
  final Dio _retryClient;

  /// Invoked when refresh fails. Task 3 wires this to sign-out.
  final void Function()? onSessionExpired;

  Future<String?>? _inFlightRefresh;

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    if (options.extra[ApiHeaders.skipAuthExtra] == true) {
      return handler.next(options);
    }

    final token = await _tokenStore.readAccessToken();
    if (token != null) {
      options.headers[ApiHeaders.authorization] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    final isUnauthorised = err.response?.statusCode == 401;
    final alreadyRetried = err.requestOptions.extra[_retriedExtra] == true;
    final skipAuth =
        err.requestOptions.extra[ApiHeaders.skipAuthExtra] == true;

    if (!isUnauthorised || alreadyRetried || skipAuth) {
      return handler.next(err);
    }

    final token = await _refreshOnce();
    if (token == null) {
      onSessionExpired?.call();
      return handler.next(err);
    }

    try {
      final options = err.requestOptions
        ..headers[ApiHeaders.authorization] = 'Bearer $token'
        ..extra[_retriedExtra] = true;

      final response = await _retryClient.fetch<dynamic>(options);
      return handler.resolve(response);
    } on DioException catch (retryError) {
      return handler.next(retryError);
    }
  }

  /// Coalesces concurrent refresh attempts into one.
  Future<String?> _refreshOnce() {
    final existing = _inFlightRefresh;
    if (existing != null) return existing;

    final future = _tokenStore.refreshAccessToken().whenComplete(() {
      _inFlightRefresh = null;
    });
    _inFlightRefresh = future;
    return future;
  }

  static const String _retriedExtra = 'perfect_hr_auth_retried';
}
