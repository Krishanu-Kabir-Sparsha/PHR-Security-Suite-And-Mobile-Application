import 'package:dio/dio.dart';

import '../../../core/networking/api_client.dart';
import '../domain/auth_session.dart';
import '../domain/sign_in_outcome.dart';

/// Sign-in, refresh and sign-out against the Odoo mobile API.
abstract interface class AuthRepository {
  /// Submit a password. Returns either a session or a demand for a device.
  ///
  /// Deliberately not `Future<AuthSession>` any more: a password on its own is
  /// no longer a sign-in, and a return type that pretended otherwise would have
  /// made the second factor something a caller could forget.
  Future<SignInOutcome> signIn({
    required String login,
    required String password,
    String? deviceLabel,
    String? companyId,
    String? authMode,
  });

  /// Move an existing session to another of the user's companies.
  ///
  /// Returns a **new** session. The server issues a fresh token rather than
  /// editing the one presented, because the company is pinned on the token
  /// precisely so it cannot change underneath a request in flight.
  ///
  /// Takes the access token explicitly. This repository talks through the
  /// auth client, which carries no AuthInterceptor by design, so nothing
  /// attaches an Authorization header on its behalf.
  Future<AuthSession> switchCompany({
    required String accessToken,
    required String companyId,
  });

  /// Complete a sign-in by confirming on an enrolled device.
  ///
  /// [assertion] is the platform's WebAuthn response, posted back untouched.
  Future<AuthSession> completeSignIn({
    required String mfaToken,
    required Map<String, dynamic> assertion,
  });

  /// Complete a sign-in with a signature from this installation's paired key.
  Future<AuthSession> completeSignInWithDevice({
    required String mfaToken,
    required Map<String, dynamic> signaturePayload,
  });

  /// Bind this installation to an account using a code from the web.
  ///
  /// Takes no bearer token, and cannot: a new handset has no session until it
  /// is paired. The code is what carries the authority, which is why it lasts
  /// ten minutes, works once, and needs the account's username beside it.
  Future<DevicePairing> pairDevice({
    required String login,
    required String code,
    required String publicKey,
    required String deviceLabel,
    required String platform,
  });

  Future<AuthSession> refresh(String refreshToken);

  Future<void> signOut(String accessToken);
}

/// What the server returned when it accepted a pairing.
class DevicePairing {
  const DevicePairing({
    required this.deviceHandle,
    required this.deviceLabel,
    required this.userLogin,
    required this.userName,
  });

  final String deviceHandle;
  final String deviceLabel;
  final String userLogin;
  final String userName;

  factory DevicePairing.fromJson(Map<String, dynamic> json) => DevicePairing(
        deviceHandle: '${json['device_handle'] ?? ''}',
        deviceLabel: '${json['device_label'] ?? ''}',
        userLogin: '${json['user_login'] ?? ''}',
        userName: '${json['user_name'] ?? ''}',
      );
}

class ApiAuthRepository implements AuthRepository {
  ApiAuthRepository({required ApiClient client}) : _client = client;

  final ApiClient _client;

  /// `POST /auth/login` -> access + refresh token and the user block.
  ///
  /// No idempotency key: a sign-in is naturally idempotent in effect, and
  /// `RetryPolicy` refuses to replay an unkeyed mutation anyway. That is the
  /// behaviour we want — a login that times out should surface, not be
  /// retried into a second session the user never asked for.
  @override
  Future<SignInOutcome> signIn({
    required String login,
    required String password,
    String? deviceLabel,
    String? companyId,
    String? authMode,
  }) async {
    final body = await _client.post<Map<String, dynamic>>(
      '/auth/login',
      data: {
        // Either a work email or an Employee ID. The server resolves which,
        // so the app does not have to guess from the shape of the string --
        // and a badge number that happens to contain an @ would have defeated
        // any guess it made.
        'login': login,
        'password': password,
        if (deviceLabel != null) 'device_label': deviceLabel,
        // Both omitted when the app has nothing to say. The server then uses
        // the user's own default company and the company's preferred method,
        // which is the correct behaviour for a single-company tenant.
        if (companyId != null && companyId.isNotEmpty) 'company_id': companyId,
        if (authMode != null && authMode.isNotEmpty) 'auth_mode': authMode,
      },
    );
    if (body['mfa_required'] == true) {
      return SignInNeedsDevice.fromJson(body);
    }
    return SignInComplete(AuthSession.fromJson(body));
  }

