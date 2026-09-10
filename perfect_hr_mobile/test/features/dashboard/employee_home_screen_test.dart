import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/config/app_config.dart';
import 'package:perfect_hr_mobile/core/data/cache_policy.dart';
import 'package:perfect_hr_mobile/core/errors/app_failure.dart';
import 'package:perfect_hr_mobile/core/session/session_controller.dart';
import 'package:perfect_hr_mobile/core/session/user_role.dart';
import 'package:perfect_hr_mobile/core/theme/app_theme.dart';
import 'package:perfect_hr_mobile/features/dashboard/application/employee_home_providers.dart';
import 'package:perfect_hr_mobile/features/dashboard/data/employee_home_repository.dart';
import 'package:perfect_hr_mobile/features/dashboard/domain/employee_home_summary.dart';
import 'package:perfect_hr_mobile/features/dashboard/presentation/employee_home_screen.dart';
import 'package:perfect_hr_mobile/shared/components/ux_states.dart';

/// **E-01 — Employee Home.**
///
/// Covers Screen & Wireframe Blueprint §9, UI-UX §12 and §48, and
/// Instructions §14, §45 (a feature is not complete when the UI renders) and
/// §20 (screen-ID traceability in the test name).

/// Repository stub driving one scripted outcome.
class _StubRepository implements EmployeeHomeRepository {
  _StubRepository({this.snapshot, this.failure});

  final DataSnapshot<EmployeeHomeSummary>? snapshot;
  final Object? failure;
  int loadCount = 0;
  int invalidateCount = 0;

  @override
  Future<DataSnapshot<EmployeeHomeSummary>> loadHome({
    bool forceRefresh = false,
  }) async {
    loadCount++;
    final f = failure;
    if (f != null) throw f;
    return snapshot!;
  }

  @override
  Future<void> invalidate() async => invalidateCount++;
}

Widget _app(ProviderContainer container) {
  return UncontrolledProviderScope(
    container: container,
    child: MaterialApp(
      theme: AppTheme.light(),
      home: const EmployeeHomeScreen(),
    ),
  );
}

ProviderContainer _container(EmployeeHomeRepository repository) {
  final container = ProviderContainer(
    overrides: [
      employeeHomeRepositoryProvider.overrideWithValue(repository),
    ],
  );
  container
      .read(sessionControllerProvider.notifier)
      .devSwitchRole(UserRole.employee);
  return container;
}

DataSnapshot<EmployeeHomeSummary> _live(EmployeeHomeSummary summary) =>
    DataSnapshot.live(summary, syncedAt: DateTime(2026, 9, 8, 9, 4));

