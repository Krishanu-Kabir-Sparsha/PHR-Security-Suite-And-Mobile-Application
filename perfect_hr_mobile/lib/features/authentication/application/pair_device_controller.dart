import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/errors/app_failure.dart';
import '../../../core/security/device_key_service.dart';
import 'auth_providers.dart';

/// Binds this installation to an account using a code generated in the browser.
///
/// The order of operations is the part that matters. The keypair is generated
/// first but **not stored**; it is only written to the keystore once the server
/// has accepted the public half. The alternative — store, then tell the server —
/// leaves a private key on the device with no counterpart on the server after
/// any failed pairing, and the next sign-in then raises a fingerprint prompt to
/// produce a signature nothing can verify.
final pairDeviceControllerProvider =
    AsyncNotifierProvider<PairDeviceController, void>(PairDeviceController.new);

class PairDeviceController extends AsyncNotifier<void> {
  @override
  Future<void> build() async {}

  /// Returns the account name on success, or null with [state] carrying why.
  Future<String?> pair({
    required String login,
    required String code,
    required String deviceLabel,
  }) async {
    state = const AsyncValue.loading();

    final keys = ref.read(deviceKeyServiceProvider);

    if (!await keys.isSupported) {
      state = AsyncValue.error(
        const ValidationFailure(
          userMessage: 'This device has no fingerprint, face unlock or screen '
              'lock set up. Add one in your device settings, then pair again.',
        ),
        StackTrace.current,
      );
      return null;
    }

    try {
      final publicKey = await keys.generateKeyPair();
      final pairing = await ref.read(authRepositoryProvider).pairDevice(
            login: login.trim(),
            code: code.trim(),
            publicKey: publicKey,
            deviceLabel: deviceLabel.trim(),
            platform: defaultTargetPlatform.name,
          );
      await keys.rememberPairing(
        publicKey: publicKey,
        handle: pairing.deviceHandle,
        login: pairing.userLogin,
        label: pairing.deviceLabel,
      );
      // The sign-in screen reads this to decide whether to offer pairing.
      ref.invalidate(deviceBindingProvider);
      state = const AsyncValue.data(null);
      return pairing.userName.isEmpty ? pairing.userLogin : pairing.userName;
    } on DeviceKeyFailure catch (failure) {
      state = AsyncValue.error(
        ValidationFailure(userMessage: failure.message),
        StackTrace.current,
      );
      return null;
    } catch (error, stack) {
      // ApiClient guarantees an AppFailure, whose user_message is the server's
      // own wording -- and here that wording names the remedy ("generate a
      // fresh one"), so replacing it would throw away the useful part.
      state = AsyncValue.error(error, stack);
      return null;
    }
  }

  /// Forget this installation's pairing, so a new code can be used.
  Future<void> unpair() async {
    await ref.read(deviceKeyServiceProvider).forget();
    ref.invalidate(deviceBindingProvider);
    state = const AsyncValue.data(null);
  }
}
