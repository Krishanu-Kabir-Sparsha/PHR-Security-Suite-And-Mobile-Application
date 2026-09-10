/// Where a piece of data came from.
enum DataOrigin {
  /// Fetched from the server during this read.
  live,

  /// Served from the local cache.
  cache,
}

/// Data plus its provenance and age.
///
/// Spec: UI-UX Specification §48, Instructions §17.
///
/// The app must distinguish **Live** from **Last synchronized** and must never
/// silently present stale data as current. Returning a bare `T` from a
/// repository makes that impossible to honour at the UI layer, so every cached
/// read returns this instead and the widget decides whether to show
/// `AppStaleDataBanner`.
class DataSnapshot<T> {
  const DataSnapshot({
    required this.data,
    required this.origin,
    required this.syncedAt,
  });

  const DataSnapshot.live(this.data, {required this.syncedAt})
      : origin = DataOrigin.live;

  const DataSnapshot.cached(this.data, {required this.syncedAt})
      : origin = DataOrigin.cache;

  final T data;
  final DataOrigin origin;

  /// When this data was retrieved from the server — not when it was read from
  /// the cache. Drives the "Last synchronized 9:04 AM" copy.
  final DateTime syncedAt;

  bool get isStale => origin == DataOrigin.cache;

  DataSnapshot<R> map<R>(R Function(T data) transform) => DataSnapshot<R>(
        data: transform(data),
        origin: origin,
        syncedAt: syncedAt,
      );
}

/// Governs whether and for how long a resource may be cached.
///
/// The [CachePolicy.never] variant exists because some Perfect HR data must
/// not be persisted locally at all. Tech-Stack §11 forbids caching raw payroll
/// data, and Instructions §17 forbids showing stale sensitive information as
/// current. Expressing that as a policy — rather than as a rule each feature
/// must remember — means the repository can refuse to write it, and an offline
/// read fails cleanly instead of quietly serving last month's payslip.
class CachePolicy {
  /// Cacheable, considered fresh for [maxAge].
  const CachePolicy.ttl(Duration maxAge)
      : _maxAge = maxAge,
        cacheable = true;

  /// Cacheable with no freshness window: always revalidate when online, but
  /// fall back to cache when offline. Suits reference data that rarely
  /// changes, such as leave types or holiday calendars.
  const CachePolicy.revalidate()
      : _maxAge = Duration.zero,
        cacheable = true;

  /// Never persisted. Offline reads fail rather than serving stale data.
  ///
  /// Use for payroll amounts, bank details and anything else whose staleness
  /// would mislead about money or entitlement.
  const CachePolicy.never()
      : _maxAge = Duration.zero,
        cacheable = false;

  final Duration _maxAge;
  final bool cacheable;

  Duration get maxAge => _maxAge;

  /// Whether a cached entry synced at [syncedAt] may be served without a
  /// network round trip.
  bool isFresh(DateTime syncedAt, {DateTime? now}) {
    if (!cacheable) return false;
    if (_maxAge == Duration.zero) return false;
    final reference = now ?? DateTime.now();
    return reference.difference(syncedAt) < _maxAge;
  }

  // --- Conventional policies, so features do not invent their own ---------

  /// Dashboards and summaries: fresh enough to avoid a spinner on tab switch,
  /// short enough that today's attendance is not misreported.
  static const CachePolicy dashboard = CachePolicy.ttl(Duration(minutes: 2));

  /// Lists that change on user action, e.g. requests and approvals.
  static const CachePolicy activityList = CachePolicy.ttl(Duration(minutes: 5));

  /// Own profile: changes rarely, useful offline.
  static const CachePolicy profile = CachePolicy.ttl(Duration(hours: 12));

  /// Reference data: leave types, holiday calendar, departments.
  static const CachePolicy reference = CachePolicy.ttl(Duration(days: 1));

  /// Payroll, bank details, compensation. Never persisted.
  static const CachePolicy sensitive = CachePolicy.never();
}
