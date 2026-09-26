import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/errors/app_failure.dart';
import '../../../core/security/passkey_service.dart';
import '../../authentication/application/auth_providers.dart';
import 'authenticator_providers.dart';

/// Where an enrolment got to, for the screen to render.
enum EnrolmentStage {
  idle,

  /// Raising the prompt for the device the user already has. Only happens when
  /// they have one — see [EnrolmentController.enrol].
  confirmingExisting,

  /// Raising the prompt that creates the new credential.
  creating,

  /// Posting the result back.
  registering,
}

/// Registers this phone as a security device, without leaving the app.
///
/// Two prompts, in order, when the user already holds a device: confirm on the
/// old one, then create on the new one. Both responses are posted in a **single
/// request**, because the proof of the first device is consumed by the request
/// that stores the second. Splitting them across two calls is precisely the bug
/// that made adding a second device impossible for months — the marker lives on
/// the request object, so it is gone before the next call arrives.
///
/// A first enrolment skips the first prompt: there is nothing yet to prove
/// control of.
class EnrolmentController extends AsyncNotifier<EnrolmentStage> {
  @override
  Future<EnrolmentStage> build() async => EnrolmentStage.idle;

  /// Returns true when a device was registered.
  ///
  /// A cancellation returns false with no error on screen: dismissing the
  /// prompt is a decision, and apologising for it would be the app treating the
  /// user's choice as a fault.
  Future<bool> enrol({required String deviceLabel}) async {
    final passkeys = ref.read(passkeyServiceProvider);
    final repository = ref.read(authenticatorRepositoryProvider);

    if (!await passkeys.isAvailable) {
      state = AsyncValue.error(
        const ServerFailure(
          userMessage: 'This phone cannot register a security device. '
              'Use the browser instead, from Security & devices.',
          isRetryable: false,
        ),
        StackTrace.current,
      );
      return false;
    }

    try {
      state = const AsyncValue.data(EnrolmentStage.confirmingExisting);
      final challenge = await repository.stepUpChallenge();

      Map<String, dynamic>? assertion;
      if (challenge != null) {
        assertion = await passkeys.get(challenge);
      }

      state = const AsyncValue.data(EnrolmentStage.creating);
      final options = await repository.enrolmentOptions();
      final credential = await passkeys.create(options);

      state = const AsyncValue.data(EnrolmentStage.registering);
      await repository.completeEnrolment(
        credential: credential,
        deviceLabel: deviceLabel,
        assertion: assertion,
      );

      // Both the status screen and the sign-in gate read this, so it has to be
      // re-read before either is shown again — otherwise somebody who has just
      // enrolled is still told they have not.
      ref.invalidate(authenticatorStatusProvider);
      state = const AsyncValue.data(EnrolmentStage.idle);
      return true;
    } on PasskeyFailure catch (failure) {
      state = failure.isCancellation
          ? const AsyncValue.data(EnrolmentStage.idle)
          : AsyncValue.error(_failureFor(failure), StackTrace.current);
      return false;
    } catch (error, stack) {
      // ApiClient guarantees an AppFailure, so the server's own wording reaches
      // the user — including the enrolment-route refusals, which explain
      // exactly why an enrolment was not permitted.
      state = AsyncValue.error(error, stack);
      return false;
    }
  }

  static AppFailure _failureFor(PasskeyFailure failure) {
    return switch (failure.kind) {
      // The server excluded the device that already holds a credential, which
      // is the whole point: one device must not satisfy a two-device rule on
      // its own. Needs to say what to do, not what went wrong.
      PasskeyFailureKind.alreadyRegistered => const ServerFailure(
          userMessage: 'This phone already has a Perfect HR security device. '
              'Add a different phone, or a security key, from a browser.',
          isRetryable: false,
        ),
      PasskeyFailureKind.unsupported => const ServerFailure(
          userMessage: 'This phone cannot register a security device. '
              'Use the browser instead, from Security & devices.',
          isRetryable: false,
        ),
      _ => ServerFailure(userMessage: failure.message),
    };
  }
}

final enrolmentControllerProvider =
    AsyncNotifierProvider<EnrolmentController, EnrolmentStage>(
  EnrolmentController.new,
);
