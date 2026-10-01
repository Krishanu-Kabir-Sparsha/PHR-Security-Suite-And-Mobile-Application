import '../../../core/data/cache_policy.dart';
import '../../../core/data/cache_store.dart';
import '../../../core/data/cached_resource.dart';
import '../../../core/networking/api_client.dart';
import '../../../core/networking/connectivity_service.dart';
import '../../dashboard/domain/employee_home_summary.dart';
import '../domain/attendance_overview.dart';
import '../domain/offsite_request.dart';

abstract interface class AttendanceRepository {
  Future<DataSnapshot<AttendanceOverview>> loadOverview({bool forceRefresh});

  /// Check in if currently out, check out if currently in.
  ///
  /// The **server** resolves the direction. A phone cannot: it may have been
  /// offline while a kiosk or biometric punch happened, and a client-chosen
  /// direction would produce a double check-in that someone then has to correct
  /// by hand.
  Future<AttendanceToggleResult> toggle({
    double? latitude,
    double? longitude,
    double? accuracyMetres,
  });

  /// Ask a manager to accept a check-in that the location rule refused.
  ///
  /// Deliberately NOT a parameter on [toggle]. It used to be: the punch was
  /// resent carrying a reason and accepted on the strength of it, which meant
  /// the employee authorised their own exception and the radius stopped
  /// nobody who was willing to type a sentence.
  ///
  /// This records nothing. It creates a request; attendance appears only if
  /// somebody else approves, and then at the time of the attempt rather than
  /// the time of the decision.
  Future<OffsiteRequest> submitOffsiteRequest({
    required String reason,
    double? latitude,
    double? longitude,
    double? accuracyMetres,
  });

  /// The most recent request, so the app can say what became of it.
  ///
  /// Without this an employee sends a request into silence, and the only way
  /// to learn it was rejected is to be refused a second time.
  Future<OffsiteRequest?> loadOffsiteRequest();

  /// Start the break if none is running, end it if one is.
  ///
  /// A toggle for the same reason the check-in is: the phone may have been
  /// offline while the break ended elsewhere, and a client that picks the
  /// direction eventually picks the wrong one.
  Future<AttendanceToggleResult> toggleBreak({String? breakType});

  /// Close a session left open on an earlier day.
  ///
  /// The way out of [AttendanceState.checkedInStale]. The server closes it at
  /// the end of the working day it belongs to — never at now, which would
  /// record the intervening days as hours worked.
  Future<AttendanceOverview> resolveStale();

  Future<void> invalidate();
}

/// `GET /me/attendance` and `POST /me/attendance/toggle`.
///
/// ```json
/// {
///   "today": {"state": "checked_in", "check_in_at": "...",
///             "worked_minutes": 252, "sessions": [...]},
///   "shift_label": "Standard 40 hours/week",
///   "workplace_label": "Head Office",
///   "days": [{"date": "2026-09-16", "worked_minutes": 480, "sessions": [...]}]
/// }
/// ```
class ApiAttendanceRepository implements AttendanceRepository {
  ApiAttendanceRepository({
    required ApiClient client,
    required CacheStore cache,
    required CacheScope scope,
    required ConnectivityService connectivity,
  })  : _client = client,
        _cache = cache,
        _scope = scope,
        _connectivity = connectivity;

  final ApiClient _client;
  final CacheStore _cache;
  final CacheScope _scope;
  final ConnectivityService _connectivity;

  static const String path = '/me/attendance';

  CachedResource<AttendanceOverview> get _resource =>
      CachedResource<AttendanceOverview>(
        key: CacheKeys.attendanceToday,
        // Short. This screen answers "am I checked in?", and a stale yes is the
        // one answer that actively misleads — someone would walk away believing
        // they had checked out.
        policy: CachePolicy.dashboard,
        scope: _scope,
        cache: _cache,
        connectivity: _connectivity,
        fetch: () async {
          final json = await _client.get<Map<String, dynamic>>(path);
          return AttendanceOverview.fromJson(json);
        },
        decode: (json) => AttendanceOverview.fromJson(
          (json as Map).cast<String, Object?>(),
        ),
        encode: (overview) => overview.toJson(),
      );

  @override
  Future<DataSnapshot<AttendanceOverview>> loadOverview({
    bool forceRefresh = false,
  }) {
    return _resource.read(forceRefresh: forceRefresh);
  }

  @override
  Future<AttendanceToggleResult> toggle({
    double? latitude,
    double? longitude,
    double? accuracyMetres,
  }) async {
    final json = await _client.post<Map<String, dynamic>>(
      '$path/toggle',
      data: <String, Object?>{
        if (latitude != null) 'latitude': latitude,
        if (longitude != null) 'longitude': longitude,
        // The phone's own margin of error. The server subtracts it before
        // deciding anybody is out of range, so a poor fix counts in the
        // employee's favour rather than against them.
        if (accuracyMetres != null) 'accuracy_m': accuracyMetres,
      },
    );
    await _resource.invalidate();
    return AttendanceToggleResult.fromJson(json);
  }

  @override
  Future<OffsiteRequest> submitOffsiteRequest({
    required String reason,
    double? latitude,
    double? longitude,
    double? accuracyMetres,
  }) async {
    final json = await _client.post<Map<String, dynamic>>(
      '$path/offsite-request',
      data: <String, Object?>{
        'reason': reason,
        // Sent again rather than remembered from the refused punch. The server
        // re-judges the position, because what a manager will be shown has to
        // be measured rather than taken from a client that could flatter it.
        if (latitude != null) 'latitude': latitude,
        if (longitude != null) 'longitude': longitude,
        if (accuracyMetres != null) 'accuracy_m': accuracyMetres,
      },
    );
    final raw = json['request'];
    return OffsiteRequest.fromJson((raw as Map).cast<String, Object?>());
  }

