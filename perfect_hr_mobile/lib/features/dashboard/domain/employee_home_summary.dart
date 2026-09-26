import 'package:flutter/foundation.dart';
import '../../../core/utilities/server_time.dart';

/// Attendance state for today.
///
/// Screen & Wireframe Blueprint E-02 legend: ● Present ◐ Late ○ Absent ◇ Leave.
enum AttendanceState {
  notCheckedIn('not_checked_in'),
  checkedIn('checked_in'),

  /// An attendance row left open on an earlier day: they forgot to check out.
  ///
  /// Reported as its own state rather than folded into [checkedIn] because the
  /// remedy is different and because, until it is closed, Odoo's own overlap
  /// constraint refuses *every* new check-in. It used to surface as a raw
  /// database error after the user pressed a button that could never work
  /// ("the employee hasn't checked out since 09/24/2026 18:07:27"); now the
  /// app can say so first and offer to fix it.
  checkedInStale('checked_in_stale'),

  onBreak('on_break'),
  checkedOut('checked_out'),
  onLeave('on_leave'),
  holiday('holiday'),
  absent('absent');

  const AttendanceState(this.wireValue);

  final String wireValue;

  static AttendanceState fromWire(String? value) => AttendanceState.values
      .firstWhere((s) => s.wireValue == value, orElse: () => notCheckedIn);

  /// Checking out for lunch and back in again is one day, two sessions.
  ///
  /// This used to be `notCheckedIn` alone, which meant the Home card offered
  /// no buttons at all once somebody had checked out — `hasActions` is
  /// `canCheckIn || canCheckOut` and both were false. The Attendance tab keyed
  /// on `isWorking` instead and kept offering Check In, so the same account
  /// could act on one screen and not the other.
  bool get canCheckIn => this == notCheckedIn || this == checkedOut;

  bool get canCheckOut => this == checkedIn || this == onBreak;

  bool get isWorking => this == checkedIn || this == onBreak;

  /// Nothing normal can happen until the forgotten session is closed.
  bool get needsAttention => this == checkedInStale;
}

/// Today's attendance, as shown in the E-01 TODAY card.
@immutable
class TodayAttendance {
  const TodayAttendance({
    required this.state,
    this.checkInAt,
    this.breakStartedAt,
    this.checkOutAt,
    this.workedMinutes = 0,
    this.shiftLabel,
    this.workplaceLabel,
    this.openSince,
  });

  final AttendanceState state;
  final DateTime? checkInAt;
  final DateTime? breakStartedAt;
  final DateTime? checkOutAt;

  /// When the still-open session began. Set whenever a row is open, and the
  /// thing a stale-session message has to name — "still checked in from
  /// Thursday" is actionable, "still checked in" is not.
  final DateTime? openSince;

  /// Minutes worked so far today, computed server-side.
  ///
  /// Deliberately not derived on the client from [checkInAt]: break handling,
  /// shift rules and rounding are payroll-adjacent business logic and belong
  /// on the server (Instructions §7).
  final int workedMinutes;

  /// e.g. "09:00–18:00"
  final String? shiftLabel;

  /// e.g. "Head Office"
  final String? workplaceLabel;

  /// "04h 12m", matching the Blueprint E-01 wireframe.
  String get workedLabel {
    final hours = workedMinutes ~/ 60;
    final minutes = workedMinutes % 60;
    return '${hours.toString().padLeft(2, '0')}h '
        '${minutes.toString().padLeft(2, '0')}m';
  }

  factory TodayAttendance.fromJson(Map<String, Object?> json) {
    return TodayAttendance(
      state: AttendanceState.fromWire(json['state'] as String?),
      checkInAt: _parseTime(json['check_in_at']),
      breakStartedAt: _parseTime(json['break_started_at']),
      checkOutAt: _parseTime(json['check_out_at']),
      workedMinutes: (json['worked_minutes'] as num?)?.toInt() ?? 0,
      shiftLabel: json['shift_label'] as String?,
      workplaceLabel: json['workplace_label'] as String?,
      openSince: _parseTime(json['open_since']),
    );
  }

