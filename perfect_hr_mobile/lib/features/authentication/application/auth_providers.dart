import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/data/data_providers.dart';
import '../../../core/networking/api_client.dart';
import '../../../core/networking/auth_interceptor.dart';
import '../../../core/session/session_controller.dart';
import '../data/auth_repository.dart';
import '../data/secure_token_store.dart';
import '../../../core/errors/app_failure.dart';
import '../../../core/security/device_key_service.dart';
import '../../../core/security/passkey_service.dart';
import '../domain/auth_session.dart';
import '../domain/sign_in_outcome.dart';

/// Uses [authApiClientProvider], never [apiClientProvider].
///
/// The auth endpoints must not go through the AuthInterceptor: refresh would
/// recurse through the very interceptor that triggers it, and the provider
/// graph would close a cycle that Riverpod throws on during the first frame.
/// The platform's passkey bridge.
///
/// A provider rather than a constructor call so tests can substitute one
/// without a live MethodChannel, which no widget test can answer.
final passkeyServiceProvider = Provider<PasskeyService>((ref) {
  return const PasskeyService();
});

/// This installation's own paired key, and the prompt that releases it.
///
/// A provider for the same reason as the one above: no widget test can answer
/// a real biometric prompt, so tests substitute a fake here.
final deviceKeyServiceProvider = Provider<DeviceKeyService>((ref) {
  return LocalAuthDeviceKeyService();
});

/// Whether this installation is paired, and to whom.
///
/// Read by the sign-in screen so it can offer "Pair this device" to a handset
/// that has never been paired, rather than waiting for a sign-in to fail.
final deviceBindingProvider = FutureProvider<DeviceBinding?>((ref) {
  return ref.watch(deviceKeyServiceProvider).binding;
});

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
        ref.read(sessionControllerProvider.notifier).establish(
              session.user,
              enrolmentRequired: session.enrolmentRequired,
              authMode: session.authMode,
            ),
    onSessionLost: () => ref
        .read(sessionControllerProvider.notifier)
        .signOut(reason: 'Your session expired. Please sign in again.'),
  );
});

/// What the most recent sign-in did to today's attendance.
///
/// Null before the first sign-in of a run, and cleared on sign-out. Held in
/// memory only, on purpose: it is a fact about one moment, and persisting it
/// would have the home screen announce a check-in that happened yesterday.
final lastSignInAttendanceProvider =
    StateProvider<SignInAttendance?>((ref) => null);

/// Drives the sign-in screen: idle, submitting, or failed.
final signInControllerProvider =
    AsyncNotifierProvider<SignInController, void>(SignInController.new);

class SignInController extends AsyncNotifier<void> {
  @override
  Future<void> build() async {}

  /// Password, then device. Returns true only when fully signed in.
  ///
  /// The two stages are one method on purpose. A caller that could do the first
  /// and forget the second would have turned the second factor into an option,
  /// and the screen would have had to remember which half of a sign-in it was
  /// in.
  Future<bool> signIn({
    required String login,
    required String password,
    String? deviceLabel,
    String? companyId,
    String? authMode,
  }) async {
    state = const AsyncValue.loading();
    try {
      final outcome = await ref.read(authRepositoryProvider).signIn(
            login: login,
            password: password,
            deviceLabel: deviceLabel,
            companyId: companyId,
            authMode: authMode,
          );

      final session = switch (outcome) {
        SignInComplete(:final session) => session,
        SignInNeedsDevice needs
            when needs.method == SecondFactorMethod.device =>
          await _confirmWithPairedKey(needs),
        SignInNeedsDevice needs => await _confirmOnDevice(needs),
      };
      if (session == null) return false;

      await _establish(session);
      return true;
    } catch (error, stack) {
      // Held as an error state rather than rethrown, so the screen can render
      // the failure's own user message. ApiClient guarantees this is an
      // AppFailure, so nothing technical can reach the user from here.
      state = AsyncValue.error(error, stack);
      return false;
    }
  }

