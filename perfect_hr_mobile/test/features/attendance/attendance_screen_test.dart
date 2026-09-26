import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/capabilities/app_capabilities.dart';
import 'package:perfect_hr_mobile/core/capabilities/capabilities_repository.dart';
import 'package:perfect_hr_mobile/core/capabilities/capability_providers.dart';
import 'package:perfect_hr_mobile/core/capabilities/model_access.dart';
import 'package:perfect_hr_mobile/core/config/app_config.dart';
import 'package:perfect_hr_mobile/core/session/session_controller.dart';
import 'package:perfect_hr_mobile/core/session/session_state.dart';
import 'package:perfect_hr_mobile/core/session/user_role.dart';
import 'package:perfect_hr_mobile/core/data/cache_policy.dart';
import 'package:perfect_hr_mobile/core/errors/app_failure.dart';
import 'package:perfect_hr_mobile/core/theme/app_theme.dart';
import 'package:perfect_hr_mobile/features/attendance/application/attendance_providers.dart';
import 'package:perfect_hr_mobile/features/attendance/data/attendance_repository.dart';
import 'package:perfect_hr_mobile/features/attendance/domain/attendance_overview.dart';
import 'package:perfect_hr_mobile/features/attendance/presentation/attendance_screen.dart';
import 'package:perfect_hr_mobile/features/dashboard/application/employee_home_providers.dart';
import 'package:perfect_hr_mobile/features/dashboard/data/employee_home_repository.dart';
import 'package:perfect_hr_mobile/features/dashboard/domain/employee_home_summary.dart';

/// E-02 Attendance.
///
/// The load-bearing rule: **the button follows the state the server last
/// reported, never what this screen believes it just did.** This deployment
/// runs `hr_attendance_gateway`, so biometric device punches are routine — a
/// phone that assumes its own last tap was the most recent event will
/// eventually offer "Check In" to someone already checked in by a door reader.

class _StubRepository implements AttendanceRepository {
  _StubRepository(this._overview, {this.toggleResult, this.toggleError});

  AttendanceOverview _overview;
  final AttendanceToggleResult? toggleResult;
  final Object? toggleError;

  int toggleCount = 0;
  int resolveStaleCount = 0;

  @override
  Future<DataSnapshot<AttendanceOverview>> loadOverview({
    bool forceRefresh = false,
  }) async {
    return DataSnapshot.live(_overview, syncedAt: DateTime.now());
  }

  @override
  Future<AttendanceToggleResult> toggle({
    double? latitude,
    double? longitude,
  }) async {
    toggleCount++;
    final error = toggleError;
    if (error != null) throw error;

    final result = toggleResult ??
        AttendanceToggleResult(
          checkedIn: !_overview.today.state.isWorking,
          today: TodayAttendance(
            state: _overview.today.state.isWorking
                ? AttendanceState.checkedOut
                : AttendanceState.checkedIn,
          ),
        );
    _overview = AttendanceOverview(today: result.today, days: _overview.days);
    return result;
  }

  @override
  Future<AttendanceOverview> resolveStale() async {
    resolveStaleCount++;
    return _overview;
  }

  @override
  Future<void> invalidate() async {}
}

AttendanceOverview _overview({
  AttendanceState state = AttendanceState.notCheckedIn,
  int workedMinutes = 0,
  List<AttendanceDay> days = const [],
}) {
  return AttendanceOverview(
    today: TodayAttendance(
      state: state,
      checkInAt: state == AttendanceState.notCheckedIn
          ? null
          : DateTime(2026, 9, 16, 9, 4),
      workedMinutes: workedMinutes,
    ),
    shiftLabel: 'Standard 40 hours/week',
    workplaceLabel: 'Head Office',
    days: days,
  );
}

ProviderContainer _container(
  AttendanceRepository repository, {
  bool mayPunch = true,
}) {
  final container = ProviderContainer(
    overrides: [
      attendanceRepositoryProvider.overrideWithValue(repository),
      // The punch button is gated on the server's own has_access answer, so a
      // test that grants nothing gets a correctly-disabled button.
      capabilitiesRepositoryProvider.overrideWithValue(
        MockCapabilitiesRepository(
          capabilities: AppCapabilities(
            features: const {AppFeature.attendance},
            hasEmployeeRecord: true,
            permissions: {
              OdooModels.attendance:
                  ModelAccess(read: true, create: mayPunch),
            },
          ),
        ),
      ),
      // A punch invalidates Home too, so Home's repository must not reach the
      // network from this test.
      employeeHomeRepositoryProvider
          .overrideWithValue(MockEmployeeHomeRepository(latency: Duration.zero)),
    ],
  );
  // capabilitiesProvider short-circuits to "unknown" without a principal —
  // correctly, since permissions are per user -- so the session has to exist
  // before any permission-gated control is pumped.
  container.read(sessionControllerProvider.notifier).establish(
        const SessionUser(
          employeeId: '1',
          displayName: 'Test Employee',
          role: UserRole.employee,
          tenantId: '1',
          tenantName: 'Perfect HR',
        ),
      );
  return container;
}

