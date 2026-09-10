import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/config/app_config.dart';
import 'core/networking/connectivity_service.dart';

/// Entry point.
///
/// Flavour is injected at build time (Tech-Stack §25):
///   flutter run --dart-define=FLAVOR=dev
///   flutter build apk --dart-define=FLAVOR=prod
///
/// Later tasks add here: secure storage warm-up and token restore (Task 3),
/// FCM registration (Task 8), Crashlytics initialisation (pending the Firebase
/// project files — Project State Q9).
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  AppConfig.initialise();

  final container = ProviderContainer();

  // Resolve connectivity before the first frame so the initial render reflects
  // real network state rather than the optimistic default. Failure here is not
  // fatal: `status` stays optimistic and the first request reports the truth.
  final connectivity = container.read(connectivityServiceProvider);
  if (connectivity is PlatformConnectivityService) {
    try {
      await connectivity.initialise();
    } catch (_) {
      // Start-up must not depend on the connectivity plugin.
    }
  }

  runApp(
    UncontrolledProviderScope(
      container: container,
      child: const PerfectHrApp(),
    ),
  );
}