  /// Sign the server's challenge with this installation's own key.
  ///
  /// Returns null when the user dismissed the prompt, for the same reason the
  /// passkey path does: declining to confirm is a decision, and an error
  /// message would be the app apologising for something they chose.
  Future<AuthSession?> _confirmWithPairedKey(SignInNeedsDevice challenge) async {
    try {
      final signature = await ref.read(deviceKeyServiceProvider).sign(
            challenge: challenge.challengeValue,
            contextRef: challenge.contextRef,
            reason: 'Confirm it is you to sign in to Perfect HR',
          );
      return await ref.read(authRepositoryProvider).completeSignInWithDevice(
            mfaToken: challenge.mfaToken,
            signaturePayload: signature.toJson(),
          );
    } on DeviceKeyFailure catch (failure) {
      if (failure.kind == DeviceKeyFailureKind.cancelled) {
        state = const AsyncValue.data(null);
        return null;
      }
      state = AsyncValue.error(
        ServerFailure(
          // notPaired here means the account has a paired device somewhere,
          // but this installation is not it -- most often a reinstall, which
          // wipes the key. "Try again" would be advice that can never work, so
          // the message names the remedy instead.
          userMessage: switch (failure.kind) {
            DeviceKeyFailureKind.notPaired =>
              'This device is not paired to your account. Open Perfect HR in '
                  'your browser, go to Mobile App > Pair My Phone, and enter '
                  'the code here.',
            DeviceKeyFailureKind.noScreenLock =>
              'Set up a fingerprint, face unlock or screen lock on this '
                  'device, then sign in again.',
            DeviceKeyFailureKind.unsupported =>
              'This device cannot confirm it is you. Sign in from a phone with '
                  'a screen lock, or use the web.',
            // lockedOut, unavailableOnThisBuild and failed already carry a
            // message written for the user; the build fault deliberately says
            // to report it, because no amount of retrying will help.
            _ => failure.message,
          },
          isRetryable: failure.kind == DeviceKeyFailureKind.failed ||
              failure.kind == DeviceKeyFailureKind.lockedOut,
        ),
        StackTrace.current,
      );
      return null;
    }
  }

  /// Raise the platform's prompt and exchange the assertion for a session.
  ///
  /// Returns null when the user cancelled, which is a decision rather than a
  /// failure: the sign-in simply stops, with no error on screen to apologise
  /// for something they chose.
  Future<AuthSession?> _confirmOnDevice(SignInNeedsDevice challenge) async {
    try {
      final assertion =
          await ref.read(passkeyServiceProvider).get(challenge.challenge);
      return await ref.read(authRepositoryProvider).completeSignIn(
            mfaToken: challenge.mfaToken,
            assertion: assertion,
          );
    } on PasskeyFailure catch (failure) {
      if (failure.isCancellation) {
        state = const AsyncValue.data(null);
        return null;
      }
      // Everything else is worth showing. `noCredential` in particular means
      // the account has a device enrolled elsewhere but not on this phone --
      // which the user can only fix by enrolling here, and needs telling.
      state = AsyncValue.error(
        ServerFailure(
          userMessage: failure.kind == PasskeyFailureKind.noCredential
              ? 'This phone has no Perfect HR security key yet. Enrol it on a '
                  'device you already use, then sign in here.'
              : failure.message,
          isRetryable: failure.kind != PasskeyFailureKind.unsupported,
        ),
        StackTrace.current,
      );
      return null;
    }
  }

  Future<void> _establish(AuthSession session) async {
    await ref.read(secureTokenStoreProvider).write(session);
    // Back to live data. The layout preview may have put this run on mocks, and
    // a real sign-in must not leave a real user looking at fabricated figures.
    ref.read(dataSourceModeProvider.notifier).useLive();
    ref.read(sessionControllerProvider.notifier).establish(
          session.user,
          enrolmentRequired: session.enrolmentRequired,
          authMode: session.authMode,
        );
    // Held so the home screen can say what signing in did to attendance. Not
    // persisted: it describes this morning, and restoring it tomorrow would
    // tell somebody they had just been checked in when they had not.
    ref.read(lastSignInAttendanceProvider.notifier).state = session.attendance;
    state = const AsyncValue.data(null);
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
    ref.read(lastSignInAttendanceProvider.notifier).state = null;
    ref.read(sessionControllerProvider.notifier).signOut();
    // The workspace is deliberately kept. It is not a credential, and making
    // somebody retype their company's address every morning would be a worse
    // app for no gain. "Sign in to a different workspace" is what forgets it.
  }

  /// Move this session to another of the user's companies.
  ///
  /// Returns true when the switch took effect. The server mints a fresh token
  /// pinned to the new company rather than editing the old one, so this is a
  /// session replacement and the router rebuilds on the new company id.
  Future<bool> switchCompany(String companyId) async {
    final store = ref.read(secureTokenStoreProvider);
    final current = await store.read();
    if (current == null) return false;

    state = const AsyncValue.loading();
    try {
      final session = await ref.read(authRepositoryProvider).switchCompany(
            accessToken: current.accessToken,
            companyId: companyId,
          );
      await _establish(session);
      return true;
    } catch (error, stack) {
      state = AsyncValue.error(error, stack);
      return false;
    }
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

  ref.read(sessionControllerProvider.notifier).establish(
        session.user,
        enrolmentRequired: session.enrolmentRequired,
        authMode: session.authMode,
      );
  return session;
});
