import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Re-reads time-sensitive data when the app comes back to the foreground.
///
/// ## Why this is needed
///
/// Attendance is the one thing in this app that two clients change
/// independently: somebody checks in at the office kiosk, or on the web
/// dashboard, or on a biometric terminal, and the phone in their pocket knows
/// nothing about it. Cached responses made that worse — the home summary is
/// held for two minutes, so a phone reopened straight after a web check-in
/// showed "not checked in" and invited a second punch, which Odoo's overlap
/// constraint then refused.
///
/// Before this existed the app had **no `AppLifecycleState` handling at all**.
/// It refetched on a pull-to-refresh and on nothing else, so the staleness
/// lasted until somebody thought to swipe.
///
/// ## Why the foreground, and not a poll
///
/// A timer runs while the phone is in a pocket, on a network the user is
/// paying for, to answer a question nobody is asking. Coming back to the
/// foreground is the exact moment somebody wants to know, and it is free.
///
/// ## What it deliberately does not do
///
/// It does not refresh everything. Payslips and the role catalog do not change
/// while a phone is locked, and re-reading them on every glance would cost
/// battery and data for nothing. Only what can change behind the app's back is
/// listed by the caller.
class ForegroundRefresh extends StatefulWidget {
  const ForegroundRefresh({
    super.key,
    required this.child,
    required this.onResume,
    this.minimumInterval = const Duration(seconds: 20),
  });

  final Widget child;

  /// Called when the app returns to the foreground, no more often than
  /// [minimumInterval].
  final Future<void> Function() onResume;

  /// Floor between refreshes.
  ///
  /// Android delivers `resumed` for things that are not really a return to the
  /// app — a permission dialog dismissing, a biometric prompt closing, the
  /// notification shade being pulled down and released. Without a floor, the
  /// fingerprint prompt during sign-in would itself trigger a refresh storm.
  final Duration minimumInterval;

  @override
  State<ForegroundRefresh> createState() => _ForegroundRefreshState();
}

class _ForegroundRefreshState extends State<ForegroundRefresh>
    with WidgetsBindingObserver {
  DateTime? _lastRefresh;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) return;

    final last = _lastRefresh;
    final now = DateTime.now();
    if (last != null && now.difference(last) < widget.minimumInterval) return;
    _lastRefresh = now;

    // Failures are swallowed on purpose. This runs because the user opened the
    // app, not because they asked for a refresh, so an error banner here would
    // be the app apologising for something nobody requested. The screen's own
    // load path reports its own failures.
    widget.onResume().catchError((Object _) {});
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// [ForegroundRefresh] wired to the providers that go stale behind the app.
///
/// Wrapped around the authenticated shell rather than around each screen, so
/// one observer serves the whole app and the refresh happens once per return
/// rather than once per mounted screen.
class AttendanceForegroundRefresh extends ConsumerWidget {
  const AttendanceForegroundRefresh({
    super.key,
    required this.child,
    required this.refresh,
  });

  final Widget child;

  /// Supplied by the caller so this file depends on no feature.
  final Future<void> Function(WidgetRef ref) refresh;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ForegroundRefresh(
      onResume: () => refresh(ref),
      child: child,
    );
  }
}
