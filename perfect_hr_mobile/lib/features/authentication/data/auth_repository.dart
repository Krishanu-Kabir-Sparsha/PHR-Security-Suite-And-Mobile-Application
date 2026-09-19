import '../../../core/networking/api_client.dart';
import '../domain/auth_session.dart';

/// Sign-in, refresh and sign-out against the Odoo mobile API.
abstract interface class AuthRepository {
  Future<AuthSession> signIn({
    required String login,
    required String password,
    String? deviceLabel,
  });

  Future<AuthSession> refresh(String refreshToken);

  Future<void> signOut(String accessToken);
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
  Future<AuthSession> signIn({
    required String login,
    required String password,
    String? deviceLabel,
  }) async {
    final body = await _client.post<Map<String, dynamic>>(
      '/auth/login',
      data: {
        'login': login,
        'password': password,
        if (deviceLabel != null) 'device_label': deviceLabel,
      },
    );
    return AuthSession.fromJson(body ?? const {});
  }

  @override
  Future<AuthSession> refresh(String refreshToken) async {
    final body = await _client.post<Map<String, dynamic>>(
      '/auth/refresh',
      data: {'refresh_token': refreshToken},
    );
    return AuthSession.fromJson(body ?? const {});
  }

  /// Best effort. The local session is cleared by the caller regardless.
  ///
  /// If the network is down, insisting on a successful server call before
  /// letting someone sign out would leave their session on screen on a device
  /// they may be handing to somebody else. The server-side token expires on
  /// its own, and can be revoked from the web client.
  @override
  Future<void> signOut(String accessToken) async {
    await _client.post<Map<String, dynamic>>('/auth/logout');
  }
}
