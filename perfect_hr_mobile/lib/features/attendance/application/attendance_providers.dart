import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/data/cache_policy.dart';
import '../../../core/data/data_providers.dart';
import '../../../core/errors/app_failure.dart';
import '../../../core/networking/api_client.dart';
import '../../../core/networking/connectivity_service.dart';
import '../../dashboard/application/employee_home_providers.dart';
import '../data/attendance_repository.dart';
import '../domain/attendance_overview.dart';

final attendanceRepositoryProvider = Provider<AttendanceRepository>((ref) {
  if (ref.watch(dataSourceModeProvider) == DataSourceMode.mock) {
    return MockAttendanceRepository();
  }

  final scope = ref.watch(cacheScopeProvider);
  if (scope == null) {
    throw StateError(
      'attendanceRepositoryProvider read without an authenticated session',
    );
  }

  return ApiAttendanceRepository(
    client: ref.watch(apiClientProvider),
    cache: ref.watch(cacheStoreProvider),
    scope: scope,
    connectivity: ref.watch(connectivityServiceProvider),
  );
});

final attendanceProvider = AsyncNotifierProvider<AttendanceNotifier,
    DataSnapshot<AttendanceOverview>>(AttendanceNotifier.new);

class AttendanceNotifier
    extends AsyncNotifier<DataSnapshot<AttendanceOverview>> {
  @override
  Future<DataSnapshot<AttendanceOverview>> build() {
    return ref.watch(attendanceRepositoryProvider).loadOverview();
  }

  Future<void> refresh() async {
    final repository = ref.read(attendanceRepositoryProvider);
    state = AsyncValue<DataSnapshot<AttendanceOverview>>.loading()
        .copyWithPrevious(state);
    state = await AsyncValue.guard(
      () => repository.loadOverview(forceRefresh: true),
    );
  }
}

/// Drives the check-in/check-out button: idle, submitting, or failed.
///
/// Separate from [attendanceProvider] so a failed punch does not blank the
/// screen. Someone who taps Check In on a bad connection must still be able to
/// see whether they were already checked in.
final attendanceToggleProvider =
    AsyncNotifierProvider<AttendanceToggleController, AttendanceToggleResult?>(
  AttendanceToggleController.new,
);

class AttendanceToggleController extends AsyncNotifier<AttendanceToggleResult?> {
  @override
  Future<AttendanceToggleResult?> build() async => null;

  /// Returns the result on success, or null when it failed — in which case the
  /// error is held in [state] for the screen to render.
  Future<AttendanceToggleResult?> toggle() async {
    state = const AsyncValue.loading();
    try {
      final result = await ref.read(attendanceRepositoryProvider).toggle();
      state = AsyncValue.data(result);

      // Both screens are now stale: the attendance screen obviously, and Home
      // because its TODAY card shows the same state. Leaving Home alone would
      // let someone check in here, go Home, and be invited to check in again.
      ref.invalidate(attendanceProvider);
      unawaited(ref.read(employeeHomeProvider.notifier).invalidateAndReload());

      return result;
    } catch (error, stack) {
      // Held rather than rethrown so the screen can render this failure's own
      // user message. ApiClient guarantees an AppFailure, so nothing technical
      // can reach the user from here.
      state = AsyncValue.error(error, stack);
      return null;
    }
  }
}

/// Fire-and-forget without the lint complaining, and without letting a failure
/// in a secondary refresh surface as an unhandled error.
void unawaited(Future<void> future) {
  future.catchError((Object _) {});
}

/// Convenience for the AI/insight strip and tests.
final attendanceFailureProvider = Provider<AppFailure?>((ref) {
  final state = ref.watch(attendanceProvider);
  final error = state.error;
  return error == null ? null : asAppFailure(error, state.stackTrace);
});