  Map<String, Object?> toJson() => {
        'state': state.wireValue,
        // UTC with a Z; see serialiseInstant. A local ISO string would be
        // re-read as UTC and shift on every cache round trip.
        'check_in_at': serialiseInstant(checkInAt),
        'break_started_at': serialiseInstant(breakStartedAt),
        'check_out_at': serialiseInstant(checkOutAt),
        'worked_minutes': workedMinutes,
        'shift_label': shiftLabel,
        'workplace_label': workplaceLabel,
        // Round-trips through the cache, so a stale session is still named
        // correctly when the app opens offline.
        'open_since': serialiseInstant(openSince),
      };
}

/// One leave type's remaining balance.
@immutable
class LeaveBalanceSummary {
  const LeaveBalanceSummary({
    required this.label,
    required this.remainingDays,
  });

  final String label;
  final double remainingDays;

  /// "12" rather than "12.0"; halves shown as "4.5".
  String get remainingLabel => remainingDays == remainingDays.roundToDouble()
      ? remainingDays.toStringAsFixed(0)
      : remainingDays.toStringAsFixed(1);

  factory LeaveBalanceSummary.fromJson(Map<String, Object?> json) =>
      LeaveBalanceSummary(
        label: json['label'] as String? ?? 'Leave',
        remainingDays: (json['remaining_days'] as num?)?.toDouble() ?? 0,
      );

  Map<String, Object?> toJson() => {
        'label': label,
        'remaining_days': remainingDays,
      };
}

/// Read-only performance summary.
///
/// Scope note: Project State Q2. Release 1 shows a score and direction only,
/// embedded here — the full E-12 dashboard is Release 2. This model has no
/// goals, competencies or review data precisely so it cannot quietly grow into
/// that screen.
@immutable
class PerformanceSummary {
  const PerformanceSummary({required this.score, this.deltaPoints});

  /// 0..1 fraction. Rendered as a percentage.
  final double score;

  /// Change in percentage points since the previous cycle. Null when there is
  /// no prior cycle to compare against — a new joiner must not be shown a
  /// misleading 0% change.
  final double? deltaPoints;

  factory PerformanceSummary.fromJson(Map<String, Object?> json) =>
      PerformanceSummary(
        score: ((json['score'] as num?)?.toDouble() ?? 0).clamp(0, 1),
        deltaPoints: (json['delta_points'] as num?)?.toDouble(),
      );

  Map<String, Object?> toJson() => {
        'score': score,
        'delta_points': deltaPoints,
      };
}

/// A pending item awaiting the employee or an approver.
@immutable
class PendingItem {
  const PendingItem({
    required this.id,
    required this.title,
    required this.subtitle,
    required this.kind,
  });

  final String id;
  final String title;

  /// e.g. "Submitted 08 Sep · Manager review"
  final String subtitle;

  /// Drives the icon and the destination. Unknown kinds fall back to a generic
  /// request so a new backend category cannot break the screen.
  final PendingItemKind kind;

  factory PendingItem.fromJson(Map<String, Object?> json) => PendingItem(
        id: json['id'] as String? ?? '',
        title: json['title'] as String? ?? 'Request',
        subtitle: json['subtitle'] as String? ?? '',
        kind: PendingItemKind.fromWire(json['kind'] as String?),
      );

  Map<String, Object?> toJson() => {
        'id': id,
        'title': title,
        'subtitle': subtitle,
        'kind': kind.wireValue,
      };
}

enum PendingItemKind {
  leave('leave'),
  attendanceCorrection('attendance_correction'),
  hrRequest('hr_request'),
  performanceReview('performance_review'),
  learning('learning');

  const PendingItemKind(this.wireValue);

  final String wireValue;

  static PendingItemKind fromWire(String? value) => PendingItemKind.values
      .firstWhere((k) => k.wireValue == value, orElse: () => hrRequest);
}

