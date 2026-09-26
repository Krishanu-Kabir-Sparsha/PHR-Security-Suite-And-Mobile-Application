import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/config/app_config.dart';
import 'core/networking/auth_interceptor.dart';
import 'core/networking/connectivity_service.dart';
import 'core/tenant/tenant_providers.dart';
import 'features/authentication/application/auth_providers.dart';

/// Entry point.
///
/// Flavour is injected at build time (Tech-Stack §25):
///   flutter run --dart-define=FLAVOR=dev
///   flutter build apk --dart-define=FLAVOR=prod
///
/// Later tasks add here: FCM registration (Task 8) and Crashlytics
/// initialisation (pending the Firebase project files — Project State Q9).
///
/// **Start-up must always reach `runApp`.** Anything that throws or hangs
/// before it produces a black screen with no message and nothing to act on --
/// which is exactly what a provider cycle in an earlier build did. So every
/// step below is individually guarded, the one that touches platform storage
/// is time-boxed, and a total failure still renders something a person can
/// read and report.
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  try {
    AppConfig.initialise();

    // The real token store replaces Task 2's UnauthenticatedTokenStore, which
    // is what makes the auth interceptor start attaching bearer tokens. Done as
    // an override rather than by editing the provider so the networking layer
    // keeps no dependency on the authentication feature.
    final container = ProviderContainer(
      overrides: [
        authTokenStoreProvider.overrideWith(
          (ref) => ref.watch(secureTokenStoreProvider),
        ),
      ],
    );

    // Resolve connectivity before the first frame so the initial render
    // reflects real network state rather than the optimistic default. Failure
    // is not fatal: `status` stays optimistic and the first request reports
    // the truth.
    final connectivity = container.read(connectivityServiceProvider);
    if (connectivity is PlatformConnectivityService) {
      try {
        await connectivity.initialise().timeout(const Duration(seconds: 5));
      } catch (_) {
        // Start-up must not depend on the connectivity plugin.
      }
    }

    // The workspace comes back FIRST, and the order is load-bearing rather
    // than tidy. Every API client's base URL is derived from it, so restoring
    // the session before the workspace would build a Dio with an empty base
    // URL and then try to refresh a token against nowhere.
    //
    // Time-boxed for the same reason as the session below.
    try {
      await container
          .read(tenantControllerProvider.notifier)
          .restore()
          .timeout(const Duration(seconds: 5));
    } catch (_) {
      // No remembered workspace is a normal state, not a failure: the sign-in
      // screen asks for one.
    }

    // Restore a stored session, so a returning user is not shown the sign-in
    // screen on every cold start.
    //
    // Time-boxed deliberately. This reaches the platform keystore, and on some
    // devices that call can be slow or simply never return; without a deadline
    // the app would hang here forever, before the first frame, showing black.
    // Signing in again is a far better outcome than an app that will not open.
    try {
      await container
          .read(sessionRestoreProvider.future)
          .timeout(const Duration(seconds: 8));
    } catch (_) {
      // Never block start-up on session restore.
    }

    runApp(
      UncontrolledProviderScope(
        container: container,
        child: const PerfectHrApp(),
      ),
    );
  } catch (error, stack) {
    // Last resort. Something in start-up failed in a way we did not anticipate,
    // and the alternative to this screen is a black one.
    debugPrint('Perfect HR failed to start: $error\n$stack');
    runApp(_StartupFailureApp(error: error));
  }
}

/// Shown only when start-up itself failed.
///
/// Deliberately depends on nothing: no theme, no providers, no localisation.
/// Whatever broke may be any of those.
class _StartupFailureApp extends StatelessWidget {
  const _StartupFailureApp({required this.error});

  final Object error;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      home: Scaffold(
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.error_outline, size: 48),
                const SizedBox(height: 16),
                const Text(
                  'Perfect HR could not start',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Please close the app and open it again. If this keeps '
                  'happening, show this screen to your IT team.',
                ),
                const SizedBox(height: 24),
                // The technical detail is shown here and nowhere else. This
                // screen only ever appears when the app is unusable, so there
                // is no working state for it to leak into, and without it a
                // report is just "it does not open".
                Expanded(
                  child: SingleChildScrollView(
                    child: Text(
                      '$error',
                      style: const TextStyle(fontSize: 12, height: 1.4),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
