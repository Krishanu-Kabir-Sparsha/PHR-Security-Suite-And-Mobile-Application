import 'package:flutter/foundation.dart';

/// Where a leave request has got to.
///
/// Wire values are `hr.leave.state`. `validate1` is Odoo's "first of two
/// approvals granted", which reads to an employee as still waiting — so it is
/// grouped with pending, not with approved.
enum LeaveState {
  draft('draft'),
  waiting('confirm'),
  waitingSecond('validate1'),
  approved('validate'),
  refused('refuse'),
  cancelled('cancel');

  const LeaveState(this.wireValue);

  final String wireValue;

  static LeaveState fromWire(String? value) => LeaveState.values.firstWhere(
        (s) => s.wireValue == value,
        orElse: () => LeaveState.draft,
      );

  bool get isPending =>
      this == LeaveState.waiting ||
      this == LeaveState.waitingSecond ||
      this == LeaveState.draft;

  bool get isApproved => this == LeaveState.approved;

  bool get isClosed =>
      this == LeaveState.refused || this == LeaveState.cancelled;
}

/// One leave type's balance for this employee.
@immutable
class LeaveBalance {
  const LeaveBalance({
    required this.id,
    required this.label,
    required this.remainingDays,
    this.allocatedDays = 0,
    this.takenDays = 0,
    this.requiresAllocation = true,
  });

  final String id;
  final String label;
  final double remainingDays;
  final double allocatedDays;
  final double takenDays;

  /// When false, this type can be requested without an allocation — Odoo's
  /// "No Limit". The apply screen must not block on a zero balance for these.
  final bool requiresAllocation;

  /// Whether applying is worth offering. A type with no allocation and no
  /// remaining days will be refused, and letting someone fill in a form first
  /// wastes their time.
  bool get canRequest => !requiresAllocation || remainingDays > 0;

  factory LeaveBalance.fromJson(Map<String, Object?> json) {
    return LeaveBalance(
      id: '${json['id']}',
      label: '${json['label'] ?? 'Time Off'}',
      remainingDays: (json['remaining_days'] as num?)?.toDouble() ?? 0,
      allocatedDays: (json['allocated_days'] as num?)?.toDouble() ?? 0,
      takenDays: (json['taken_days'] as num?)?.toDouble() ?? 0,
      requiresAllocation: json['requires_allocation'] as bool? ?? true,
    );
  }

  Map<String, Object?> toJson() => {
        'id': id,
        'label': label,
        'remaining_days': remainingDays,
        'allocated_days': allocatedDays,
        'taken_days': takenDays,
        'requires_allocation': requiresAllocation,
      };
}

/// One of the employee's own leave requests.
@immutable
class LeaveRequest {
  const LeaveRequest({
    required this.id,
    required this.typeLabel,
    required this.dateFrom,
    required this.dateTo,
    required this.days,
    required this.state,
    required this.stateLabel,
    this.typeId,
    this.reason,
    this.canCancel = false,
  });

  final String id;
  final String? typeId;
  final String typeLabel;
  final DateTime dateFrom;
  final DateTime dateTo;
  final double days;
  final LeaveState state;

  /// The server's own wording for the state.
  ///
  /// Preferred over a client-side label because Odoo's approval chain is
  /// configurable per leave type — "Waiting second approval" is meaningless on
  /// a type with a single approver, and the server knows which it is.
  final String stateLabel;

  final String? reason;

  /// Odoo's computed `can_cancel`, never re-derived here.
  ///
  /// It accounts for the validation type, the state, and whether the leave has
  /// already started. Re-deriving it from the state alone would eventually
  /// disagree with the web client about the same request.
  final bool canCancel;

  factory LeaveRequest.fromJson(Map<String, Object?> json) {
    return LeaveRequest(
      id: '${json['id']}',
      typeId: json['type_id']?.toString(),
      typeLabel: '${json['type_label'] ?? 'Time Off'}',
      dateFrom: _date(json['date_from']),
      dateTo: _date(json['date_to']),
      days: (json['days'] as num?)?.toDouble() ?? 0,
      state: LeaveState.fromWire(json['state'] as String?),
      stateLabel: '${json['state_label'] ?? ''}',
      reason: json['reason'] as String?,
      canCancel: json['can_cancel'] as bool? ?? false,
    );
  }

  Map<String, Object?> toJson() => {
        'id': id,
        'type_id': typeId,
        'type_label': typeLabel,
        'date_from': dateFrom.toIso8601String().split('T').first,
        'date_to': dateTo.toIso8601String().split('T').first,
        'days': days,
        'state': state.wireValue,
        'state_label': stateLabel,
        'reason': reason,
        'can_cancel': canCancel,
      };
}

/// E-05 Leave: balances and the employee's own request history.
@immutable
class LeaveOverview {
  const LeaveOverview({
    this.balances = const [],
    this.requests = const [],
    this.pendingCount = 0,
  });

  final List<LeaveBalance> balances;
  final List<LeaveRequest> requests;
  final int pendingCount;

  List<LeaveRequest> get upcoming {
    final today = DateTime.now();
    return requests
        .where((r) => !r.state.isClosed && !r.dateTo.isBefore(today))
        .toList();
  }

  /// Types the employee can actually apply for.
  List<LeaveBalance> get requestable =>
      balances.where((b) => b.canRequest).toList();

  factory LeaveOverview.fromJson(Map<String, Object?> json) {
    final balances = json['balances'];
    final requests = json['requests'];

    return LeaveOverview(
      balances: balances is List
          ? balances
              .whereType<Map<Object?, Object?>>()
              .map((b) => LeaveBalance.fromJson(b.cast<String, Object?>()))
              .toList()
          : const [],
      requests: requests is List
          ? requests
              .whereType<Map<Object?, Object?>>()
              .map((r) => LeaveRequest.fromJson(r.cast<String, Object?>()))
              .toList()
          : const [],
      pendingCount: (json['pending_count'] as num?)?.toInt() ?? 0,
    );
  }

  Map<String, Object?> toJson() => {
        'balances': balances.map((b) => b.toJson()).toList(),
        'requests': requests.map((r) => r.toJson()).toList(),
        'pending_count': pendingCount,
      };
}

DateTime _date(Object? value) =>
    DateTime.tryParse('$value') ?? DateTime.now();
