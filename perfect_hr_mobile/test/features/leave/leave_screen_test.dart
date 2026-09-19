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
import 'package:perfect_hr_mobile/features/dashboard/application/employee_home_providers.dart';
import 'package:perfect_hr_mobile/features/dashboard/data/employee_home_repository.dart';
import 'package:perfect_hr_mobile/features/leave/application/leave_providers.dart';
import 'package:perfect_hr_mobile/features/leave/data/leave_repository.dart';
import 'package:perfect_hr_mobile/features/leave/domain/leave_models.dart';
import 'package:perfect_hr_mobile/features/leave/presentation/leave_screen.dart';

/// E-05 Leave.
///
/// Balances are the reason people open this screen, and they are also what
/// makes Apply meaningful. The rules worth protecting are the ones where being
/// slightly wrong costs somebody a refused request: what counts as requestable,
/// and who is allowed to withdraw what.

class _StubRepository implements LeaveRepository {
  _StubRepository(this._overview, {this.error});

  LeaveOverview _overview;
  final Object? error;

  int applyCount = 0;
  int cancelCount = 0;
  String? cancelledId;

  @override
  Future<DataSnapshot<LeaveOverview>> loadOverview({
    bool forceRefresh = false,
  }) async {
    return DataSnapshot.live(_overview, syncedAt: DateTime.now());
  }

  @override
  Future<LeaveRequest> apply({
    required String typeId,
    required DateTime from,
    required DateTime to,
    String? reason,
  }) async {
    applyCount++;
    final failure = error;
    if (failure != null) throw failure;
    return LeaveRequest(
      id: '99',
      typeLabel: 'Paid Time Off',
      dateFrom: from,
      dateTo: to,
      days: 1,
      state: LeaveState.waiting,
      stateLabel: 'Waiting approval',
    );
  }

  @override
  Future<LeaveRequest> cancel(String requestId, {String? reason}) async {
    cancelCount++;
    cancelledId = requestId;
    final failure = error;
    if (failure != null) throw failure;

    final updated = _overview.requests
        .map(
          (r) => r.id != requestId
              ? r
              : LeaveRequest(
                  id: r.id,
                  typeLabel: r.typeLabel,
                  dateFrom: r.dateFrom,
                  dateTo: r.dateTo,
                  days: r.days,
                  state: LeaveState.cancelled,
                  stateLabel: 'Cancelled',
                ),
        )
        .toList();
    _overview = LeaveOverview(balances: _overview.balances, requests: updated);
    return updated.firstWhere((r) => r.id == requestId);
  }

  @override
  Future<void> invalidate() async {}
}

LeaveRequest _request({
  String id = '1',
  LeaveState state = LeaveState.waiting,
  String stateLabel = 'Waiting approval',
  bool canCancel = true,
}) {
  return LeaveRequest(
    id: id,
    typeLabel: 'Paid Time Off',
    dateFrom: DateTime(2026, 10, 1),
    dateTo: DateTime(2026, 10, 3),
    days: 3,
    state: state,
    stateLabel: stateLabel,
    canCancel: canCancel,
  );
}