Future<void> _pump(WidgetTester tester, ProviderContainer container) async {
  tester.view.physicalSize = const Size(1200, 3000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(
        theme: AppTheme.light(),
        home: const AttendanceScreen(),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(AppConfig.initialise);

  group('today', () {
    testWidgets('offers Check In when the server says not checked in',
        (tester) async {
      final container = _container(_StubRepository(_overview()));
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('NOT CHECKED IN'), findsOneWidget);
      expect(find.text('Check In'), findsOneWidget);
      expect(find.text('Check Out'), findsNothing);
    });

    testWidgets('offers Check Out when the server says checked in',
        (tester) async {
      final container = _container(
        _StubRepository(
          _overview(state: AttendanceState.checkedIn, workedMinutes: 252),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('CHECKED IN'), findsOneWidget);
      expect(find.text('Check Out'), findsOneWidget);
      expect(find.textContaining('04h 12m'), findsWidgets);
    });

    testWidgets('will not let someone on approved leave punch in',
        (tester) async {
      // An attendance record would contradict the person's own approved leave,
      // and somebody would have to unpick it by hand afterwards.
      final container = _container(
        _StubRepository(_overview(state: AttendanceState.onLeave)),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('ON LEAVE'), findsOneWidget);
      final button = tester.widget<FilledButton>(
        find.byType(FilledButton).first,
      );
      expect(button.onPressed, isNull);
    });

    testWidgets('stays enabled after checking out', (tester) async {
      // A second shift, or a correction to a premature check-out, are both
      // legitimate. The server decides whether to accept it, not this screen.
      final container = _container(
        _StubRepository(_overview(state: AttendanceState.checkedOut)),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      final button = tester.widget<FilledButton>(
        find.byType(FilledButton).first,
      );
      expect(button.onPressed, isNotNull);
    });
  });

  group('punching', () {
    testWidgets('sends one toggle and follows the direction the server returns',
        (tester) async {
      final repository = _StubRepository(_overview());
      final container = _container(repository);
      addTearDown(container.dispose);
      await _pump(tester, container);

      await tester.tap(find.text('Check In'));
      await tester.pumpAndSettle();

      expect(repository.toggleCount, 1);
      // The label now reflects what came back, not what was tapped.
      expect(find.text('Check Out'), findsOneWidget);
    });

    testWidgets('reports a rejected punch without losing the current state',
        (tester) async {
      // Odoo raises on an overlapping record, and sec_record_freeze raises on a
      // frozen period. Either way the person must still be able to see whether
      // they are checked in.
      final repository = _StubRepository(
        _overview(state: AttendanceState.checkedIn),
        toggleError: const ValidationFailure(
          userMessage: 'Cannot create new attendance, the employee is '
              'already checked in.',
        ),
      );
      final container = _container(repository);
      addTearDown(container.dispose);
      await _pump(tester, container);

      await tester.tap(find.text('Check Out'));
      await tester.pumpAndSettle();

      expect(find.textContaining('already checked in'), findsOneWidget);
      expect(find.text('CHECKED IN'), findsOneWidget);
    });
  });

  group('history', () {
    testWidgets('summarises only the days actually worked', (tester) async {
      // Averaging across the whole window would include weekends and report a
      // misleadingly short working day.
      final container = _container(
        _StubRepository(
          _overview(
            days: [
              AttendanceDay(date: DateTime(2026, 9, 15), workedMinutes: 480),
              AttendanceDay(date: DateTime(2026, 9, 14), workedMinutes: 0),
              AttendanceDay(date: DateTime(2026, 9, 13), workedMinutes: 420),
            ],
          ),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('2'), findsOneWidget); // days present, not 3
      expect(find.text('7h 30m'), findsOneWidget); // (480 + 420) / 2
    });

    testWidgets('says so plainly when there is no history', (tester) async {
      final container = _container(_StubRepository(_overview()));
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(
        find.textContaining('No attendance has been recorded'),
        findsOneWidget,
      );
    });
  });

  group('permission', () {
    testWidgets('disables the punch when the server does not permit it',
        (tester) async {
      // Driven by Odoo's own has_access answer, which already accounts for the
      // Plaza role's backing group, grant exceptions and record rules. A role
      // without create on hr.attendance would otherwise be shown a button that
      // can only 403 — and a 403 reads as a broken app, not as a restriction.
      final container = _container(
        _StubRepository(_overview()),
        mayPunch: false,
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      final button = tester.widget<FilledButton>(
        find.byType(FilledButton).first,
      );
      expect(button.onPressed, isNull);
    });

    testWidgets('says why, and points at who can change it', (tester) async {
      // A disabled control with no explanation is indistinguishable from a
      // bug. Naming it as a permission sends the person to HR rather than to
      // whoever they think maintains the app.
      final container = _container(
        _StubRepository(_overview()),
        mayPunch: false,
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(
        find.textContaining('role does not include recording attendance'),
        findsOneWidget,
      );
    });
  });
}
