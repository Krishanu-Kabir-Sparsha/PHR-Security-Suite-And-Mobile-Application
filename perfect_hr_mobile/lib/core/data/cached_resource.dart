import '../errors/app_failure.dart';
import '../networking/connectivity_service.dart';
import 'cache_policy.dart';
import 'cache_store.dart';

/// Base class for a read of one cacheable resource.
///
/// Spec: Tech-Stack §12, UI-UX §48, Instructions §17 and §21.
///
/// Read strategy, in order:
///
/// 1. **Fresh cache** (within the policy's TTL, and not a forced refresh) →
///    return it. No network call, so tab switches feel instant.
/// 2. **Online** → fetch, write to cache when the policy permits, return live.
/// 3. **Fetch failed but cache exists** → return the cached copy marked stale,
///    so a flaky network degrades instead of erroring.
/// 4. **Fetch failed, no cache** → propagate the failure, which
///    `AsyncStateView` renders as the right one of the six UX states.
///
/// The exception to step 3 is a [CachePolicy.never] resource: it is neither
/// written nor served from cache, so an offline read of payroll fails rather
/// than showing a stale amount as current.
class CachedResource<T> {
  CachedResource({
    required this.key,
    required this.policy,
    required this.scope,
    required this.cache,
    required this.connectivity,
    required this.fetch,
    required this.decode,
    required this.encode,
    this.offlineMessage,
  });

  /// Cache key. Use a [CacheKeys] constant.
  final String key;

  final CachePolicy policy;
  final CacheScope scope;
  final CacheStore cache;
  final ConnectivityService connectivity;

  /// Remote read. Must throw an [AppFailure] on error — `ApiClient` guarantees
  /// this, so repositories never see a `DioException`.
  final Future<T> Function() fetch;

  /// Rebuilds [T] from cached JSON.
  final T Function(Object? json) decode;

  /// Serialises [T] for the cache.
  final Object? Function(T value) encode;

  /// Overrides the offline copy, e.g. for payroll:
  /// "Connection required to view your payslip."
  final String? offlineMessage;

  Future<DataSnapshot<T>> read({
    bool forceRefresh = false,
    DateTime? now,
  }) async {
    final reference = now ?? DateTime.now();

    if (!forceRefresh && policy.cacheable) {
      final cached = await _readCache();
      if (cached != null && policy.isFresh(cached.syncedAt, now: reference)) {
        return DataSnapshot.cached(cached.data, syncedAt: cached.syncedAt);
      }
    }

    // A non-cacheable resource cannot be satisfied offline at all, so fail
    // before attempting a request that is certain to fail less clearly.
    if (!policy.cacheable && connectivity.isOffline) {
      throw ConnectionRequiredFailure(
        userMessage: offlineMessage ??
            'Connection required to view this information.',
        technical: 'non-cacheable resource requested offline: $key',
      );
    }

    try {
      final data = await fetch();
      if (policy.cacheable) {
        await cache.write(scope, key, encode(data), syncedAt: reference);
      }
      return DataSnapshot.live(data, syncedAt: reference);
    } on AppFailure catch (failure) {
      // A permission denial or a validation error is an authoritative answer
      // from the server. Falling back to cache would contradict it, and could
      // show data the user has since lost access to.
      if (!_isFallbackEligible(failure)) rethrow;
      if (!policy.cacheable) rethrow;

      final cached = await _readCache();
      if (cached == null) rethrow;

      return DataSnapshot.cached(cached.data, syncedAt: cached.syncedAt);
    }
  }

  /// Only transport-class failures justify serving stale data.
  bool _isFallbackEligible(AppFailure failure) {
    return failure is OfflineFailure ||
        failure is NetworkFailure ||
        failure is ServerFailure;
  }

  Future<_CachedValue<T>?> _readCache() async {
    if (!policy.cacheable) return null;
    final entry = await cache.read(scope, key);
    if (entry == null) return null;
    try {
      return _CachedValue(decode(entry.payload), entry.syncedAt);
    } catch (_) {
      // A schema change can leave undecodable entries. Drop rather than fail:
      // a corrupt cache must never block a working online read.
      await cache.delete(scope, key);
      return null;
    }
  }

  /// Invalidates this entry, e.g. after a mutation that affects it.
  Future<void> invalidate() => cache.delete(scope, key);
}

class _CachedValue<T> {
  const _CachedValue(this.data, this.syncedAt);

  final T data;
  final DateTime syncedAt;
}
