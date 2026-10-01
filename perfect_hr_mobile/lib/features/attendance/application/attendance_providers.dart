import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/data/cache_policy.dart';
import '../../../core/data/data_providers.dart';
import '../../../core/errors/app_failure.dart';
import '../../../core/networking/api_client.dart';
import '../../../core/networking/connectivity_service.dart';
import '../../dashboard/application/employee_home_providers.dart';
import '../data/attendance_repository.dart';
import '../domain/attendance_overview.dart';
import '../domain/offsite_request.dart';
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

  /// Where the handset was when the last punch was refused.
  ///
  /// Held so that an approval request carries the position the employee was
  /// standing at when they tried, not wherever they happen to be by the time
  /// they finish typing. A manager judging "was this person at a client site
  /// at 9am?" needs the 9am position, and a phone moves.
  PunchLocation? _refusedAt;

  /// Returns the result on success, or null when it failed — in which case the
  /// error is held in [state] for the screen to render.
  ///
  /// There is no reason parameter any more. A reason used to be resent with
  /// the punch and the punch accepted on the strength of it, which meant the
  /// employee authorised their own exception. Being refused now leads to
  /// [submitOffsiteRequest], which records nothing until a manager agrees.
  Future<AttendanceToggleResult?> toggle() async {
    state = const AsyncValue.loading();
    try {
      // Best effort, always. The phone sends whatever it has; the SERVER
      // decides whether that is enough. Under ENFORCE a missing fix is
      // refused — which is the point, since otherwise declining the location
      // permission would be the way around the rule — but that judgement is
      // not the client's to make, and a client that filtered its own fixes
      // would be a client that could flatter them.
      final where = await ref.read(punchLocationServiceProvider).current();
      _refusedAt = where;

      final result = await ref.read(attendanceRepositoryProvider).toggle(
            latitude: where?.latitude,
            longitude: where?.longitude,
            accuracyMetres: where?.accuracyMetres,
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


  /// Ask a manager to accept the check-in the location rule just refused.
  ///
  /// Returns the request on success, or null — in which case [state] holds the
  /// failure for the screen. Deliberately separate from [toggle]: nothing is
  /// recorded here, and conflating "I punched in" with "I asked to be allowed
  /// to punch in" is how the earlier design ended up letting people wave
  /// themselves through.
  ///
  /// Sends the position captured when the punch was refused rather than a
  /// fresh one, so what the manager judges is where the employee was when
  /// they tried.
  Future<OffsiteRequest?> submitOffsiteRequest(String reason) async {
    state = const AsyncValue.loading();
    try {
      final where = _refusedAt;
      final request = await ref
          .read(attendanceRepositoryProvider)
          .submitOffsiteRequest(
            reason: reason,
            latitude: where?.latitude,
            longitude: where?.longitude,
            accuracyMetres: where?.accuracyMetres,
          );
      state = const AsyncValue.data(null);
      ref.invalidate(offsiteRequestProvider);
      return request;
    } catch (error, stack) {
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

/// The employee's most recent off-site approval request, if any.
///
/// autoDispose so returning to the screen re-reads it: the whole value of this
/// is telling somebody their manager has decided, and a cached "pending" would
/// do the opposite.
final offsiteRequestProvider =
    FutureProvider.autoDispose<OffsiteRequest?>((ref) {
  return ref.watch(attendanceRepositoryProvider).loadOffsiteRequest();
});