  @override
  Future<OffsiteRequest?> loadOffsiteRequest() async {
    final json = await _client.get<Map<String, dynamic>>('$path/offsite-request');
    final raw = json['request'];
    return raw is Map
        ? OffsiteRequest.fromJson(raw.cast<String, Object?>())
        : null;
  }

  @override
  Future<AttendanceToggleResult> toggleBreak({String? breakType}) async {
    final json = await _client.post<Map<String, dynamic>>(
      '$path/break',
      data: <String, Object?>{
        if (breakType != null) 'break_type': breakType,
      },
    );
    await _resource.invalidate();
    return AttendanceToggleResult.fromJson(json);
  }

  @override
  Future<AttendanceOverview> resolveStale() async {
    final json = await _client.post<Map<String, dynamic>>(
      '$path/resolve-stale',
      // An idempotency key, because this is a mutation worth retrying: the
      // server treats "nothing stale" as success, so a replay is harmless,
      // and without a key RetryPolicy refuses to replay it at all.
      idempotencyKey: 'resolve-stale-${DateTime.now().toIso8601String()}',
    );
    await _resource.invalidate();
    final today = json['today'];
    return AttendanceOverview(
      today: TodayAttendance.fromJson(
        today is Map ? today.cast<String, Object?>() : const {},
      ),
    );
  }

  @override
  Future<void> invalidate() => _resource.invalidate();
}

/// Mock for development and for widget tests.
class MockAttendanceRepository implements AttendanceRepository {
  MockAttendanceRepository({
    this.latency = const Duration(milliseconds: 400),
    this.failWith,
    AttendanceOverview? overview,
  }) : _overview = overview ?? sample();

  final Duration latency;
  final Object? failWith;
  AttendanceOverview _overview;

  static AttendanceOverview sample() {
    final now = DateTime.now();
    return AttendanceOverview(
      today: TodayAttendance(
        state: AttendanceState.checkedIn,
        checkInAt: DateTime(now.year, now.month, now.day, 9, 4),
        workedMinutes: 252,
        shiftLabel: 'Standard 40 hours/week',
        workplaceLabel: 'Head Office',
      ),
      shiftLabel: 'Standard 40 hours/week',
      workplaceLabel: 'Head Office',
      days: [
        for (var i = 1; i <= 5; i++)
          AttendanceDay(
            date: now.subtract(Duration(days: i)),
            workedMinutes: 480 - i * 7,
            sessions: [
              AttendanceSession(
                id: '$i',
                checkIn: DateTime(now.year, now.month, now.day - i, 9, 2),
                checkOut: DateTime(now.year, now.month, now.day - i, 18, 0),
                workedHours: 8,
              ),
            ],
          ),
      ],
    );
  }

  @override
  Future<DataSnapshot<AttendanceOverview>> loadOverview({
    bool forceRefresh = false,
  }) async {
    await Future<void>.delayed(latency);
    final failure = failWith;
    if (failure != null) throw failure;
    return DataSnapshot.live(_overview, syncedAt: DateTime.now());
  }

  @override
  Future<AttendanceToggleResult> toggle({
    double? latitude,
    double? longitude,
    double? accuracyMetres,
  }) async {
    await Future<void>.delayed(latency);
    final failure = failWith;
    if (failure != null) throw failure;

    final wasIn = _overview.today.state.isWorking;
    final today = TodayAttendance(
      state: wasIn ? AttendanceState.checkedOut : AttendanceState.checkedIn,
      checkInAt: wasIn ? _overview.today.checkInAt : DateTime.now(),
      checkOutAt: wasIn ? DateTime.now() : null,
      workedMinutes: _overview.today.workedMinutes,
      shiftLabel: _overview.shiftLabel,
      workplaceLabel: _overview.workplaceLabel,
    );
    _overview = AttendanceOverview(
      today: today,
      days: _overview.days,
      shiftLabel: _overview.shiftLabel,
      workplaceLabel: _overview.workplaceLabel,
    );
    return AttendanceToggleResult(checkedIn: !wasIn, today: today);
  }

  @override
  Future<OffsiteRequest> submitOffsiteRequest({
    required String reason,
    double? latitude,
    double? longitude,
    double? accuracyMetres,
  }) async {
    await Future<void>.delayed(latency);
    return OffsiteRequest(
      id: 'mock-1',
      state: OffsiteRequestState.pending,
      requestedAt: DateTime.now(),
      reason: reason,
      distanceMetres: 1100,
      locationName: 'Head Office',
      manager: 'Ayesha Rahman',
    );
  }

  @override
  Future<OffsiteRequest?> loadOffsiteRequest() async {
    await Future<void>.delayed(latency);
    return null;
  }

  @override
  Future<AttendanceToggleResult> toggleBreak({String? breakType}) async {
    await Future<void>.delayed(latency);
    return AttendanceToggleResult(
      checkedIn: _overview.today.state.isWorking,
      today: _overview.today,
    );
  }

  @override
  Future<AttendanceOverview> resolveStale() async {
    await Future<void>.delayed(latency);
    return _overview;
  }

  @override
  Future<void> invalidate() async {}
}