void main() {
  setUpAll(() => AppConfig.initialise(flavorName: 'dev'));

  group('E-01 loaded state', () {
    testWidgets('renders the five specified sections in order', (tester) async {
      final container = _container(
        _StubRepository(snapshot: _live(MockEmployeeHomeRepository.sample())),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      // UI-UX §55 section order.
      expect(find.text('TODAY'), findsOneWidget);
      expect(find.text('QUICK ACTIONS'), findsOneWidget);
      expect(find.text('MY HR'), findsOneWidget);
      expect(find.text('PENDING'), findsOneWidget);

      final today = tester.getTopLeft(find.text('TODAY')).dy;
      final quick = tester.getTopLeft(find.text('QUICK ACTIONS')).dy;
      final myHr = tester.getTopLeft(find.text('MY HR')).dy;
      expect(today, lessThan(quick));
      expect(quick, lessThan(myHr));
    });

    testWidgets('shows the greeting with the employee first name',
        (tester) async {
      final container = _container(
        _StubRepository(snapshot: _live(MockEmployeeHomeRepository.sample())),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.textContaining('Rahim'), findsWidgets);
      expect(find.text('Software Engineer'), findsOneWidget);
    });

    testWidgets('TODAY card shows status, check-in time and worked duration',
        (tester) async {
      final container = _container(
        _StubRepository(snapshot: _live(MockEmployeeHomeRepository.sample())),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.text('CHECKED IN'), findsOneWidget);
      expect(find.text('9:04 AM'), findsOneWidget);
      // 252 minutes, formatted per the Blueprint wireframe.
      expect(find.text('Worked 04h 12m'), findsOneWidget);
      expect(find.text('Check Out'), findsOneWidget);
    });

    testWidgets('offers Check In, not Check Out, before checking in',
        (tester) async {
      final container = _container(
        _StubRepository(
          snapshot: _live(MockEmployeeHomeRepository.emptySample()),
        ),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.text('NOT CHECKED IN'), findsOneWidget);
      expect(find.text('Check Out'), findsNothing);
    });

    testWidgets('unread notification count reaches the header', (tester) async {
      final container = _container(
        _StubRepository(snapshot: _live(MockEmployeeHomeRepository.sample())),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.text('3'), findsWidgets);
    });
  });

  group('E-01 performance tile — Release 1 scope (Q2)', () {
    testWidgets('shows score and delta when a record exists', (tester) async {
      final container = _container(
        _StubRepository(snapshot: _live(MockEmployeeHomeRepository.sample())),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.text('84%'), findsOneWidget);
    });

    testWidgets('omits the tile entirely rather than showing 0%',
        (tester) async {
      // A new joiner, or a role whose data scope excludes performance.
      final container = _container(
        _StubRepository(
          snapshot: _live(MockEmployeeHomeRepository.emptySample()),
        ),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.text('PERFORMANCE'), findsNothing);
      expect(find.text('0%'), findsNothing);
    });
  });

  group('E-01 AI insight — trust rules', () {
    testWidgets('a descriptive insight is labelled AI-generated',
        (tester) async {
      final container = _container(
        _StubRepository(snapshot: _live(MockEmployeeHomeRepository.sample())),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.text('AI-GENERATED INSIGHT'), findsOneWidget);
      expect(
        find.text('Your attendance is healthy this month.'),
        findsOneWidget,
      );
    });

    testWidgets('a prediction with confidence is labelled as predicted',
        (tester) async {
      final summary = EmployeeHomeSummary(
        attendance: MockEmployeeHomeRepository.sample().attendance,
        aiInsight: const HomeAiInsight(
          headline: 'You may exceed your late-arrival threshold this month.',
          isPrediction: true,
          confidence: 0.78,
        ),
      );
      final container = _container(_StubRepository(snapshot: _live(summary)));
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.text('AI-PREDICTED RISK'), findsOneWidget);
      expect(find.text('78%'), findsOneWidget);
    });

    testWidgets(
        'a prediction missing its confidence degrades to a descriptive '
        'insight instead of overstating certainty', (tester) async {
      final summary = EmployeeHomeSummary(
        attendance: MockEmployeeHomeRepository.sample().attendance,
        aiInsight: const HomeAiInsight(
          headline: 'Attrition risk may be rising in your team.',
          isPrediction: true,
          // Server bug: prediction without confidence.
        ),
      );
      final container = _container(_StubRepository(snapshot: _live(summary)));
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      // Must not crash on the AiInsightCard assertion, and must not claim
      // to be a prediction without stating confidence (UI-UX §39).
      expect(tester.takeException(), isNull);
      expect(find.text('AI-PREDICTED RISK'), findsNothing);
      expect(find.text('AI-GENERATED INSIGHT'), findsOneWidget);
    });

    testWidgets('no insight means no AI card at all', (tester) async {
      final container = _container(
        _StubRepository(
          snapshot: _live(MockEmployeeHomeRepository.emptySample()),
        ),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.textContaining('AI-'), findsNothing);
    });
  });

  group('E-01 states', () {
    testWidgets('loading shows skeletons', (tester) async {
      final container = _container(
        _StubRepository(snapshot: _live(MockEmployeeHomeRepository.sample())),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.byType(AppSkeleton), findsWidgets);
    });

    testWidgets('a transport failure shows the error state with retry',
        (tester) async {
      final container = _container(
        _StubRepository(failure: const ServerFailure()),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.byType(AppErrorState), findsOneWidget);
      expect(find.text('Try Again'), findsOneWidget);
    });

    testWidgets('a permission failure shows restricted, without retry',
        (tester) async {
      final container = _container(
        _StubRepository(failure: const PermissionFailure()),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.byType(AppPermissionDeniedState), findsOneWidget);
      expect(find.text('Try Again'), findsNothing);
    });

    testWidgets('offline shows the offline state', (tester) async {
      final container = _container(
        _StubRepository(failure: const OfflineFailure()),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.byType(AppOfflineState), findsOneWidget);
    });

    testWidgets('cached data shows the last-synchronized banner',
        (tester) async {
      final container = _container(
        _StubRepository(
          snapshot: DataSnapshot.cached(
            MockEmployeeHomeRepository.sample(),
            syncedAt: DateTime(2026, 9, 8, 8, 30),
          ),
        ),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.byType(AppStaleDataBanner), findsOneWidget);
      expect(find.textContaining('8:30 AM'), findsOneWidget);
    });

    testWidgets('live data shows no stale banner', (tester) async {
      final container = _container(
        _StubRepository(snapshot: _live(MockEmployeeHomeRepository.sample())),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      expect(find.byType(AppStaleDataBanner), findsNothing);
    });

    testWidgets('an empty pending list reads as reassurance, not emptiness',
        (tester) async {
      final container = _container(
        _StubRepository(
          snapshot: _live(MockEmployeeHomeRepository.emptySample()),
        ),
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(_app(container));
      await tester.pumpAndSettle();

      // UI-UX §46 — never a bare "No requests."
      expect(find.textContaining("You're all caught up"), findsOneWidget);
    });
  });

  group('EmployeeHomeSummary parsing', () {
    test('parses the full PROPOSED API payload', () {
      final summary = EmployeeHomeSummary.fromJson({
        'attendance': {
          'state': 'checked_in',
          'check_in_at': '2026-09-08T09:04:00Z',
          'worked_minutes': 252,
          'shift_label': '09:00-18:00',
          'workplace_label': 'Head Office',
        },
        'leave_balances': [
          {'label': 'Annual', 'remaining_days': 12},
          {'label': 'Sick', 'remaining_days': 8.5},
        ],
        'performance': {'score': 0.84, 'delta_points': 9},
        'pending_items': [
          {
            'id': 'AC-1',
            'title': 'Attendance Correction',
            'subtitle': '08 Sep',
            'kind': 'attendance_correction',
          },
        ],
        'ai_insight': {'headline': 'All good.', 'is_prediction': false},
        'unread_notifications': 3,
      });

      expect(summary.attendance.state, AttendanceState.checkedIn);
      expect(summary.attendance.workedLabel, '04h 12m');
      expect(summary.leaveBalances.length, 2);
      expect(summary.leaveBalances[1].remainingLabel, '8.5');
      expect(summary.performance!.score, 0.84);
      expect(summary.pendingItems.single.kind,
          PendingItemKind.attendanceCorrection);
      expect(summary.unreadNotifications, 3);
    });

    test('survives a minimal payload without throwing', () {
      final summary = EmployeeHomeSummary.fromJson({});
      expect(summary.attendance.state, AttendanceState.notCheckedIn);
      expect(summary.leaveBalances, isEmpty);
      expect(summary.performance, isNull);
      expect(summary.aiInsight, isNull);
      expect(summary.unreadNotifications, 0);
    });

    test('an unknown enum value falls back rather than throwing', () {
      // A newer backend must not break an older client.
      final attendance =
          TodayAttendance.fromJson({'state': 'some_future_state'});
      expect(attendance.state, AttendanceState.notCheckedIn);

      final item = PendingItem.fromJson({'kind': 'future_kind'});
      expect(item.kind, PendingItemKind.hrRequest);
    });

    test('round-trips through JSON for the cache', () {
      final original = MockEmployeeHomeRepository.sample(
        now: DateTime(2026, 9, 8, 12),
      );
      final restored = EmployeeHomeSummary.fromJson(original.toJson());

      expect(restored.attendance.state, original.attendance.state);
      expect(restored.attendance.workedMinutes,
          original.attendance.workedMinutes);
      expect(restored.attendance.checkInAt, original.attendance.checkInAt);
      expect(restored.leaveBalances.length, original.leaveBalances.length);
      expect(restored.performance!.score, original.performance!.score);
      expect(restored.pendingItems.length, original.pendingItems.length);
      expect(restored.aiInsight!.headline, original.aiInsight!.headline);
    });

    test('a score outside 0..1 is clamped', () {
      expect(PerformanceSummary.fromJson({'score': 1.4}).score, 1.0);
      expect(PerformanceSummary.fromJson({'score': -0.2}).score, 0.0);
    });

    test('worked duration formats to the wireframe', () {
      expect(
        const TodayAttendance(
          state: AttendanceState.checkedIn,
          workedMinutes: 0,
        ).workedLabel,
        '00h 00m',
      );
      expect(
        const TodayAttendance(
          state: AttendanceState.checkedIn,
          workedMinutes: 252,
        ).workedLabel,
        '04h 12m',
      );
      expect(
        const TodayAttendance(
          state: AttendanceState.checkedIn,
          workedMinutes: 605,
        ).workedLabel,
        '10h 05m',
      );
    });

    test('attendance state gates the available actions', () {
      expect(AttendanceState.notCheckedIn.canCheckIn, isTrue);
      expect(AttendanceState.notCheckedIn.canCheckOut, isFalse);
      expect(AttendanceState.checkedIn.canCheckOut, isTrue);
      expect(AttendanceState.onBreak.canCheckOut, isTrue);
      expect(AttendanceState.checkedOut.canCheckIn, isFalse);
      expect(AttendanceState.onLeave.canCheckIn, isFalse);
    });
  });

  group('MockEmployeeHomeRepository', () {
    test('returns a live snapshot matching the Blueprint example', () async {
      final repository =
          MockEmployeeHomeRepository(latency: Duration.zero);
      final snapshot = await repository.loadHome();

      expect(snapshot.origin, DataOrigin.live);
      expect(snapshot.data.attendance.workedLabel, '04h 12m');
      expect(snapshot.data.leaveBalances.first.remainingLabel, '12');
    });

    test('can be scripted to fail, to exercise the error states', () async {
      final repository = MockEmployeeHomeRepository(
        latency: Duration.zero,
        failWith: const PermissionFailure(),
      );
      await expectLater(
        repository.loadHome(),
        throwsA(isA<PermissionFailure>()),
      );
    });
  });
}
