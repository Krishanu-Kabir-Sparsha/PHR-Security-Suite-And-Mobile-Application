import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/data/cache_policy.dart';
import 'package:perfect_hr_mobile/core/data/cache_store.dart';
import 'package:perfect_hr_mobile/core/data/cached_resource.dart';
import 'package:perfect_hr_mobile/core/errors/app_failure.dart';
import 'package:perfect_hr_mobile/core/networking/connectivity_service.dart';

/// Covers Tech-Stack §11–12, UI-UX §48 and Instructions §16–17.
///
/// Two behaviours here are correctness-critical rather than cosmetic:
/// stale data must never be presented as current, and sensitive data must
/// never be served from cache at all.

const _scope = CacheScope(tenantId: 'tenant-a', userId: 'EMP-001');
const _otherScope = CacheScope(tenantId: 'tenant-b', userId: 'EMP-001');

CachedResource<Map<String, Object?>> _resource({
  required CacheStore cache,
  required ConnectivityService connectivity,
  required Future<Map<String, Object?>> Function() fetch,
  CachePolicy policy = CachePolicy.dashboard,
  CacheScope scope = _scope,
  String key = CacheKeys.dashboard,
  String? offlineMessage,
}) {
  return CachedResource<Map<String, Object?>>(
    key: key,
    policy: policy,
    scope: scope,
    cache: cache,
    connectivity: connectivity,
    fetch: fetch,
    decode: (json) => (json as Map).cast<String, Object?>(),
    encode: (value) => value,
    offlineMessage: offlineMessage,
  );
}

