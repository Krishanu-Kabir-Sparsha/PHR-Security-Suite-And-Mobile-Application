import 'package:flutter/widgets.dart';

/// Motion tokens — UI-UX Specification §50 (Microinteraction Guidelines).
///
/// Animations must remain restrained and professional. All durations are
/// routed through here so that a reduced-motion preference can be honoured
/// globally (Instructions §26).
abstract final class AppMotion {
  static const Duration instant = Duration(milliseconds: 80);
  static const Duration fast = Duration(milliseconds: 150);
  static const Duration normal = Duration(milliseconds: 240);
  static const Duration slow = Duration(milliseconds: 400);

  /// Skeleton shimmer cycle.
  static const Duration shimmer = Duration(milliseconds: 1200);

  static const Curve standard = Curves.easeOutCubic;
  static const Curve emphasised = Curves.easeOutQuart;
  static const Curve exit = Curves.easeInCubic;

  /// Returns [duration], or [Duration.zero] when the platform requests
  /// reduced motion. Call sites should prefer this over raw tokens.
  static Duration respecting(BuildContext context, Duration duration) {
    final reduce = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    return reduce ? Duration.zero : duration;
  }
}
