import '../../../core/data/cache_policy.dart';
import '../../../core/data/cache_store.dart';
import '../../../core/data/cached_resource.dart';
import '../../../core/networking/api_client.dart';
import '../../../core/networking/connectivity_service.dart';
import '../domain/leave_models.dart';

abstract interface class LeaveRepository {
  Future<DataSnapshot<LeaveOverview>> loadOverview({bool forceRefresh});

  Future<LeaveRequest> apply({
    required String typeId,
    required DateTime from,
    required DateTime to,
    String? reason,
  });

  Future<LeaveRequest> cancel(String requestId, {String? reason});

  Future<void> invalidate();
}

/// `GET /me/leave`, `POST /me/leave/apply`, `POST /me/leave/{id}/cancel`.
///
/// Balances are computed by Odoo from `hr.leave.type.virtual_remaining_leaves`
/// — allocation minus taken minus pending. The client never does that
/// arithmetic: accrual plans, carry-over and expiring allocations all feed it,
/// and an employee whose phone and web client disagree about their own balance
/// will trust neither.
class ApiLeaveRepository implements LeaveRepository {
  ApiLeaveRepository({
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

  static const String path = '/me/leave';

  CachedResource<LeaveOverview> get _resource => CachedResource<LeaveOverview>(
        key: CacheKeys.leaveBalance,
        // Longer than the dashboard: a balance changes when leave is approved,
        // not minute to minute, and this screen is opened repeatedly while
        // somebody decides on dates.
        policy: CachePolicy.activityList,
        scope: _scope,
        cache: _cache,
        connectivity: _connectivity,
        fetch: () async {
          final json = await _client.get<Map<String, dynamic>>(path);
          return LeaveOverview.fromJson(json);
        },
        decode: (json) =>
            LeaveOverview.fromJson((json as Map).cast<String, Object?>()),
        encode: (overview) => overview.toJson(),
      );

  @override
  Future<DataSnapshot<LeaveOverview>> loadOverview({
    bool forceRefresh = false,
  }) {
    return _resource.read(forceRefresh: forceRefresh);
  }

  @override
  Future<LeaveRequest> apply({
    required String typeId,
    required DateTime from,
    required DateTime to,
    String? reason,
  }) async {
    final json = await _client.post<Map<String, dynamic>>(
      '$path/apply',
      data: <String, Object?>{
        'type_id': typeId,
        // Date only, no time. Odoo's `request_date_from` is a Date field, and
        // sending a timestamp would make the day depend on the phone's
        // timezone — someone applying late at night could book the wrong day.
        'date_from': _day(from),
        'date_to': _day(to),
        if (reason != null && reason.isNotEmpty) 'reason': reason,
      },
    );
    await _resource.invalidate();
    return LeaveRequest.fromJson(
      (json['request'] as Map?)?.cast<String, Object?>() ?? json,
    );
  }

  @override
  Future<LeaveRequest> cancel(String requestId, {String? reason}) async {
    final json = await _client.post<Map<String, dynamic>>(
      '$path/$requestId/cancel',
      data: <String, Object?>{if (reason != null) 'reason': reason},
    );
    await _resource.invalidate();
    return LeaveRequest.fromJson(
      (json['request'] as Map?)?.cast<String, Object?>() ?? json,
    );
  }

  @override
  Future<void> invalidate() => _resource.invalidate();

  static String _day(DateTime value) =>
      '${value.year.toString().padLeft(4, '0')}-'
      '${value.month.toString().padLeft(2, '0')}-'
      '${value.day.toString().padLeft(2, '0')}';
}

/// Mock for development and widget tests.
class MockLeaveRepository implements LeaveRepository {
  MockLeaveRepository({
    this.latency = const Duration(milliseconds: 400),
    this.failWith,
    LeaveOverview? overview,
  }) : _overview = overview ?? sample();

  final Duration latency;
  final Object? failWith;
  LeaveOverview _overview;

  static LeaveOverview sample() {
    final now = DateTime.now();
    return LeaveOverview(
      balances: const [
        LeaveBalance(
          id: '1',
          label: 'Paid Time Off',
          remainingDays: 10,
          allocatedDays: 20,
          takenDays: 10,
        ),
        LeaveBalance(
          id: '2',
          label: 'Sick Leave',
          remainingDays: 6,
          allocatedDays: 10,
          takenDays: 4,
        ),
      ],
      requests: [
        LeaveRequest(
          id: '11',
          typeId: '1',
          typeLabel: 'Paid Time Off',
          dateFrom: now.add(const Duration(days: 12)),
          dateTo: now.add(const Duration(days: 14)),
          days: 3,
          state: LeaveState.waiting,
          stateLabel: 'Waiting approval',
          canCancel: true,
        ),
      ],
      pendingCount: 1,
    );
  }

  @override
  Future<DataSnapshot<LeaveOverview>> loadOverview({
    bool forceRefresh = false,
  }) async {
    await Future<void>.delayed(latency);
    final failure = failWith;
    if (failure != null) throw failure;
    return DataSnapshot.live(_overview, syncedAt: DateTime.now());
  }

  @override
  Future<LeaveRequest> apply({
    required String typeId,
    required DateTime from,
    required DateTime to,
    String? reason,
  }) async {
    await Future<void>.delayed(latency);
    final failure = failWith;
    if (failure != null) throw failure;

    final created = LeaveRequest(
      id: '${DateTime.now().millisecondsSinceEpoch}',
      typeId: typeId,
      typeLabel: _overview.balances
          .firstWhere(
            (b) => b.id == typeId,
            orElse: () => const LeaveBalance(
              id: '0',
              label: 'Time Off',
              remainingDays: 0,
            ),
          )
          .label,
      dateFrom: from,
      dateTo: to,
      days: to.difference(from).inDays + 1,
      state: LeaveState.waiting,
      stateLabel: 'Waiting approval',
      reason: reason,
      canCancel: true,
    );
    _overview = LeaveOverview(
      balances: _overview.balances,
      requests: [created, ..._overview.requests],
      pendingCount: _overview.pendingCount + 1,
    );
    return created;
  }

  @override
  Future<LeaveRequest> cancel(String requestId, {String? reason}) async {
    await Future<void>.delayed(latency);
    final failure = failWith;
    if (failure != null) throw failure;

    final requests = _overview.requests.map((r) {
      if (r.id != requestId) return r;
      return LeaveRequest(
        id: r.id,
        typeId: r.typeId,
        typeLabel: r.typeLabel,
        dateFrom: r.dateFrom,
        dateTo: r.dateTo,
        days: r.days,
        state: LeaveState.cancelled,
        stateLabel: 'Cancelled',
        reason: r.reason,
      );
    }).toList();

    _overview = LeaveOverview(
      balances: _overview.balances,
      requests: requests,
      pendingCount: requests.where((r) => r.state.isPending).length,
    );
    return requests.firstWhere((r) => r.id == requestId);
  }

  @override
  Future<void> invalidate() async {}
}
