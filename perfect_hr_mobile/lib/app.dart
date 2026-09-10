import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/analytics/telemetry.dart';
import 'core/data/data_providers.dart';
import 'core/routing/app_router.dart';
import 'core/theme/app_theme.dart';

/// Application root.
///
/// Theme mode follows the system setting. Both light and dark themes are built
/// from the same token set (UI-UX §56), so no screen needs to branch on
/// brightness.
class PerfectHrApp extends ConsumerStatefulWidget {
  const PerfectHrApp({super.key});

  @override
  ConsumerState<PerfectHrApp> createState() => _PerfectHrAppState();
}

class _PerfectHrAppState extends ConsumerState<PerfectHrApp> {
  @override
  void initState() {
    super.initState();
    // Keep the cache lifecycle observer alive for the whole app run. It purges
    // a session's cached data on sign-out and when a different principal signs
    // in on the same device (Instructions §15, §16). Without something holding
    // it, the provider would never be created and cached HR data would survive
    // logout.
    ref.read(cacheLifecycleProvider);
    ref.read(telemetryProvider).track(AnalyticsEvent.appOpened);
  }

  @override
  Widget build(BuildContext context) {
    final router = ref.watch(routerProvider);

    return MaterialApp.router(
      title: 'Perfect HR',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.system,
      routerConfig: router,
      builder: (context, child) {
        // Honour the user's text-scale preference but clamp the upper bound so
        // dense KPI layouts stay legible rather than overflowing
        // (UI-UX §49 — scalable text).
        final mediaQuery = MediaQuery.of(context);
        return MediaQuery(
          data: mediaQuery.copyWith(
            textScaler: mediaQuery.textScaler.clamp(
              minScaleFactor: 0.9,
              maxScaleFactor: 1.6,
            ),
          ),
          child: child ?? const SizedBox.shrink(),
        );
      },
    );
  }
}