ProviderContainer _container(
  LeaveRepository repository, {
  bool mayApply = true,
}) {
  final container = ProviderContainer(
    overrides: [
      leaveRepositoryProvider.overrideWithValue(repository),
      capabilitiesRepositoryProvider.overrideWithValue(
        MockCapabilitiesRepository(
          capabilities: AppCapabilities(
            features: const {AppFeature.leave},
            hasEmployeeRecord: true,
            permissions: {
              OdooModels.leave: ModelAccess(read: true, create: mayApply),
            },
          ),
        ),
      ),
      employeeHomeRepositoryProvider
          .overrideWithValue(MockEmployeeHomeRepository(latency: Duration.zero)),
    ],
  );
  // Permissions are per user, so capabilitiesProvider yields nothing without
  // a principal and every gated control would render disabled.
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
  tester.view.physicalSize = const Size(1200, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(theme: AppTheme.light(), home: const LeaveScreen()),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(AppConfig.initialise);

  group('balances', () {
    testWidgets('shows what is left, taken and allocated', (tester) async {
      final container = _container(
        _StubRepository(
          const LeaveOverview(
            balances: [
              LeaveBalance(
                id: '1',
                label: 'Paid Time Off',
                remainingDays: 10,
                allocatedDays: 20,
                takenDays: 10,
              ),
            ],
          ),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Paid Time Off'), findsOneWidget);
      // Whole numbers lose the decimal; half-days would keep it.
      expect(find.text('10 days left'), findsOneWidget);
      expect(find.text('10 days taken of 20 days allocated'), findsOneWidget);
    });

    testWidgets('explains an empty balance rather than showing nothing',
        (tester) async {
      final container = _container(_StubRepository(const LeaveOverview()));
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(
        find.textContaining('No leave has been allocated'),
        findsOneWidget,
      );
    });
  });

  group('applying', () {
    testWidgets('is disabled when nothing can be requested', (tester) async {
      // Offering Apply above a zero balance invites a request Odoo will refuse.
      final container = _container(
        _StubRepository(
          const LeaveOverview(
            balances: [
              LeaveBalance(id: '1', label: 'Paid Time Off', remainingDays: 0),
            ],
          ),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Apply for Leave'),
      );
      expect(button.onPressed, isNull);
    });

    testWidgets('stays available for a type that needs no allocation',
        (tester) async {
      // Odoo's "No Limit" types have no allocation at all. Treating a zero
      // allocation as "nothing left" would block unpaid leave entirely.
      final container = _container(
        _StubRepository(
          const LeaveOverview(
            balances: [
              LeaveBalance(
                id: '3',
                label: 'Unpaid',
                remainingDays: 0,
                requiresAllocation: false,
              ),
            ],
          ),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Apply for Leave'),
      );
      expect(button.onPressed, isNotNull);
    });
  });

  group('requests', () {
    testWidgets("uses the server's own wording for the state", (tester) async {
      // Odoo's approval chain is configurable per leave type, so a client-side
      // label would claim "second approval" on a single-approver type.
      final container = _container(
        _StubRepository(
          LeaveOverview(
            requests: [
              _request(
                state: LeaveState.waitingSecond,
                stateLabel: 'Waiting second approval',
              ),
            ],
          ),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Waiting second approval'), findsOneWidget);
    });

    testWidgets('offers cancel only where the server allows it',
        (tester) async {
      // can_cancel is Odoo's computed field. Re-deriving it from the state
      // would eventually disagree with the web client about the same request.
      final container = _container(
        _StubRepository(
          LeaveOverview(
            requests: [
              _request(id: '1', canCancel: false),
              _request(id: '2'),
            ],
          ),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Cancel request'), findsOneWidget);
    });

    testWidgets('confirms before withdrawing, and cancelling the dialog is safe',
        (tester) async {
      final repository = _StubRepository(
        LeaveOverview(requests: [_request(id: '7')]),
      );
      final container = _container(repository);
      addTearDown(container.dispose);
      await _pump(tester, container);

      await tester.tap(find.text('Cancel request'));
      await tester.pumpAndSettle();
      expect(find.byType(AlertDialog), findsOneWidget);

      await tester.tap(find.text('Keep it'));
      await tester.pumpAndSettle();
      expect(repository.cancelCount, 0);

      await tester.tap(find.text('Cancel request').first);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Cancel request'));
      await tester.pumpAndSettle();

      expect(repository.cancelCount, 1);
      expect(repository.cancelledId, '7');
    });

    testWidgets('shows a rejection without clearing the balances',
        (tester) async {
      // "You do not have enough days" is raised by Odoo at create time, and the
      // balances are exactly what the person needs in order to fix the request.
      final repository = _StubRepository(
        const LeaveOverview(
          balances: [
            LeaveBalance(id: '1', label: 'Paid Time Off', remainingDays: 2),
          ],
        ),
        error: const ValidationFailure(
          userMessage: 'You do not have enough days for this leave type.',
        ),
      );
      final container = _container(repository);
      addTearDown(container.dispose);
      await _pump(tester, container);

      await container.read(leaveActionProvider.notifier).apply(
            typeId: '1',
            from: DateTime(2026, 10, 1),
            to: DateTime(2026, 10, 30),
          );
      await tester.pumpAndSettle();

      expect(find.textContaining('do not have enough days'), findsOneWidget);
      expect(find.text('2 days left'), findsOneWidget);
    });
  });

  group('permission', () {
    testWidgets('disables Apply when the server does not permit it',
        (tester) async {
      // From Odoo's own has_access answer, which already reflects the Plaza
      // role's backing group, grant exceptions and record rules.
      final container = _container(
        _StubRepository(
          const LeaveOverview(
            balances: [
              LeaveBalance(id: '1', label: 'Paid Time Off', remainingDays: 10),
            ],
          ),
        ),
        mayApply: false,
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Apply for Leave'),
      );
      expect(button.onPressed, isNull);
    });

    testWidgets('distinguishes "no days left" from "not permitted"',
        (tester) async {
      // The two send the person to different people for a remedy, so one
      // message for both would be actively unhelpful.
      final container = _container(
        _StubRepository(
          const LeaveOverview(
            balances: [
              LeaveBalance(id: '1', label: 'Paid Time Off', remainingDays: 10),
            ],
          ),
        ),
        mayApply: false,
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(
        find.textContaining('role does not include requesting leave'),
        findsOneWidget,
      );
      expect(find.textContaining('No leave has been allocated'), findsNothing);
    });
  });
}
