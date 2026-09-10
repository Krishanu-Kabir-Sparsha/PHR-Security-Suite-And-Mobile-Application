import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/app_config.dart';
import '../session/session_controller.dart';
import '../session/session_state.dart';
import '../storage/app_database.dart';
import 'cache_store.dart';

/// Whether repositories serve live API data or local mock data.
///
/// Spec: Instructions §22 (Mock Data Rule).
///
/// Mock mode exists so UI work can proceed before the mobile endpoints exist
/// (Project State Q4). It is selectable only in dev and qa builds, so mock
/// data cannot reach a UAT or production user even if a feature forgets to
/// swap its repository.
enum DataSourceMode { live, mock }

class DataSourceModeController extends Notifier<DataSourceMode> {
  @override
  DataSourceMode build() {
    // Live by default even in dev: a feature must opt into mocks explicitly,
    // so nobody demos mock data believing it came from the backend.
    return DataSourceMode.live;
  }

  void useMocks() {
    if (!AppConfig.current.allowsDevTools) {
      assert(false, 'Mock data sources are not permitted in this flavour.');
      return;
    }
    state = DataSourceMode.mock;
  }

  void useLive() => state = DataSourceMode.live;
}

final dataSourceModeProvider =
    NotifierProvider<DataSourceModeController, DataSourceMode>(
  DataSourceModeController.new,
);

final appDatabaseProvider = Provider<AppDatabase>((ref) {
  final database = AppDatabase();
  ref.onDispose(database.close);
  return database;
});

final cacheStoreProvider = Provider<CacheStore>((ref) {
  return DriftCacheStore(ref.watch(appDatabaseProvider));
});

/// The active cache namespace, or null when unauthenticated.
///
/// Repositories must not read or write the cache without a scope: an unscoped
/// entry could be read by the next session on a shared device
/// (Instructions §16).
final cacheScopeProvider = Provider<CacheScope?>((ref) {
  final user = ref.watch(activeUserProvider);
  if (user == null) return null;
  return CacheScope(tenantId: user.tenantId, userId: user.employeeId);
});

/// Purges cached data when a session ends.
///
/// Spec: Instructions §15 (secure logout), §16 (tenant isolation).
///
/// Without this, signing out would leave one employee's cached dashboard,
/// attendance and requests on disk for whoever signs in next. Keep this
/// provider alive for the lifetime of the app — `PerfectHrApp` watches it.
final cacheLifecycleProvider = Provider<void>((ref) {
  CacheScope? previousScope = ref.read(cacheScopeProvider);

  ref.listen<SessionState>(sessionControllerProvider, (before, after) {
    final scopeToPurge = previousScope;

    if (after is SessionAuthenticated) {
      final nextScope = CacheScope(
        tenantId: after.user.tenantId,
        userId: after.user.employeeId,
      );
      // A different principal on the same device: clear the previous one's
      // cache rather than letting two scopes coexist on disk.
      if (scopeToPurge != null && scopeToPurge != nextScope) {
        _purge(ref, scopeToPurge);
      }
      previousScope = nextScope;
      return;
    }

    // Sign-out or session expiry.
    if (scopeToPurge != null) {
      _purge(ref, scopeToPurge);
    }
    previousScope = null;
  });

  // Housekeeping: drop anything older than a week at start-up, so an
  // abandoned account's data does not linger indefinitely.
  Future<void>(() async {
    try {
      await ref.read(cacheStoreProvider).purgeOlderThan(
            const Duration(days: 7),
          );
    } catch (_) {
      // Housekeeping must never prevent start-up.
    }
  });
});

void _purge(Ref ref, CacheScope scope) {
  Future<void>(() async {
    try {
      await ref.read(cacheStoreProvider).purgeScope(scope);
    } catch (_) {
      // A failed purge must not block sign-out. The start-up sweep and the
      // scope namespace both limit the exposure.
    }
  });
}
