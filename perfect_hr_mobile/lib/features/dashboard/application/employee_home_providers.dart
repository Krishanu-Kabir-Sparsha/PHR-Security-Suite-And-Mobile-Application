import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/data/cache_policy.dart';
import '../../../core/data/data_providers.dart';
import '../../../core/errors/app_failure.dart';
import '../../../core/networking/api_client.dart';
import '../../../core/networking/connectivity_service.dart';
import '../data/employee_home_repository.dart';
import '../domain/employee_home_summary.dart';

/// Selects the live or mock repository.
///
/// Instructions §22 — the mock is chosen here, once, rather than by feature
/// code branching on a flag. Production paths cannot reach the mock because
/// `DataSourceMode.mock` is only settable in dev and qa.
final employeeHomeRepositoryProvider = Provider<EmployeeHomeRepository>((ref) {
  if (ref.watch(dataSourceModeProvider) == DataSourceMode.mock) {
    return MockEmployeeHomeRepository();
  }

  final scope = ref.watch(cacheScopeProvider);
  if (scope == null) {
    // No authenticated principal means no cache namespace, and an unscoped
    // cache write could be read by the next session on a shared device
    // (Instructions §16). The router prevents this state from being reachable;
    // failing loudly is better than caching without a scope.
    throw StateError(
      'employeeHomeRepositoryProvider read without an authenticated session',
    );
  }

  return ApiEmployeeHomeRepository(
    client: ref.watch(apiClientProvider),
    cache: ref.watch(cacheStoreProvider),
    scope: scope,
    connectivity: ref.watch(connectivityServiceProvider),
  );
});

/// E-01 Employee Home data.
///
/// Returns the whole [DataSnapshot] rather than just the summary, so the
/// screen can honour the Live vs Last-synchronized distinction (UI-UX §48).
final employeeHomeProvider =
    AsyncNotifierProvider<EmployeeHomeNotifier, DataSnapshot<EmployeeHomeSummary>>(
  EmployeeHomeNotifier.new,
);

class EmployeeHomeNotifier
    extends AsyncNotifier<DataSnapshot<EmployeeHomeSummary>> {
  @override
  Future<DataSnapshot<EmployeeHomeSummary>> build() {
    return ref.watch(employeeHomeRepositoryProvider).loadHome();
  }

  /// Pull-to-refresh. Keeps the current data visible while refetching, so the
  /// screen does not collapse to a skeleton on a manual refresh.
  Future<void> refresh() async {
    final repository = ref.read(employeeHomeRepositoryProvider);
    state = AsyncValue<DataSnapshot<EmployeeHomeSummary>>.loading()
        .copyWithPrevious(state);
    state = await AsyncValue.guard(
      () => repository.loadHome(forceRefresh: true),
    );
  }

  /// Invalidates after an action elsewhere changed the home state, e.g. a
  /// check-in or a leave submission.
  Future<void> invalidateAndReload() async {
    await ref.read(employeeHomeRepositoryProvider).invalidate();
    ref.invalidateSelf();
  }
}

/// Whether the last successful read came from cache, for the stale banner.
final employeeHomeIsStaleProvider = Provider<bool>((ref) {
  final snapshot = ref.watch(employeeHomeProvider);
  return snapshot.valueOrNull?.isStale ?? false;
});

/// Convenience: the failure behind the current error state, already mapped.
final employeeHomeFailureProvider = Provider<AppFailure?>((ref) {
  final snapshot = ref.watch(employeeHomeProvider);
  final error = snapshot.error;
  if (error == null) return null;
  return asAppFailure(error, snapshot.stackTrace);
});
