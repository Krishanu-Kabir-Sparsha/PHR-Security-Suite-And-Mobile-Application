import 'dart:convert';

/// A cached JSON document with its sync time.
class CacheEntry {
  const CacheEntry({
    required this.key,
    required this.payload,
    required this.syncedAt,
  });

  final String key;

  /// Decoded JSON. Stored as text; decoded on read.
  final Object? payload;

  final DateTime syncedAt;
}

/// Local cache contract.
///
/// Spec: Tech-Stack §12, Instructions §17.
///
/// **Scoping is a security requirement, not a convenience.** Every entry is
/// namespaced by tenant and user, and [purgeScope] runs on sign-out. Perfect HR
/// is multi-tenant and a device may be shared — a support engineer signing in
/// after an employee must not be able to read the previous session's cached
/// records, and two tenants must never share a cache namespace
/// (Instructions §16).
abstract interface class CacheStore {
  /// Reads an entry, or null when absent.
  Future<CacheEntry?> read(CacheScope scope, String key);

  /// Writes or replaces an entry.
  Future<void> write(
    CacheScope scope,
    String key,
    Object? payload, {
    required DateTime syncedAt,
  });

  Future<void> delete(CacheScope scope, String key);

  /// Removes every entry whose key begins with [prefix]. Used to invalidate a
  /// family of records after a mutation, e.g. `leave:` after a submission.
  Future<void> deleteByPrefix(CacheScope scope, String prefix);

  /// Removes everything for a scope. Called on sign-out.
  Future<void> purgeScope(CacheScope scope);

  /// Removes entries older than [maxAge] across all scopes. Housekeeping, run
  /// at start-up so an abandoned account's data does not linger indefinitely.
  Future<int> purgeOlderThan(Duration maxAge);
}

/// Tenant + user namespace for cache entries.
class CacheScope {
  const CacheScope({required this.tenantId, required this.userId});

  final String tenantId;
  final String userId;

  /// Composite namespace. Both parts are included so that neither a tenant
  /// change nor a user change can ever resolve to another session's entries.
  String get value => '$tenantId::$userId';

  @override
  bool operator ==(Object other) =>
      other is CacheScope &&
      other.tenantId == tenantId &&
      other.userId == userId;

  @override
  int get hashCode => Object.hash(tenantId, userId);

  @override
  String toString() => 'CacheScope($value)';
}

/// Cache keys, kept in one place so prefixes stay consistent and
/// [CacheStore.deleteByPrefix] invalidations remain predictable.
abstract final class CacheKeys {
  static const String dashboard = 'dashboard:home';
  static const String profile = 'profile:me';
  static const String attendancePrefix = 'attendance:';
  static const String attendanceToday = 'attendance:today';
  static const String attendanceMonthPrefix = 'attendance:month:';
  static const String leavePrefix = 'leave:';
  static const String leaveBalance = 'leave:balance';
  static const String requestsPrefix = 'requests:';
  static const String notifications = 'notifications:recent';
  static const String referencePrefix = 'reference:';

  static String attendanceMonth(int year, int month) =>
      '$attendanceMonthPrefix$year-${month.toString().padLeft(2, '0')}';

  static String requestList(String status) => '$requestsPrefix$status';
}

/// In-memory [CacheStore] for tests and for the dev mock data source.
///
/// Behaviourally equivalent to the Drift implementation, including JSON
/// round-tripping — so a test that passes here is not passing only because it
/// held onto the same object reference.
class InMemoryCacheStore implements CacheStore {
  final Map<String, Map<String, _Record>> _data = {};

  @override
  Future<CacheEntry?> read(CacheScope scope, String key) async {
    final record = _data[scope.value]?[key];
    if (record == null) return null;
    return CacheEntry(
      key: key,
      payload: jsonDecode(record.json),
      syncedAt: record.syncedAt,
    );
  }

  @override
  Future<void> write(
    CacheScope scope,
    String key,
    Object? payload, {
    required DateTime syncedAt,
  }) async {
    final bucket = _data.putIfAbsent(scope.value, () => {});
    bucket[key] = _Record(jsonEncode(payload), syncedAt);
  }

  @override
  Future<void> delete(CacheScope scope, String key) async {
    _data[scope.value]?.remove(key);
  }

  @override
  Future<void> deleteByPrefix(CacheScope scope, String prefix) async {
    _data[scope.value]?.removeWhere((key, _) => key.startsWith(prefix));
  }

  @override
  Future<void> purgeScope(CacheScope scope) async {
    _data.remove(scope.value);
  }

  @override
  Future<int> purgeOlderThan(Duration maxAge) async {
    final cutoff = DateTime.now().subtract(maxAge);
    var removed = 0;
    for (final bucket in _data.values) {
      final stale = bucket.entries
          .where((e) => e.value.syncedAt.isBefore(cutoff))
          .map((e) => e.key)
          .toList();
      for (final key in stale) {
        bucket.remove(key);
        removed++;
      }
    }
    return removed;
  }

  /// Test helper: total entries across all scopes.
  int get length => _data.values.fold(0, (sum, b) => sum + b.length);
}

class _Record {
  const _Record(this.json, this.syncedAt);

  final String json;
  final DateTime syncedAt;
}
