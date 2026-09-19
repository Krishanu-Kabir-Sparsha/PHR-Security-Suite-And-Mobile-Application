import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/data/data_providers.dart';
import '../../../core/networking/api_client.dart';
import '../../../core/networking/auth_interceptor.dart';
import '../../../core/session/session_controller.dart';
import '../data/auth_repository.dart';
import '../data/secure_token_store.dart';
import '../domain/auth_session.dart';

/// Uses [authApiClientProvider], never [apiClientProvider].
///
/// The auth endpoints must not go through the AuthInterceptor: refresh would
/// recurse through the very interceptor that triggers it, and the provider
/// graph would close a cycle that Riverpod throws on during the first frame.
final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return ApiAuthRepository(client: ref.watch(authApiClientProvider));
});

/// The real token store, replacing Task 2's `UnauthenticatedTokenStore`.
///
/// Overridden onto [authTokenStoreProvider] in `main.dart`, which is what makes
/// the interceptor start attaching bearer tokens. Until that override exists
/// the app is, correctly, anonymous.
final secureTokenStoreProvider = Provider<SecureTokenStore>((ref) {
  return SecureTokenStore(
    repository: ref.watch(authRepositoryProvider),
    // A refresh that happens inside the interceptor must reach the session
    // too, or the UI would keep rendering the identity from the token it
    // replaced.
    onSessionChanged: (session) =>
        ref.read(sessionControllerProvider.notifier).establish(session.user),
    onSessionLost: () => ref
        .read(sessionControllerProvider.notifier)
        .signOut(reason: 'Your session expired. Please sign in again.'),
  );
});

/// Drives the sign-in screen: idle, submitting, or failed.
final signInControllerProvider =
    AsyncNotifierProvider<SignInController, void>(SignInController.new);

class SignInController extends AsyncNotifier<void> {
  @override
  Future<void> build() async {}

  Future<bool> signIn({
    required String login,
    required String password,
    String? deviceLabel,
  }) async {
    state = const AsyncValue.loading();
    try {
      final session = await ref.read(authRepositoryProvider).signIn(
            login: login,
            password: password,
            deviceLabel: deviceLabel,
          );
      await ref.read(secureTokenStoreProvider).write(session);
      // Back to live data. The dev role switcher may have put this run on
      // mocks, and a real sign-in must not leave a real user looking at
      // fabricated figures.
      ref.read(dataSourceModeProvider.notifier).useLive();
      ref.read(sessionControllerProvider.notifier).establish(session.user);
      state = const AsyncValue.data(null);
      return true;
    } catch (error, stack) {
      // Held as an error state rather than rethrown, so the screen can render
      // the failure's own user message. ApiClient guarantees this is an
      // AppFailure, so nothing technical can reach the user from here.
      state = AsyncValue.error(error, stack);
      return false;
    }
  }

  Future<void> signOut() async {
    final store = ref.read(secureTokenStoreProvider);
    final session = await store.read();
    if (session != null) {
      try {
        await ref.read(authRepositoryProvider).signOut(session.accessToken);
      } catch (_) {
        // Best effort; see ApiAuthRepository.signOut. The local clear below is
        // what actually matters on a device being handed to someone else.
      }
    }
    await store.clear();
    ref.read(sessionControllerProvider.notifier).signOut();
  }
}

/// Restores a stored session at start-up.
///
/// Resolved before the first frame in `main.dart` so a returning user does not
/// see the sign-in screen flash past on every cold start.
final sessionRestoreProvider = FutureProvider<AuthSession?>((ref) async {
  final store = ref.watch(secureTokenStoreProvider);
  final session = await store.read();
  if (session == null) return null;

  // An expired access token is not a reason to sign somebody out: the refresh
  // token usually still has weeks on it. Try to renew, and only give up if
  // that fails.
  if (session.isExpired) {
    final renewed = await store.refreshAccessToken();
    if (renewed == null) return null;
    return store.read();
  }

  ref.read(sessionControllerProvider.notifier).establish(session.user);
  return session;
});
