import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/errors/app_failure.dart';
import 'package:perfect_hr_mobile/core/theme/app_theme.dart';
import 'package:perfect_hr_mobile/features/subscription/application/subscription_providers.dart';
import 'package:perfect_hr_mobile/features/subscription/data/subscription_repository.dart';
import 'package:perfect_hr_mobile/features/subscription/domain/workspace_subscription.dart';
import 'package:perfect_hr_mobile/features/subscription/presentation/subscription_screen.dart';

/// The workspace's own plan, and the three ways this screen can end up with
/// nothing to show.
///
/// The thread running through all of it: **"there is no plan", "you may not
/// see the plan" and "we could not read the plan" are three different
/// sentences.** Collapsing them into one empty card would tell an
/// administrator their subscription had lapsed when it had not.

class _StubRepository implements SubscriptionRepository {
  _StubRepository({this.result, this.error});

  final SubscriptionResult? result;
  final Object? error;

  @override
  Future<SubscriptionResult> load() async {
    if (error != null) throw error!;
    return result ?? SubscriptionResult.none;
  }
}

ProviderContainer _container(SubscriptionRepository repository) {
  return ProviderContainer(
    overrides: [
      subscriptionRepositoryProvider.overrideWithValue(repository),
    ],
  );
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
        home: const SubscriptionScreen(),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('parsing what the server sent', () {
    test('a full plan comes through intact', () {
      final plan = WorkspaceSubscription.fromJson(const {
        'plan_name': 'Enterprise',
        'health': 'active',
        'headline': 'Your subscription is active.',
        'is_trial': false,
        'price': {'display': '৳12,000.00 / month', 'amount': 12000.0},
        'renews_on': '2027-01-01',
        'days_left': 97,
        'usage': {
          'users': {'used': 18, 'limit': 100, 'unit': 'users', 'ratio': 0.18},
        },
        'apps': ['Attendances', 'Payroll'],
      });

      expect(plan.planName, 'Enterprise');
      expect(plan.health, SubscriptionHealth.active);
      expect(plan.users?.used, 18);
      expect(plan.apps, ['Attendances', 'Payroll']);
    });

    test('an unknown health word does not become an alarm', () {
      // A newer server inventing a state must not make an older app shout
      // about it. Unknown is informational, never "needs attention".
      final plan = WorkspaceSubscription.fromJson(const {
        'health': 'gracefully_winding_down',
        'headline': 'Something new.',
      });

      expect(plan.health, SubscriptionHealth.unknown);
      expect(plan.health.needsAttention, isFalse);
    });

    test('only a stopped service demands attention', () {
      // Deliberately narrow. A trial and an approaching renewal are worth
      // noting; a banner that is coloured every day is one nobody reads.
      expect(SubscriptionHealth.suspended.needsAttention, isTrue);
      expect(SubscriptionHealth.ended.needsAttention, isTrue);
      expect(SubscriptionHealth.trial.needsAttention, isFalse);
      expect(SubscriptionHealth.renewing.needsAttention, isFalse);
      expect(SubscriptionHealth.active.needsAttention, isFalse);
    });
  });

  group('quota arithmetic', () {
    test('a capped quota reads as "used of limit"', () {
      const quota = QuotaUsage(used: 18, limit: 100, unit: 'users');
      expect(quota.display, '18 of 100 users');
    });

    test('an uncapped quota never invents a limit', () {
      // The trap: a plan with no seat cap must not render as a full bar or
      // divide by zero. It says what is used and stops there.
      const quota = QuotaUsage(used: 18, unit: 'users', unlimited: true);
      expect(quota.display, '18 users');
      expect(quota.limit, isNull);
    });

    test('fractional storage keeps one decimal, whole numbers keep none', () {
      // "4.2 of 50 GB" is useful; "4.20000001 of 50.0 GB" is noise.
      const partial = QuotaUsage(used: 4.2, limit: 50, unit: 'GB');
      const whole = QuotaUsage(used: 4, limit: 50, unit: 'GB');
      expect(partial.display, '4.2 of 50 GB');
      expect(whole.display, '4 of 50 GB');
    });
  });

  group('the screen', () {
    testWidgets('renders the plan, its price and its usage', (tester) async {
      final container = _container(const MockSubscriptionRepository());
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Enterprise'), findsOneWidget);
      expect(find.text('৳12,000.00 / month'), findsOneWidget);
      expect(find.text('18 of 100 users'), findsOneWidget);
    });

    testWidgets('states that a quota never stops anyone working',
        (tester) async {
      // Said out loud on the screen, because a progress bar beside a limit is
      // read as a threshold that will block something. Here it never does,
      // and an administrator who believes otherwise may buy seats they do not
      // need or stop people uploading documents they should.
      final container = _container(const MockSubscriptionRepository());
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(
        find.textContaining('never stops anyone working'),
        findsOneWidget,
      );
    });

    testWidgets('says when the deployment simply has no plan', (tester) async {
      // An on-premise install. Not an error, and not an empty plan card --
      // which would read as a subscription that had lapsed.
      final container = _container(_StubRepository(result: SubscriptionResult.none));
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('No subscription on this workspace'), findsOneWidget);
      expect(
        find.textContaining('Everything else in the app works normally'),
        findsOneWidget,
      );
    });

    testWidgets('a refusal reads as a refusal, not as a fault', (tester) async {
      // Somebody's access changed between the menu being drawn and this screen
      // opening. "Something went wrong" would send them to support over a
      // permission change.
      final container = _container(
        _StubRepository(
          error: const PermissionFailure(
            userMessage:
                'Your plan details are available to workspace administrators.',
            code: 'subscription_forbidden',
          ),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Not available to you'), findsOneWidget);
      expect(find.text('Could not load your plan'), findsNothing);
    });

    testWidgets('a failed read does NOT claim the plan is gone',
        (tester) async {
      // THE distinction this screen exists to keep. A network failure must
      // never be rendered as "no subscription".
      final container = _container(
        _StubRepository(error: const NetworkFailure(technical: 'timeout')),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Could not load your plan'), findsOneWidget);
      expect(find.text('No subscription on this workspace'), findsNothing);
    });

    testWidgets('says when the plan facts were last confirmed', (tester) async {
      // These come from a snapshot written by the billing server, not a live
      // call. Saying when they were last confirmed is the difference between
      // a stale number and a wrong one.
      final container = _container(const MockSubscriptionRepository());
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.textContaining('last confirmed'), findsOneWidget);
    });
  });
}
