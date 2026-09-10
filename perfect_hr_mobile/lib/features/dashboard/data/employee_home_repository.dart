import '../../../core/data/cache_policy.dart';
import '../../../core/data/cache_store.dart';
import '../../../core/data/cached_resource.dart';
import '../../../core/networking/api_client.dart';
import '../../../core/networking/connectivity_service.dart';
import '../domain/employee_home_summary.dart';

/// Reads the E-01 Employee Home aggregate.
abstract interface class EmployeeHomeRepository {
  /// [forceRefresh] bypasses a fresh cache, for pull-to-refresh.
  Future<DataSnapshot<EmployeeHomeSummary>> loadHome({bool forceRefresh});

  /// Invalidates the cached home summary. Called after any action that changes
  /// it — check-in, leave submission, request creation — so the user is not
  /// shown a stale card immediately after acting.
  Future<void> invalidate();
}

/// **PROPOSED API** — not yet implemented server-side (Project State Q4).
///
/// ```
/// GET /api/v1/me/home
/// ```
///
/// | Aspect | Value |
/// | --- | --- |
/// | Auth | Bearer, required |
/// | Tenant | From token claims; no request parameter |
/// | Permission | `attendance.self.read` implied by an authenticated employee |
/// | Pagination | None. `pending_items` capped server-side at 5 |
/// | Cache | `CachePolicy.dashboard`, 2 minutes |
///
/// Response 200:
/// ```json
/// {
///   "attendance": {
///     "state": "checked_in",
///     "check_in_at": "2026-09-08T09:04:00+06:00",
///     "break_started_at": null,
///     "check_out_at": null,
///     "worked_minutes": 252,
///     "shift_label": "09:00-18:00",
///     "workplace_label": "Head Office"
///   },
///   "leave_balances": [
///     {"label": "Annual", "remaining_days": 12},
///     {"label": "Sick", "remaining_days": 8}
///   ],
///   "performance": {"score": 0.84, "delta_points": 9},
///   "pending_items": [
///     {"id": "AC-2026-0041", "title": "Attendance Correction",
///      "subtitle": "08 Sep · Manager review", "kind": "attendance_correction"}
///   ],
///   "ai_insight": {
///     "headline": "Your attendance is healthy this month.",
///     "explanation": "You had 3 late arrivals this week.",
///     "recommendation": null,
///     "confidence": null,
///     "is_prediction": false,
///     "insight_id": "INS-2026-0912"
///   },
///   "unread_notifications": 3
/// }
/// ```
///
/// Notes for the backend team:
/// - `worked_minutes` must be computed server-side. Break handling, shift
///   rules and rounding are payroll-adjacent and must not be re-derived on the
///   client (Instructions §7).
/// - `performance` may be omitted entirely when the employee has no record or
///   the data scope excludes it. The client omits the tile rather than
///   rendering 0%.
/// - `delta_points` must be omitted, not zero, when there is no prior cycle.
/// - `ai_insight.is_prediction` must be true whenever the insight is
///   forward-looking, and `confidence` is then required — the client refuses
///   to render a prediction without one (Instructions §14).
/// - Errors follow the envelope in the Project State API contract: optional
///   display-safe `user_message`, optional `errors` map.
class ApiEmployeeHomeRepository implements EmployeeHomeRepository {
  ApiEmployeeHomeRepository({
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

  static const String path = '/me/home';

  CachedResource<EmployeeHomeSummary> get _resource =>
      CachedResource<EmployeeHomeSummary>(
        key: CacheKeys.dashboard,
        policy: CachePolicy.dashboard,
        scope: _scope,
        cache: _cache,
        connectivity: _connectivity,
        fetch: () async {
          final json = await _client.get<Map<String, dynamic>>(path);
          return EmployeeHomeSummary.fromJson(json);
        },
        decode: (json) => EmployeeHomeSummary.fromJson(
          (json as Map).cast<String, Object?>(),
        ),
        encode: (summary) => summary.toJson(),
      );

  @override
  Future<DataSnapshot<EmployeeHomeSummary>> loadHome({
    bool forceRefresh = false,
  }) {
    return _resource.read(forceRefresh: forceRefresh);
  }

  @override
  Future<void> invalidate() => _resource.invalidate();
}

/// Mock repository for UI development before `GET /me/home` exists.
///
/// Instructions §22: mock data must be clearly separated, must not be
/// hard-coded into production repositories, and must keep the same interface
/// so it is replaceable. This class is selected only when
/// `DataSourceMode.mock` is active, which is dev/qa only.
///
/// Values match the Screen & Wireframe Blueprint E-01 wireframe so the
/// rendered screen can be compared against the specification directly.
class MockEmployeeHomeRepository implements EmployeeHomeRepository {
  MockEmployeeHomeRepository({
    this.latency = const Duration(milliseconds: 600),
    this.failWith,
    EmployeeHomeSummary? summary,
  }) : _summary = summary;

  /// Simulated network delay, so loading states are actually visible during
  /// development rather than flashing past.
  final Duration latency;

  /// When set, `loadHome` throws it. Used to exercise the error, offline and
  /// permission states without unplugging anything.
  final Object? failWith;

  final EmployeeHomeSummary? _summary;

  @override
  Future<DataSnapshot<EmployeeHomeSummary>> loadHome({
    bool forceRefresh = false,
  }) async {
    await Future<void>.delayed(latency);
    final failure = failWith;
    if (failure != null) throw failure;
    return DataSnapshot.live(
      _summary ?? sample(),
      syncedAt: DateTime.now(),
    );
  }

  @override
  Future<void> invalidate() async {}

  /// The Blueprint E-01 example state: checked in at 09:04, 4h 12m worked.
  static EmployeeHomeSummary sample({DateTime? now}) {
    final reference = now ?? DateTime.now();
    final checkIn = DateTime(
      reference.year,
      reference.month,
      reference.day,
      9,
      4,
    );

    return EmployeeHomeSummary(
      attendance: TodayAttendance(
        state: AttendanceState.checkedIn,
        checkInAt: checkIn,
        workedMinutes: 252,
        shiftLabel: '09:00–18:00',
        workplaceLabel: 'Head Office',
      ),
      leaveBalances: const [
        LeaveBalanceSummary(label: 'Annual', remainingDays: 12),
        LeaveBalanceSummary(label: 'Sick', remainingDays: 8),
        LeaveBalanceSummary(label: 'Casual', remainingDays: 4),
      ],
      performance: const PerformanceSummary(score: 0.84, deltaPoints: 9),
      pendingItems: const [
        PendingItem(
          id: 'AC-2026-0041',
          title: 'Attendance Correction',
          subtitle: '08 Sep · Manager review',
          kind: PendingItemKind.attendanceCorrection,
        ),
        PendingItem(
          id: 'LR-2026-00123',
          title: 'Annual Leave · 15–17 Sep',
          subtitle: 'Waiting for manager approval',
          kind: PendingItemKind.leave,
        ),
      ],
      aiInsight: const HomeAiInsight(
        headline: 'Your attendance is healthy this month.',
        explanation: 'You had 3 late arrivals this week.',
        insightId: 'INS-2026-0912',
      ),
      unreadNotifications: 3,
    );
  }

  /// A first-day employee: nothing recorded, nothing pending, no performance
  /// history. Exercises the empty-ish path that a demo dataset always hides.
  static EmployeeHomeSummary emptySample() => const EmployeeHomeSummary(
        attendance: TodayAttendance(
          state: AttendanceState.notCheckedIn,
          shiftLabel: '09:00–18:00',
          workplaceLabel: 'Head Office',
        ),
        leaveBalances: [
          LeaveBalanceSummary(label: 'Annual', remainingDays: 0),
        ],
      );
}
