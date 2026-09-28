import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/data/cache_policy.dart';
import '../../../core/data/data_providers.dart';
import '../../../core/errors/app_failure.dart';
import '../../../core/networking/api_client.dart';
import '../../../core/networking/connectivity_service.dart';
import '../../dashboard/application/employee_home_providers.dart';
import '../data/attendance_repository.dart';
import '../domain/attendance_overview.dart';
import '../../../core/security/punch_location_service.dart';

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
  ///
  /// [offSiteReason] is sent only on a second attempt, after the server has
  /// said the punch looks far from the employee's work location and the user
  /// has explained why. Its presence turns a refusal into a flagged
  /// acceptance; see `models/attendance_geofence.py`.
  Future<AttendanceToggleResult?> toggle({String? offSiteReason}) async {
    state = const AsyncValue.loading();
    try {
      // Best effort, always. A location failure must never stop a punch —
      // this returns null for a denied permission, a disabled radio or a
      // timeout, and the server reads an absent fix as "nothing to check".
      final where = await ref.read(punchLocationServiceProvider).current();

      final result = await ref.read(attendanceRepositoryProvider).toggle(
            latitude: where?.latitude,
            longitude: where?.longitude,
            accuracyMetres: where?.accuracyMetres,
            offSiteReason: offSiteReason,
          );
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

  /// Start or end a break, then reload both screens.
  ///
  /// Deliberately not folded into [toggle]. A break is recorded *inside* the
  /// session; a toggle ends it. Sharing one entry point would make "I am
  /// going for lunch" and "I am going home" the same button press.
  Future<AttendanceToggleResult?> toggleBreak({String? breakType}) async {
    state = const AsyncValue.loading();
    try {
      final result = await ref
          .read(attendanceRepositoryProvider)
          .toggleBreak(breakType: breakType);
      state = AsyncValue.data(result);
      ref.invalidate(attendanceProvider);
      unawaited(ref.read(employeeHomeProvider.notifier).invalidateAndReload());
      return result;
    } catch (error, stack) {
      state = AsyncValue.error(error, stack);
      return null;
    }
  }

  /// Close a session left open on an earlier day, then reload both screens.
  ///
  /// Separate from [toggle] rather than folded into it. A toggle on a stale
  /// session would check the person out at *now*, turning a forgotten Thursday
  /// into a 48-hour shift that flows straight into worked hours and overtime.
  /// This asks the server to close it at the end of the day it belongs to.
  Future<bool> resolveStale() async {
    state = const AsyncValue.loading();
    try {
      await ref.read(attendanceRepositoryProvider).resolveStale();
      state = const AsyncValue.data(null);
      ref.invalidate(attendanceProvider);
      unawaited(ref.read(employeeHomeProvider.notifier).invalidateAndReload());
      return true;
    } catch (error, stack) {
      state = AsyncValue.error(error, stack);
      return false;
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
