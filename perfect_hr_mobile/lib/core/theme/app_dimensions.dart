import 'package:flutter/widgets.dart';

/// Spacing scale — UI-UX Specification §9.
///
/// Cards and sections must breathe; the interface must never read as an
/// exported ERP report. Never hard-code an EdgeInsets value at a call site.
abstract final class AppSpacing {
  static const double xxs = 4;
  static const double xs = 8;
  static const double sm = 12;
  static const double md = 16;
  static const double lg = 24;
  static const double xl = 32;
  static const double xxl = 48;
  static const double xxxl = 64;

  /// Standard horizontal page gutter.
  static const EdgeInsets pageHorizontal = EdgeInsets.symmetric(horizontal: md);

  /// Standard page padding for scrollable content.
  static const EdgeInsets page =
      EdgeInsets.symmetric(horizontal: md, vertical: lg);

  /// Internal padding for a standard card.
  static const EdgeInsets card = EdgeInsets.all(md);

  /// Bottom padding that clears the bottom navigation bar.
  static const EdgeInsets bottomNavClearance = EdgeInsets.only(bottom: xxl + md);
}

/// Corner radius tokens.
abstract final class AppRadius {
  static const double xs = 6;
  static const double sm = 10;
  static const double md = 14;
  static const double lg = 20;
  static const double pill = 999;

  static const BorderRadius cardRadius = BorderRadius.all(Radius.circular(md));
  static const BorderRadius controlRadius =
      BorderRadius.all(Radius.circular(sm));
  static const BorderRadius sheetRadius = BorderRadius.vertical(
    top: Radius.circular(lg),
  );
  static const BorderRadius pillRadius =
      BorderRadius.all(Radius.circular(pill));
}

/// Elevation tokens. Perfect HR uses borders and low elevation in preference
/// to heavy shadows (UI-UX §6.1 — calm, professional, not dashboard-heavy).
abstract final class AppElevation {
  static const double none = 0;
  static const double card = 0;
  static const double raised = 1;
  static const double sheet = 3;
  static const double dialog = 6;
}

/// Minimum interactive sizes — UI-UX §49, Instructions §26 (accessibility).
abstract final class AppSizes {
  /// Minimum touch target on both platforms.
  static const double minTouchTarget = 48;
  static const double buttonHeight = 52;
  static const double inputHeight = 52;
  static const double avatarSm = 32;
  static const double avatarMd = 44;
  static const double avatarLg = 72;
  static const double iconSm = 18;
  static const double iconMd = 22;
  static const double iconLg = 28;
  static const double bottomNavHeight = 68;
}

/// Responsive breakpoints — UI-UX §56, Screen Blueprint §75.
/// The design must not depend on a single device resolution.
abstract final class AppBreakpoints {
  /// Small phones (e.g. iPhone SE class).
  static const double compact = 360;

  /// Standard phones.
  static const double medium = 400;

  /// Large phones / unfolded foldables / small tablets.
  static const double expanded = 600;

  static bool isCompact(double width) => width < medium;
  static bool isExpanded(double width) => width >= expanded;
}
