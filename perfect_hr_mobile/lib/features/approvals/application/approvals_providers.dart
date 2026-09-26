import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/data/data_providers.dart';
import '../../../core/errors/app_failure.dart';
import '../../../core/networking/api_client.dart';
import '../../../core/security/device_key_service.dart';
import '../../../core/security/passkey_service.dart';
import '../../../core/security/second_factor.dart';
import '../../authentication/application/auth_providers.dart';
import '../data/approvals_repository.dart';
import '../domain/override_approval.dart';

final approvalsRepositoryProvider = Provider<ApprovalsRepository>((ref) {
  if (ref.watch(dataSourceModeProvider) == DataSourceMode.mock) {
    return MockApprovalsRepository();
  }
  return ApiApprovalsRepository(client: ref.watch(apiClientProvider));
});

/// Overrides waiting on this person right now.
final approvalQueueProvider =
    AsyncNotifierProvider<ApprovalQueueNotifier, ApprovalQueue>(
  ApprovalQueueNotifier.new,
);

class ApprovalQueueNotifier extends AsyncNotifier<ApprovalQueue> {
  @override
  Future<ApprovalQueue> build() {
    return ref.watch(approvalsRepositoryProvider).loadQueue();
  }

  Future<void> refresh() async {
    final repository = ref.read(approvalsRepositoryProvider);
    state = const AsyncValue<ApprovalQueue>.loading().copyWithPrevious(state);
    state = await AsyncValue.guard(repository.loadQueue);
  }
}

/// Whether to offer approvals at all.
///
/// False when the override module is not installed, so the entry is hidden
/// rather than opening a queue that can never fill. An *empty* queue is
/// different and still shows: "nothing is waiting on you" is useful to know.
final approvalsAvailableProvider = Provider<bool>((ref) {
  return ref.watch(approvalQueueProvider).valueOrNull?.available ?? false;
});

final pendingApprovalCountProvider = Provider<int>((ref) {
  return ref.watch(approvalQueueProvider).valueOrNull?.requests.length ?? 0;
});

/// Decides one override: confirm on a device, then approve. Or reject.
final approvalActionProvider =
    AsyncNotifierProvider<ApprovalActionController, void>(
  ApprovalActionController.new,
);

class ApprovalActionController extends AsyncNotifier<void> {
  @override
  Future<void> build() async {}

  /// Approve, gated on a device confirmation bound to this one override.
  ///
  /// The challenge comes from the server and is answered and posted back inside
  /// the same flow, because the proof is consumed by the request that records
  /// the decision. A confirmation given for one override cannot approve
  /// another — that binding is the difference between a signature and a bearer
  /// token.
  Future<bool> approve(OverrideApproval approval) async {
    state = const AsyncValue.loading();

    try {
      final repository = ref.read(approvalsRepositoryProvider);
      // Fetched before any prompt is raised, because it is the server that
      // decides which proof this account can give. Raising a prompt first would
      // mean guessing, and guessing wrong here asks an approver for a device
      // they do not have while an override waits.
      final challenge = await repository.challengeFor(approval.id);

      if (challenge.method == SecondFactorMethod.device) {
        return await _approveWithPairedKey(repository, approval, challenge);
      }

      final passkeys = ref.read(passkeyServiceProvider);
      if (!await passkeys.isAvailable) {
        state = AsyncValue.error(
          const ServerFailure(
            userMessage: 'This phone cannot confirm an approval. '
                'Approve from a browser instead.',
            isRetryable: false,
          ),
          StackTrace.current,
        );
        return false;
      }

      final assertion = await passkeys.get(challenge.options);
      await repository.approve(requestId: approval.id, assertion: assertion);

      state = const AsyncValue.data(null);
      await ref.read(approvalQueueProvider.notifier).refresh();
      return true;
    } on PasskeyFailure catch (failure) {
      // Cancelling is a decision, not a failure — and on an approval screen
      // that matters more than anywhere else: somebody who thought better of it
      // should not be told something went wrong.
      state = failure.isCancellation
          ? const AsyncValue.data(null)
          : AsyncValue.error(
              ServerFailure(
                userMessage: failure.kind == PasskeyFailureKind.noCredential
                    ? 'This phone has no Perfect HR security device. '
                        'Register one from Security & devices first.'
                    : failure.message,
              ),
              StackTrace.current,
            );
      return false;
    } catch (error, stack) {
      // The server's own refusals are the useful ones here: not your tier yet,
      // not a reviewer, already decided.
      state = AsyncValue.error(error, stack);
      return false;
    }
  }

  /// Sign the override's challenge with this installation's paired key.
  ///
  /// The reason string names the override, because a biometric prompt that
  /// simply says "confirm" is one people answer without reading — and this one
  /// is the last thing standing between a request and a frozen record changing.
  Future<bool> _approveWithPairedKey(
    ApprovalsRepository repository,
    OverrideApproval approval,
    ApprovalChallenge challenge,
  ) async {
    try {
      final signature = await ref.read(deviceKeyServiceProvider).sign(
            challenge: challenge.challengeValue,
            contextRef: challenge.contextRef,
            reason: 'Approve ${approval.reference}',
          );
      await repository.approve(
        requestId: approval.id,
        signaturePayload: signature.toJson(),
      );
      state = const AsyncValue.data(null);
      await ref.read(approvalQueueProvider.notifier).refresh();
      return true;
    } on DeviceKeyFailure catch (failure) {
      // Cancelling is a decision. On an approval screen that matters more than
      // anywhere else: somebody who thought better of it must not be told
      // something went wrong.
      state = failure.kind == DeviceKeyFailureKind.cancelled
          ? const AsyncValue.data(null)
          : AsyncValue.error(
              ServerFailure(
                userMessage: failure.kind == DeviceKeyFailureKind.notPaired
                    ? 'This device is not paired to your account. Pair it from '
                        'Security & devices, then approve again.'
                    : failure.message,
                isRetryable: failure.kind == DeviceKeyFailureKind.failed ||
                    failure.kind == DeviceKeyFailureKind.lockedOut,
              ),
              StackTrace.current,
            );
      return false;
    } catch (error, stack) {
      state = AsyncValue.error(error, stack);
      return false;
    }
  }

  /// Reject. No device confirmation, deliberately — see the repository.
  Future<bool> reject(OverrideApproval approval) async {
    state = const AsyncValue.loading();
    try {
      await ref.read(approvalsRepositoryProvider).reject(approval.id);
      state = const AsyncValue.data(null);
      await ref.read(approvalQueueProvider.notifier).refresh();
      return true;
    } catch (error, stack) {
      state = AsyncValue.error(error, stack);
      return false;
    }
  }
}
