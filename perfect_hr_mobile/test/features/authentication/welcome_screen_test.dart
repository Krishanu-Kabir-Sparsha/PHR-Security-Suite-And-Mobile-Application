import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/config/app_config.dart';
import 'package:perfect_hr_mobile/core/data/data_providers.dart';
import 'package:perfect_hr_mobile/core/session/session_controller.dart';
import 'package:perfect_hr_mobile/core/session/session_state.dart';
import 'package:perfect_hr_mobile/core/theme/app_theme.dart';
import 'package:perfect_hr_mobile/features/authentication/presentation/welcome_screen.dart';

/// Regression tests for a Welcome screen whose buttons did nothing.
///
/// Both actions shipped as `onPressed: null` from Task 1, pending an
/// authentication task that changed shape and never wired them. Visually they
/// looked like buttons, so the app appeared frozen: the only thing that
/// responded was the development role switcher.
///
/// A disabled button is invisible to most widget tests — it renders, it finds,
/// it simply does not act — so the assertion has to be on `enabled`, not on
/// presence.

Widget _app(ProviderContainer container) {
  return UncontrolledProviderScope(
    container: container,
    child: MaterialApp(theme: AppTheme.light(), home: const WelcomeScreen()),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(AppConfig.initialise);

  testWidgets('the sign-in button is enabled', (tester) async {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    await tester.pumpWidget(_app(container));
    await tester.pumpAndSettle();

    final button = tester.widget<FilledButton>(find.byType(FilledButton).first);
    expect(
      button.onPressed,
      isNotNull,
      reason: 'a button the user can see must do something when tapped',
    );
  });

  testWidgets('offers one sign-in action, not two competing ones',
      (tester) async {
    // "Get Started" and "Sign In" both led to the same place. There is no
    // self-service sign-up in an HR product, so the second only made people
    // hesitate over which was correct.
    final container = ProviderContainer();
    addTearDown(container.dispose);

    await tester.pumpWidget(_app(container));
    await tester.pumpAndSettle();

    expect(find.text('Sign In'), findsOneWidget);
    expect(find.text('Get Started'), findsNothing);
  });

  testWidgets('a dev role switches the app to mock data', (tester) async {
    // A dev session is a fabricated identity with no token, so live requests
    // could only return 401 and the shell would render as "session expired" —
    // which reads as a broken app rather than a development shortcut.
    final container = ProviderContainer();
    addTearDown(container.dispose);

    await tester.pumpWidget(_app(container));
    await tester.pumpAndSettle();

    expect(container.read(dataSourceModeProvider), DataSourceMode.live);

    await tester.tap(find.text('Employee'));
    await tester.pumpAndSettle();

    expect(container.read(dataSourceModeProvider), DataSourceMode.mock);
    expect(container.read(sessionControllerProvider), isA<SessionAuthenticated>());
  });
}
