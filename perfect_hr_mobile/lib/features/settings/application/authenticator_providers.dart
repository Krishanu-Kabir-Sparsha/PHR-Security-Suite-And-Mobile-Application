import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/data/data_providers.dart';
import '../../../core/networking/api_client.dart';
import '../data/authenticator_repository.dart';
import '../domain/authenticator_status.dart';

/// Selects the live or mock repository, once, here.
///
/// No cache scope is required, unlike the dashboard providers: this repository
/// does not cache. See the note in `AuthenticatorRepository`.
final authenticatorRepositoryProvider = Provider<AuthenticatorRepository>((ref) {
  if (ref.watch(dataSourceModeProvider) == DataSourceMode.mock) {
    return MockAuthenticatorRepository();
  }
  return ApiAuthenticatorRepository(client: ref.watch(apiClientProvider));
});

/// SET-02 security-key enrolment status.
final authenticatorStatusProvider =
    AsyncNotifierProvider<AuthenticatorNotifier, AuthenticatorStatus>(
  AuthenticatorNotifier.new,
);

class AuthenticatorNotifier extends AsyncNotifier<AuthenticatorStatus> {
  @override
  Future<AuthenticatorStatus> build() {
    return ref.watch(authenticatorRepositoryProvider).loadStatus();
  }

  /// Re-read after the user returns from the browser.
  ///
  /// Deliberately drops to a loading state rather than keeping the old value
  /// visible. Everywhere else in this app a refresh keeps current data on
  /// screen, but here the previous value is precisely what the user is trying
  /// to disprove: they went away to enrol a device, and showing "1 of 2"
  /// underneath a spinner invites them to read the stale number as the answer.
  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(
      () => ref.read(authenticatorRepositoryProvider).loadStatus(),
    );
  }
}
