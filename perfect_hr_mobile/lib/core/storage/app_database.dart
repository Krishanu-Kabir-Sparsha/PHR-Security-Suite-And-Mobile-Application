import 'dart:convert';

import 'package:drift/drift.dart';
import 'package:drift_flutter/drift_flutter.dart';

import '../data/cache_store.dart';

part 'app_database.g.dart';

/// Generic cache table.
///
/// Spec: Tech-Stack §12, Instructions §22 and §47.
///
/// A single key/JSON table rather than a typed table per resource. That is a
/// deliberate choice at this stage: the mobile API contracts do not exist yet
/// (Project State Q4), and designing ten schemas against endpoints that may
/// change would be inventing requirements. A resource that later needs real
/// querying — attendance history filtered by date range, say — gets its own
/// typed table in the task that builds it, alongside a migration.
///
/// Deliberately absent: any column for payroll amounts, bank details or
/// national ID. Those are governed by [CachePolicy.never] and must not reach
/// this database at all.
@DataClassName('CacheRow')
class CacheEntries extends Table {
  /// Tenant + user namespace. See [CacheScope] — scoping prevents one
  /// session's cache from being readable by the next.
  TextColumn get scope => text()();

  TextColumn get entryKey => text()();

  /// JSON-encoded payload.
  TextColumn get payload => text()();

  /// When the data was retrieved from the server.
  DateTimeColumn get syncedAt => dateTime()();

  @override
  Set<Column<Object>> get primaryKey => {scope, entryKey};
}

@DriftDatabase(tables: [CacheEntries])
class AppDatabase extends _$AppDatabase {
  AppDatabase([QueryExecutor? executor])
      : super(executor ?? _openConnection());

  /// In-memory database for tests.
  AppDatabase.forTesting(super.executor);

  @override
  int get schemaVersion => 1;

  @override
  MigrationStrategy get migration => MigrationStrategy(
        onCreate: (m) => m.createAll(),
        beforeOpen: (details) async {
          await customStatement('PRAGMA foreign_keys = ON');
        },
      );

  static QueryExecutor _openConnection() {
    // NOTE ON ENCRYPTION: this database is not encrypted at rest. That is
    // acceptable only because cache policy keeps genuinely sensitive data out
    // of it (payroll, bank, identity documents). If a future feature needs to
    // cache sensitive records, switch to SQLCipher via `sqlcipher_flutter_libs`
    // with the key held in Keystore/Keychain — do not relax the cache policy
    // instead. Raised as Project State Q8.
    return driftDatabase(name: 'perfect_hr_cache');
  }
}

/// [CacheStore] backed by Drift.
class DriftCacheStore implements CacheStore {
  DriftCacheStore(this._db);

  final AppDatabase _db;

  @override
  Future<CacheEntry?> read(CacheScope scope, String key) async {
    final row = await (_db.select(_db.cacheEntries)
          ..where((t) => t.scope.equals(scope.value) & t.entryKey.equals(key)))
        .getSingleOrNull();
    if (row == null) return null;
    return CacheEntry(
      key: row.entryKey,
      payload: jsonDecode(row.payload),
      syncedAt: row.syncedAt,
    );
  }

  @override
  Future<void> write(
    CacheScope scope,
    String key,
    Object? payload, {
    required DateTime syncedAt,
  }) async {
    await _db.into(_db.cacheEntries).insertOnConflictUpdate(
          CacheRow(
            scope: scope.value,
            entryKey: key,
            payload: jsonEncode(payload),
            syncedAt: syncedAt,
          ),
        );
  }

  @override
  Future<void> delete(CacheScope scope, String key) async {
    await (_db.delete(_db.cacheEntries)
          ..where((t) => t.scope.equals(scope.value) & t.entryKey.equals(key)))
        .go();
  }

  @override
  Future<void> deleteByPrefix(CacheScope scope, String prefix) async {
    await (_db.delete(_db.cacheEntries)
          ..where(
            (t) => t.scope.equals(scope.value) & t.entryKey.like('$prefix%'),
          ))
        .go();
  }

  @override
  Future<void> purgeScope(CacheScope scope) async {
    await (_db.delete(_db.cacheEntries)
          ..where((t) => t.scope.equals(scope.value)))
        .go();
  }

  @override
  Future<int> purgeOlderThan(Duration maxAge) {
    final cutoff = DateTime.now().subtract(maxAge);
    return (_db.delete(_db.cacheEntries)
          ..where((t) => t.syncedAt.isSmallerThanValue(cutoff)))
        .go();
  }
}