  /// `POST /auth/login/webauthn` -> the token pair, at last.
  @override
  Future<AuthSession> completeSignIn({
    required String mfaToken,
    required Map<String, dynamic> assertion,
  }) async {
    final body = await _client.post<Map<String, dynamic>>(
      '/auth/login/webauthn',
      data: {'mfa_token': mfaToken, 'assertion': assertion},
    );
    return AuthSession.fromJson(body);
  }

  /// `POST /auth/login/device` -> the token pair.
  @override
  Future<AuthSession> completeSignInWithDevice({
    required String mfaToken,
    required Map<String, dynamic> signaturePayload,
  }) async {
    final body = await _client.post<Map<String, dynamic>>(
      '/auth/login/device',
      data: {'mfa_token': mfaToken, 'signature_payload': signaturePayload},
    );
    return AuthSession.fromJson(body);
  }

  /// `POST /device/pair` -> the device handle this installation now holds.
  @override
  Future<DevicePairing> pairDevice({
    required String login,
    required String code,
    required String publicKey,
    required String deviceLabel,
    required String platform,
  }) async {
    final body = await _client.post<Map<String, dynamic>>(
      '/device/pair',
      data: {
        'login': login,
        'code': code,
        'public_key': publicKey,
        'device_label': deviceLabel,
        'platform': platform,
      },
    );
    return DevicePairing.fromJson(body);
  }

  /// `POST /auth/company` -> a new session in the chosen company.
  @override
  Future<AuthSession> switchCompany({
    required String accessToken,
    required String companyId,
  }) async {
    final body = await _client.post<Map<String, dynamic>>(
      '/auth/company',
      data: {'company_id': companyId},
      options: _bearer(accessToken),
    );
    return AuthSession.fromJson(body);
  }

  /// An Authorization header for the endpoints that need one.
  ///
  /// Written by hand because this repository uses the auth client, which has
  /// no AuthInterceptor: routing refresh through the interceptor that reacts
  /// to a 401 by refreshing would recurse. The cost is that the two
  /// authenticated calls here have to carry their own header, and forgetting
  /// to is silent -- the request simply goes out anonymous and is refused.
  Options _bearer(String accessToken) =>
      Options(headers: {'Authorization': 'Bearer $accessToken'});

  @override
  Future<AuthSession> refresh(String refreshToken) async {
    final body = await _client.post<Map<String, dynamic>>(
      '/auth/refresh',
      data: {'refresh_token': refreshToken},
    );
    return AuthSession.fromJson(body);
  }

  /// Best effort. The local session is cleared by the caller regardless.
  ///
  /// If the network is down, insisting on a successful server call before
  /// letting someone sign out would leave their session on screen on a device
  /// they may be handing to somebody else.
  ///
  /// The header is attached explicitly, and until 18.0.1.12.0 it was not:
  /// `accessToken` was accepted and then never used, so /auth/logout was
  /// called anonymously, answered 401, and the caller swallowed it as the
  /// "best effort" this comment describes. Sign-out therefore never revoked
  /// anything -- a handed-over phone kept a working access token for an hour
  /// and a refresh token for thirty days, and the only visible symptom was
  /// its absence.
  @override
  Future<void> signOut(String accessToken) async {
    await _client.post<Map<String, dynamic>>(
      '/auth/logout',
      options: _bearer(accessToken),
    );
  }
}
