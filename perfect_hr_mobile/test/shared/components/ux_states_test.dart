import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/errors/app_failure.dart';
import 'package:perfect_hr_mobile/core/theme/app_theme.dart';
import 'package:perfect_hr_mobile/shared/components/async_state_view.dart';
import 'package:perfect_hr_mobile/shared/components/ux_states.dart';

/// Covers Screen & Wireframe Blueprint §52 (six global UX states) and
/// Instructions §24 (no raw technical errors reach the user).

Widget _wrap(Widget child) {
  return MaterialApp(
    theme: AppTheme.light(),
    home: Scaffold(body: child),
  );
}

void main() {
  group('individual UX states', () {
    testWidgets('loading state renders skeletons, not a bare spinner',
        (tester) async {
      await tester.pumpWidget(_wrap(const AppLoadingState(cardCount: 2)));
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.byType(AppSkeleton), findsWidgets);
      expect(find.byType(CircularProgressIndicator), findsNothing);
    });

    testWidgets('empty state shows a reassuring title and optional action',
        (tester) async {
      var tapped = false;
      await tester.pumpWidget(
        _wrap(
          AppEmptyState(
            title: 'No pending HR requests',
            message: "You're all caught up.",
            actionLabel: 'Create Request',
            onAction: () => tapped = true,
          ),
        ),
      );

      expect(find.text('No pending HR requests'), findsOneWidget);
      expect(find.text("You're all caught up."), findsOneWidget);

      await tester.tap(find.text('Create Request'));
      expect(tapped, isTrue);
    });

    testWidgets('error state offers Try Again when retryable', (tester) async {
      var retried = false;
      await tester.pumpWidget(
        _wrap(AppErrorState(onRetry: () => retried = true)),
      );

      expect(find.text('Try Again'), findsOneWidget);
      await tester.tap(find.text('Try Again'));
      expect(retried, isTrue);
    });

    testWidgets('offline state states that data is last synchronized',
        (tester) async {
      await tester.pumpWidget(
        _wrap(AppOfflineState(lastSyncedAt: DateTime(2026, 9, 7, 9, 4))));

      expect(find.textContaining("You're offline"), findsOneWidget);
      expect(find.textContaining('Last synchronized 9:04 AM'), findsOneWidget);
    });

    testWidgets('permission denied state offers no retry affordance',
        (tester) async {
      await tester.pumpWidget(_wrap(const AppPermissionDeniedState()));

      expect(
        find.text("You don't have permission to view this information."),
        findsOneWidget,
      );
      expect(find.text('Try Again'), findsNothing);
    });
  });

  group('AsyncStateView failure mapping', () {
    Widget view(AsyncValue<List<String>> value) {
      return _wrap(
        AsyncStateView<List<String>>(
          value: value,
          onRetry: () {},
          onGoBack: () {},
          isEmpty: (data) => data.isEmpty,
          emptyTitle: 'Nothing here yet',
          builder: (data) => Text('items: ${data.length}'),
        ),
      );
    }

    testWidgets('data renders the caller content', (tester) async {
      await tester.pumpWidget(view(const AsyncValue.data(['a', 'b'])));
      expect(find.text('items: 2'), findsOneWidget);
    });

    testWidgets('empty data renders the empty state', (tester) async {
      await tester.pumpWidget(view(const AsyncValue.data([])));
      expect(find.text('Nothing here yet'), findsOneWidget);
    });

    testWidgets('OfflineFailure renders the offline state', (tester) async {
      await tester.pumpWidget(
        view(AsyncValue.error(const OfflineFailure(), StackTrace.empty)),
      );
      expect(find.byType(AppOfflineState), findsOneWidget);
    });

    testWidgets('PermissionFailure renders permission denied, never an error',
        (tester) async {
      await tester.pumpWidget(
        view(AsyncValue.error(const PermissionFailure(), StackTrace.empty)),
      );
      expect(find.byType(AppPermissionDeniedState), findsOneWidget);
      expect(find.byType(AppErrorState), findsNothing);
    });

    testWidgets('PermissionFailure suppresses retry because it cannot succeed',
        (tester) async {
      await tester.pumpWidget(
        view(AsyncValue.error(const PermissionFailure(), StackTrace.empty)),
      );
      expect(find.text('Try Again'), findsNothing);
    });

    testWidgets('an unmapped exception still shows a safe message',
        (tester) async {
      await tester.pumpWidget(
        view(
          AsyncValue.error(
            Exception('DioException: HTTP 500 at /api/v1/me/dashboard'),
            StackTrace.empty,
          ),
        ),
      );

      expect(find.text('Something went wrong. Please try again.'),
          findsOneWidget);
      // Instructions §24 — technical detail must not surface.
      expect(find.textContaining('500'), findsNothing);
      expect(find.textContaining('Dio'), findsNothing);
      expect(find.textContaining('api/v1'), findsNothing);
    });
  });

  group('failure model', () {
    test('every failure variant maps to a UX state', () {
      const failures = <AppFailure>[
        OfflineFailure(),
        ConnectionRequiredFailure(),
        NetworkFailure(),
        ServerFailure(),
        PermissionFailure(),
        SessionExpiredFailure(),
        NotFoundFailure(),
        ValidationFailure(),
        UnknownFailure(),
      ];

      for (final failure in failures) {
        expect(failure.uxState, isA<FailureUxState>());
        expect(failure.userMessage, isNotEmpty);
      }
    });

    test('user messages contain no technical markers', () {
      const failures = <AppFailure>[
        OfflineFailure(),
        NetworkFailure(),
        ServerFailure(),
        PermissionFailure(),
        UnknownFailure(),
      ];

      for (final failure in failures) {
        expect(failure.userMessage, isNot(contains('HTTP')));
        expect(failure.userMessage, isNot(matches(RegExp(r'\b[45]\d{2}\b'))));
      }
    });

    test('asAppFailure passes through an existing failure unchanged', () {
      const original = PermissionFailure(scope: 'payroll.org.read');
      expect(asAppFailure(original), same(original));
    });

    test('asAppFailure wraps an arbitrary error safely', () {
      final failure = asAppFailure(StateError('token decode failed'));
      expect(failure, isA<UnknownFailure>());
      expect(failure.userMessage, isNot(contains('token')));
      expect(failure.technical, contains('token'));
    });
  });
}
