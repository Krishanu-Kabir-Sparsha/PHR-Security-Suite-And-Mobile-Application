import 'package:flutter/foundation.dart';

import '../../dashboard/domain/employee_home_summary.dart';

/// One check-in/check-out pair.
///
/// A day is a list of these rather than a single in/out pair, because a lunch
/// break produces two rows in `hr.attendance` and reporting only the last would
/// silently drop the morning.
@immutable
class AttendanceSession {
  const AttendanceSession({
    required this.id,
    required this.checkIn,
    this.checkOut,
    this.workedHours = 0,
    this.inCity,
    this.outCity,
  });

  final String id;
  final DateTime checkIn;
  final DateTime? checkOut;
  final double workedHours;
  final String? inCity;
  final String? outCity;

  bool get isOpen => checkOut == null;

  factory AttendanceSession.fromJson(Map<String, Object?> json) {
    return AttendanceSession(
      id: '${json['id']}',
      checkIn: _time(json['check_in']) ?? DateTime.now(),
      checkOut: _time(json['check_out']),
      workedHours: (json['worked_hours'] as num?)?.toDouble() ?? 0,
      inCity: json['in_city'] as String?,
      outCity: json['out_city'] as String?,
    );
  }

  Map<String, Object?> toJson() => {
        'id': id,
        'check_in': checkIn.toIso8601String(),
        'check_out': checkOut?.toIso8601String(),
        'worked_hours': workedHours,
        'in_city': inCity,
        'out_city': outCity,
      };
}

/// One calendar day's attendance.
///
/// Grouped server-side. Which day a late-evening punch belongs to depends on
/// the company's timezone, not the phone's, so the client must not do this
/// grouping itself — a traveller would otherwise see their own history shift.
@immutable
class AttendanceDay {
  const AttendanceDay({
    required this.date,
    required this.workedMinutes,
    this.sessions = const [],
  });

  final DateTime date;
  final int workedMinutes;
  final List<AttendanceSession> sessions;

  String get workedLabel {
    final hours = workedMinutes ~/ 60;
    final minutes = workedMinutes % 60;
    return '${hours.toString().padLeft(2, '0')}h '
        '${minutes.toString().padLeft(2, '0')}m';
  }

  factory AttendanceDay.fromJson(Map<String, Object?> json) {
    final sessions = json['sessions'];
    return AttendanceDay(
      date: DateTime.tryParse('${json['date']}') ?? DateTime.now(),
      workedMinutes: (json['worked_minutes'] as num?)?.toInt() ?? 0,
      sessions: sessions is List
          ? sessions
              .whereType<Map<Object?, Object?>>()
              .map((s) => AttendanceSession.fromJson(s.cast<String, Object?>()))
              .toList()
          : const [],
    );
  }

  Map<String, Object?> toJson() => {
        'date': date.toIso8601String().split('T').first,
        'worked_minutes': workedMinutes,
        'sessions': sessions.map((s) => s.toJson()).toList(),
      };
}

/// E-02 Attendance: today plus recent history.
@immutable
class AttendanceOverview {
  const AttendanceOverview({
    required this.today,
    this.days = const [],
    this.shiftLabel,
    this.workplaceLabel,
  });

  final TodayAttendance today;
  final List<AttendanceDay> days;
  final String? shiftLabel;
  final String? workplaceLabel;

  /// Days actually worked in the window, for the month summary.
  int get daysPresent => days.where((d) => d.workedMinutes > 0).length;

  int get totalWorkedMinutes =>
      days.fold<int>(0, (sum, day) => sum + day.workedMinutes);

  /// Average over days actually worked, not over the whole window — a window
  /// that includes weekends would otherwise report a misleadingly short day.
  String get averageDayLabel {
    final worked = daysPresent;
    if (worked == 0) return '—';
    final minutes = totalWorkedMinutes ~/ worked;
    return '${minutes ~/ 60}h ${(minutes % 60).toString().padLeft(2, '0')}m';
  }

  factory AttendanceOverview.fromJson(Map<String, Object?> json) {
    final today = json['today'];
    final days = json['days'];

    return AttendanceOverview(
      today: TodayAttendance.fromJson(
        today is Map ? today.cast<String, Object?>() : const {},
      ),
      days: days is List
          ? days
              .whereType<Map<Object?, Object?>>()
              .map((d) => AttendanceDay.fromJson(d.cast<String, Object?>()))
              .toList()
          : const [],
      shiftLabel: json['shift_label'] as String?,
      workplaceLabel: json['workplace_label'] as String?,
    );
  }

  Map<String, Object?> toJson() => {
        'today': today.toJson(),
        'days': days.map((d) => d.toJson()).toList(),
        'shift_label': shiftLabel,
        'workplace_label': workplaceLabel,
      };
}

/// The outcome of a toggle, as the **server** resolved it.
///
/// The direction is reported rather than assumed. A phone that has been offline
/// does not know whether a kiosk or biometric punch has happened since it last
/// synchronised, so it cannot say which way the toggle went — only the server
/// can, and telling the user "checked in" when they were checked out would be
/// worse than saying nothing.
@immutable
class AttendanceToggleResult {
  const AttendanceToggleResult({
    required this.checkedIn,
    required this.today,
  });

  final bool checkedIn;
  final TodayAttendance today;

  factory AttendanceToggleResult.fromJson(Map<String, Object?> json) {
    final today = json['today'];
    return AttendanceToggleResult(
      checkedIn: json['direction'] == 'check_in',
      today: TodayAttendance.fromJson(
        today is Map ? today.cast<String, Object?>() : const {},
      ),
    );
  }
}

DateTime? _time(Object? value) {
  if (value == null) return null;
  return DateTime.tryParse('$value')?.toLocal();
}
