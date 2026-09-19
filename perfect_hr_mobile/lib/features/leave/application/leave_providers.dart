import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/data/cache_policy.dart';
import '../../../core/data/data_providers.dart';
import '../../../core/networking/api_client.dart';
import '../../../core/networking/connectivity_service.dart';
import '../../attendance/application/attendance_providers.dart' show unawaited;
import '../../dashboard/application/employee_home_providers.dart';
import '../data/leave_repository.dart';
import '../domain/leave_models.dart';

final leaveRepositoryProvider = Provider<LeaveRepository>((ref) {
  if (ref.watch(dataSourceModeProvider) == DataSourceMode.mock) {
    return MockLeaveRepository();
  }

  final scope = ref.watch(cacheScopeProvider);
  if (scope == null) {
    throw StateError(
      'leaveRepositoryProvider read without an authenticated session',
    );
  }

  return ApiLeaveRepository(
    client: ref.watch(apiClientProvider),
    cache: ref.watch(cacheStoreProvider),
    scope: scope,
    connectivity: ref.watch(connectivityServiceProvider),
  );
});

final leaveProvider =
    AsyncNotifierProvider<LeaveNotifier, DataSnapshot<LeaveOverview>>(
  LeaveNotifier.new,
);

class LeaveNotifier extends AsyncNotifier<DataSnapshot<LeaveOverview>> {
  @override
  Future<DataSnapshot<LeaveOverview>> build() {
    return ref.watch(leaveRepositoryProvider).loadOverview();
  }

  Future<void> refresh() async {
    final repository = ref.read(leaveRepositoryProvider);
    state = AsyncValue<DataSnapshot<LeaveOverview>>.loading()
        .copyWithPrevious(state);
    state = await AsyncValue.guard(
      () => repository.loadOverview(forceRefresh: true),
    );
  }
}

/// Drives the apply form and the cancel action.
///
/// Separate from [leaveProvider] so a rejected application — "you do not have
/// enough days", which Odoo raises at create time — leaves the balances on
/// screen. Those are exactly what the person needs to see to fix the request.
final leaveActionProvider =
    AsyncNotifierProvider<LeaveActionController, void>(
  LeaveActionController.new,
);

class LeaveActionController extends AsyncNotifier<void> {
  @override
  Future<void> build() async {}

  Future<bool> apply({
    required String typeId,
    required DateTime from,
    required DateTime to,
    String? reason,
  }) async {
    state = const AsyncValue.loading();
    try {
      await ref.read(leaveRepositoryProvider).apply(
            typeId: typeId,
            from: from,
            to: to,
            reason: reason,
          );
      state = const AsyncValue.data(null);
      _refreshDependents();
      return true;
    } catch (error, stack) {
      state = AsyncValue.error(error, stack);
      return false;
    }
  }

  Future<bool> cancel(String requestId) async {
    state = const AsyncValue.loading();
    try {
      await ref.read(leaveRepositoryProvider).cancel(requestId);
      state = const AsyncValue.data(null);
      _refreshDependents();
      return true;
    } catch (error, stack) {
      state = AsyncValue.error(error, stack);
      return false;
    }
  }

  /// Home shows the same balance and the same pending items, so leaving it
  /// alone would let someone apply for leave here and still see the old
  /// balance on the next screen.
  void _refreshDependents() {
    ref.invalidate(leaveProvider);
    unawaited(ref.read(employeeHomeProvider.notifier).invalidateAndReload());
  }
}