/// The AI insight shown on E-01.
///
/// Carries its provenance and confidence from the server rather than letting
/// the screen decide how to label AI output (Instructions §14).
@immutable
class HomeAiInsight {
  const HomeAiInsight({
    required this.headline,
    this.explanation,
    this.recommendation,
    this.confidence,
    this.isPrediction = false,
    this.insightId,
  });

  final String headline;
  final String? explanation;
  final String? recommendation;

  /// 0..1. Required by the UI when [isPrediction] is true (UI-UX §39).
  final double? confidence;

  final bool isPrediction;

  /// Target for "View Insight". Null hides the action.
  final String? insightId;

  factory HomeAiInsight.fromJson(Map<String, Object?> json) => HomeAiInsight(
        headline: json['headline'] as String? ?? '',
        explanation: json['explanation'] as String?,
        recommendation: json['recommendation'] as String?,
        confidence: (json['confidence'] as num?)?.toDouble(),
        isPrediction: json['is_prediction'] as bool? ?? false,
        insightId: json['insight_id'] as String?,
      );

  Map<String, Object?> toJson() => {
        'headline': headline,
        'explanation': explanation,
        'recommendation': recommendation,
        'confidence': confidence,
        'is_prediction': isPrediction,
        'insight_id': insightId,
      };
}

/// Everything E-01 renders, in one payload.
///
/// One aggregate rather than six parallel requests: Instructions §25 requires
/// mobile-optimised endpoints, and a home screen that fans out into six calls
/// is slow on the target market's networks and awkward to cache coherently.
@immutable
class EmployeeHomeSummary {
  const EmployeeHomeSummary({
    required this.attendance,
    this.leaveBalances = const [],
    this.performance,
    this.pendingItems = const [],
    this.aiInsight,
    this.unreadNotifications = 0,
  });

  final TodayAttendance attendance;
  final List<LeaveBalanceSummary> leaveBalances;

  /// Null when the employee has no performance record, or when the role's
  /// data scope excludes it. The screen omits the tile rather than showing 0%.
  final PerformanceSummary? performance;

  final List<PendingItem> pendingItems;
  final HomeAiInsight? aiInsight;
  final int unreadNotifications;

  /// Primary balance for the "MY HR" strip — the first entry the server
  /// returns, which it orders by relevance.
  LeaveBalanceSummary? get primaryLeaveBalance =>
      leaveBalances.isEmpty ? null : leaveBalances.first;

  factory EmployeeHomeSummary.fromJson(Map<String, Object?> json) {
    return EmployeeHomeSummary(
      attendance: TodayAttendance.fromJson(
        (json['attendance'] as Map?)?.cast<String, Object?>() ?? const {},
      ),
      leaveBalances: ((json['leave_balances'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => LeaveBalanceSummary.fromJson(e.cast<String, Object?>()))
          .toList(growable: false),
      performance: json['performance'] == null
          ? null
          : PerformanceSummary.fromJson(
              (json['performance'] as Map).cast<String, Object?>(),
            ),
      pendingItems: ((json['pending_items'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => PendingItem.fromJson(e.cast<String, Object?>()))
          .toList(growable: false),
      aiInsight: json['ai_insight'] == null
          ? null
          : HomeAiInsight.fromJson(
              (json['ai_insight'] as Map).cast<String, Object?>(),
            ),
      unreadNotifications:
          (json['unread_notifications'] as num?)?.toInt() ?? 0,
    );
  }

  Map<String, Object?> toJson() => {
        'attendance': attendance.toJson(),
        'leave_balances': leaveBalances.map((e) => e.toJson()).toList(),
        'performance': performance?.toJson(),
        'pending_items': pendingItems.map((e) => e.toJson()).toList(),
        'ai_insight': aiInsight?.toJson(),
        'unread_notifications': unreadNotifications,
      };
}

DateTime? _parseTime(Object? value) {
  if (value is! String || value.isEmpty) return null;
  return parseServerTime(value);
}