void main() {
  group('read strategy', () {
    test('a cold read fetches live and marks the snapshot live', () async {
      final cache = InMemoryCacheStore();
      var calls = 0;

      final snapshot = await _resource(
        cache: cache,
        connectivity: FakeConnectivityService(),
        fetch: () async {
          calls++;
          return {'present': 36};
        },
      ).read();

      expect(calls, 1);
      expect(snapshot.origin, DataOrigin.live);
      expect(snapshot.isStale, isFalse);
      expect(snapshot.data['present'], 36);
    });

    test('a fresh cache hit avoids the network entirely', () async {
      final cache = InMemoryCacheStore();
      final connectivity = FakeConnectivityService();
      var calls = 0;

      Future<Map<String, Object?>> fetch() async {
        calls++;
        return {'present': 36};
      }

      final resource = _resource(
        cache: cache,
        connectivity: connectivity,
        fetch: fetch,
      );

      await resource.read();
      final second = await resource.read();

      expect(calls, 1, reason: 'second read must be served from cache');
      expect(second.origin, DataOrigin.cache);
      expect(second.isStale, isTrue);
    });

    test('an expired cache entry triggers a refetch', () async {
      final cache = InMemoryCacheStore();
      var calls = 0;

      final resource = _resource(
        cache: cache,
        connectivity: FakeConnectivityService(),
        policy: const CachePolicy.ttl(Duration(minutes: 2)),
        fetch: () async {
          calls++;
          return {'present': 36 + calls};
        },
      );

      final first = await resource.read(now: DateTime(2026, 9, 7, 9, 0));
      final second = await resource.read(now: DateTime(2026, 9, 7, 9, 5));

      expect(calls, 2);
      expect(first.data['present'], 37);
      expect(second.data['present'], 38);
      expect(second.origin, DataOrigin.live);
    });

    test('forceRefresh bypasses a fresh cache', () async {
      final cache = InMemoryCacheStore();
      var calls = 0;

      final resource = _resource(
        cache: cache,
        connectivity: FakeConnectivityService(),
        fetch: () async {
          calls++;
          return {'present': 36};
        },
      );

      await resource.read();
      await resource.read(forceRefresh: true);

      expect(calls, 2);
    });
  });

  group('offline behaviour', () {
    test('a network failure falls back to cache marked stale', () async {
      final cache = InMemoryCacheStore();
      final connectivity = FakeConnectivityService();
      var shouldFail = false;

      final resource = _resource(
        cache: cache,
        connectivity: connectivity,
        policy: const CachePolicy.ttl(Duration(minutes: 2)),
        fetch: () async {
          if (shouldFail) throw const OfflineFailure();
          return {'present': 36};
        },
      );

      final live = await resource.read(now: DateTime(2026, 9, 7, 9, 0));
      expect(live.origin, DataOrigin.live);

      shouldFail = true;
      connectivity.setStatus(ConnectivityStatus.offline);
      final stale = await resource.read(now: DateTime(2026, 9, 7, 9, 30));

      expect(stale.origin, DataOrigin.cache);
      expect(stale.isStale, isTrue);
      expect(stale.data['present'], 36);
      // syncedAt must be the original server time, not the read time, so the
      // "Last synchronized" copy is truthful.
      expect(stale.syncedAt, DateTime(2026, 9, 7, 9, 0));
    });

    test('a network failure with no cache propagates the failure', () async {
      final resource = _resource(
        cache: InMemoryCacheStore(),
        connectivity: FakeConnectivityService(ConnectivityStatus.offline),
        fetch: () async => throw const OfflineFailure(),
      );

      await expectLater(resource.read(), throwsA(isA<OfflineFailure>()));
    });

    test('a permission denial is never masked by cached data', () async {
      final cache = InMemoryCacheStore();
      var denied = false;

      final resource = _resource(
        cache: cache,
        connectivity: FakeConnectivityService(),
        policy: const CachePolicy.ttl(Duration(minutes: 2)),
        fetch: () async {
          if (denied) throw const PermissionFailure();
          return {'present': 36};
        },
      );

      await resource.read(now: DateTime(2026, 9, 7, 9, 0));
      denied = true;

      // Access may have been revoked since the cache was written. Serving the
      // cached copy would contradict an authoritative server answer.
      await expectLater(
        resource.read(now: DateTime(2026, 9, 7, 9, 30)),
        throwsA(isA<PermissionFailure>()),
      );
    });

    test('a validation failure is not masked by cached data', () async {
      final cache = InMemoryCacheStore();
      await cache.write(
        _scope,
        CacheKeys.dashboard,
        {'present': 36},
        syncedAt: DateTime(2026, 9, 7, 9, 0),
      );

      final resource = _resource(
        cache: cache,
        connectivity: FakeConnectivityService(),
        fetch: () async => throw const ValidationFailure(),
      );

      await expectLater(
        resource.read(forceRefresh: true),
        throwsA(isA<ValidationFailure>()),
      );
    });
  });

  group('sensitive data is never cached', () {
    test('CachePolicy.never reports itself as non-cacheable', () {
      expect(CachePolicy.sensitive.cacheable, isFalse);
      expect(
        CachePolicy.sensitive.isFresh(DateTime.now()),
        isFalse,
      );
    });

    test('a successful sensitive read writes nothing to the cache', () async {
      final cache = InMemoryCacheStore();

      final snapshot = await _resource(
        cache: cache,
        connectivity: FakeConnectivityService(),
        policy: CachePolicy.sensitive,
        key: 'payroll:september',
        fetch: () async => {'net_salary': 42500},
      ).read();

      expect(snapshot.origin, DataOrigin.live);
      expect(cache.length, 0, reason: 'payroll must not reach local storage');
    });

    test('a sensitive read offline fails rather than serving stale data',
        () async {
      final resource = _resource(
        cache: InMemoryCacheStore(),
        connectivity: FakeConnectivityService(ConnectivityStatus.offline),
        policy: CachePolicy.sensitive,
        key: 'payroll:september',
        offlineMessage: 'Connection required to view your payslip.',
        fetch: () async => {'net_salary': 42500},
      );

      await expectLater(
        resource.read(),
        throwsA(
          isA<ConnectionRequiredFailure>().having(
            (f) => f.userMessage,
            'userMessage',
            'Connection required to view your payslip.',
          ),
        ),
      );
    });

    test('a sensitive read does not fall back even if an entry somehow exists',
        () async {
      final cache = InMemoryCacheStore();
      // Simulate a stray write from an earlier build or a bug.
      await cache.write(
        _scope,
        'payroll:september',
        {'net_salary': 1},
        syncedAt: DateTime(2026, 8, 1),
      );

      final resource = _resource(
        cache: cache,
        connectivity: FakeConnectivityService(),
        policy: CachePolicy.sensitive,
        key: 'payroll:september',
        fetch: () async => throw const NetworkFailure(),
      );

      await expectLater(resource.read(), throwsA(isA<NetworkFailure>()));
    });
  });

  group('cache scoping', () {
    test('one scope cannot read another scope\'s entry', () async {
      final cache = InMemoryCacheStore();
      await cache.write(
        _scope,
        CacheKeys.dashboard,
        {'present': 36},
        syncedAt: DateTime(2026, 9, 7),
      );

      expect(await cache.read(_otherScope, CacheKeys.dashboard), isNull);
      expect(await cache.read(_scope, CacheKeys.dashboard), isNotNull);
    });

    test('purging a scope leaves other scopes intact', () async {
      final cache = InMemoryCacheStore();
      final now = DateTime(2026, 9, 7);
      await cache.write(_scope, CacheKeys.dashboard, {'a': 1}, syncedAt: now);
      await cache.write(
        _otherScope,
        CacheKeys.dashboard,
        {'b': 2},
        syncedAt: now,
      );

      await cache.purgeScope(_scope);

      expect(await cache.read(_scope, CacheKeys.dashboard), isNull);
      expect(await cache.read(_otherScope, CacheKeys.dashboard), isNotNull);
    });

    test('scope equality distinguishes tenant and user', () {
      expect(
        const CacheScope(tenantId: 't', userId: 'u'),
        const CacheScope(tenantId: 't', userId: 'u'),
      );
      expect(
        const CacheScope(tenantId: 't', userId: 'u'),
        isNot(const CacheScope(tenantId: 't', userId: 'v')),
      );
      expect(
        const CacheScope(tenantId: 't', userId: 'u'),
        isNot(const CacheScope(tenantId: 's', userId: 'u')),
      );
    });
  });

  group('cache maintenance', () {
    test('deleteByPrefix invalidates a family of entries', () async {
      final cache = InMemoryCacheStore();
      final now = DateTime(2026, 9, 7);
      await cache.write(_scope, CacheKeys.leaveBalance, {'annual': 12},
          syncedAt: now);
      await cache.write(_scope, 'leave:history', <String>[], syncedAt: now);
      await cache.write(_scope, CacheKeys.dashboard, {'a': 1}, syncedAt: now);

      await cache.deleteByPrefix(_scope, CacheKeys.leavePrefix);

      expect(await cache.read(_scope, CacheKeys.leaveBalance), isNull);
      expect(await cache.read(_scope, 'leave:history'), isNull);
      expect(await cache.read(_scope, CacheKeys.dashboard), isNotNull);
    });

    test('purgeOlderThan removes only stale entries', () async {
      final cache = InMemoryCacheStore();
      await cache.write(
        _scope,
        'old',
        {'a': 1},
        syncedAt: DateTime.now().subtract(const Duration(days: 30)),
      );
      await cache.write(_scope, 'new', {'b': 2}, syncedAt: DateTime.now());

      final removed = await cache.purgeOlderThan(const Duration(days: 7));

      expect(removed, 1);
      expect(await cache.read(_scope, 'old'), isNull);
      expect(await cache.read(_scope, 'new'), isNotNull);
    });

    test('an undecodable entry is dropped rather than failing the read',
        () async {
      final cache = InMemoryCacheStore();
      // Payload shape from a previous schema.
      await cache.write(
        _scope,
        CacheKeys.dashboard,
        'a bare string',
        syncedAt: DateTime.now(),
      );

      final snapshot = await _resource(
        cache: cache,
        connectivity: FakeConnectivityService(),
        fetch: () async => {'present': 36},
      ).read();

      expect(snapshot.origin, DataOrigin.live);
      expect(snapshot.data['present'], 36);
    });

    test('cache round-trips through JSON, not object identity', () async {
      final cache = InMemoryCacheStore();
      final original = {'nested': {'value': 1}, 'list': [1, 2, 3]};
      await cache.write(_scope, 'k', original, syncedAt: DateTime(2026));

      final entry = await cache.read(_scope, 'k');
      expect(entry!.payload, isNot(same(original)));
      expect(entry.payload, original);
    });
  });

  group('live-connection guard', () {
    test('blocks an action when offline', () async {
      final connectivity =
          FakeConnectivityService(ConnectivityStatus.offline);
      var ran = false;

      await expectLater(
        requireLiveConnection(
          connectivity,
          action: () async {
            ran = true;
            return 'ok';
          },
          message: 'Connection required to complete check-in.',
        ),
        throwsA(isA<ConnectionRequiredFailure>()),
      );
      expect(ran, isFalse, reason: 'the action must not be attempted');
    });

    test('runs the action when online', () async {
      final result = await requireLiveConnection(
        FakeConnectivityService(),
        action: () async => 'ok',
      );
      expect(result, 'ok');
    });
  });
}
