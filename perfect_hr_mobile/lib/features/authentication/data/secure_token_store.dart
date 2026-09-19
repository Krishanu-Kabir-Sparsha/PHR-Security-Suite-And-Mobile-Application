import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../../core/networking/auth_interceptor.dart';
import '../domain/auth_session.dart';
import 'auth_repository.dart';

/// [AuthTokenStore] backed by the platform keystore.
///
/// Tokens go in Keystore/Keychain, never in the Drift cache or
/// SharedPreferences. The cache database is explicitly unencrypted (risk R9),
/// and it is acceptable only because policy keeps sensitive material out of it;
/// a bearer token is exactly the material that must stay out.
///
/// This is the implementation of the seam Task 2 left behind. The interceptor
/// already handles single-flight refresh, so all that is required here is
/// honest answers to three questions: what is the token, can you get a new one,
/// and forget everything.
class SecureTokenStore implements AuthTokenStore {
  SecureTokenStore({
    required AuthRepository repository,
    FlutterSecureStorage? storage,
    this.onSessionChanged,
    this.onSessionLost,
  })  : _repository = repository,
        _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  static const String _key = 'perfecthr.auth.session';

  final AuthRepository _repository;
  final FlutterSecureStorage _storage;

  /// Notified whenever a new session is written, so the session controller and
  /// the UI follow a refresh that happened inside an interceptor.
  final void Function(AuthSession session)? onSessionChanged;

  /// Notified when refresh fails and the user must sign in again.
  final void Function()? onSessionLost;

  AuthSession? _cached;

  Future<AuthSession?> read() async {
    if (_cached != null) return _cached;
    final raw = await _storage.read(key: _key);
    if (raw == null || raw.isEmpty) return null;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return null;
      return _cached = AuthSession.fromStored(decoded.cast<String, Object?>());
    } catch (_) {
      // A stored blob we cannot parse is treated as no session rather than as
      // an error. The format may have changed across an app update, and the
      // remedy is always the same: sign in again.
      await clear();
      return null;
    }
  }

  Future<void> write(AuthSession session) async {
    _cached = session;
    await _storage.write(key: _key, value: jsonEncode(session.toJson()));
    onSessionChanged?.call(session);
  }

  @override
  Future<String?> readAccessToken() async {
    final session = await read();
    if (session == null) return null;
    // Returned even when expired. The interceptor's job is to notice the 401
    // and call refreshAccessToken; pre-empting it here would mean two places
    // deciding when a token is stale, and they would eventually disagree.
    return session.accessToken;
  }

  @override
  Future<String?> refreshAccessToken() async {
    final session = await read();
    if (session == null || session.refreshToken.isEmpty) return null;
    try {
      final renewed = await _repository.refresh(session.refreshToken);
      await write(renewed);
      return renewed.accessToken;
    } catch (_) {
      // Refresh tokens rotate server-side, so a failure here is terminal:
      // there is no second attempt that could succeed. Clear, and let the app
      // send the user to sign-in rather than looping on 401s.
      await clear();
      onSessionLost?.call();
      return null;
    }
  }

  @override
  Future<void> clear() async {
    _cached = null;
    await _storage.delete(key: _key);
  }
}
