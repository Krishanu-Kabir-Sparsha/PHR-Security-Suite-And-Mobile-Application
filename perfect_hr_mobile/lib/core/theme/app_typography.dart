import 'package:flutter/material.dart';

/// Typography tokens — UI-UX Specification §8.
///
/// Hierarchy: Display / Heading 1 / Heading 2 / Heading 3 / Body / Caption /
/// KPI. Readability is prioritised over decorative styling.
///
/// FONT: Perfect HR has no declared typeface (Project State Q6). Until a brand
/// font is licensed and added to `pubspec.yaml` assets, [fontFamily] stays
/// null so the platform default is used (Roboto on Android, SF on iOS), which
/// is a safe, highly legible fallback. Setting [fontFamily] here is the only
/// change required to adopt a brand font application-wide.
abstract final class AppTypography {
  static const String? fontFamily = null;

  static const TextStyle _base = TextStyle(
    fontFamily: fontFamily,
    letterSpacing: 0,
    height: 1.4,
  );

  /// Major dashboard KPI or executive insight headline.
  static final TextStyle display = _base.copyWith(
    fontSize: 30,
    fontWeight: FontWeight.w700,
    height: 1.2,
    letterSpacing: -0.4,
  );

  /// Page title.
  static final TextStyle heading1 = _base.copyWith(
    fontSize: 22,
    fontWeight: FontWeight.w700,
    height: 1.25,
    letterSpacing: -0.2,
  );

  /// Section title.
  static final TextStyle heading2 = _base.copyWith(
    fontSize: 18,
    fontWeight: FontWeight.w600,
    height: 1.3,
  );

  /// Card title.
  static final TextStyle heading3 = _base.copyWith(
    fontSize: 16,
    fontWeight: FontWeight.w600,
    height: 1.35,
  );

  /// Primary information.
  static final TextStyle body = _base.copyWith(
    fontSize: 15,
    fontWeight: FontWeight.w400,
  );

  static final TextStyle bodyStrong = body.copyWith(
    fontWeight: FontWeight.w600,
  );

  static final TextStyle bodySmall = _base.copyWith(
    fontSize: 13.5,
    fontWeight: FontWeight.w400,
  );

  /// Supporting information.
  static final TextStyle caption = _base.copyWith(
    fontSize: 12.5,
    fontWeight: FontWeight.w400,
    height: 1.35,
  );

  /// Uppercase section label, e.g. "TODAY", "QUICK ACTIONS".
  static final TextStyle overline = _base.copyWith(
    fontSize: 11.5,
    fontWeight: FontWeight.w700,
    letterSpacing: 0.8,
    height: 1.2,
  );

  /// Large numeric value, e.g. "1,248", "94.2%".
  static final TextStyle kpi = _base.copyWith(
    fontSize: 28,
    fontWeight: FontWeight.w700,
    height: 1.1,
    letterSpacing: -0.6,
    fontFeatures: const [FontFeature.tabularFigures()],
  );

  /// Hero numeric value used on executive and attendance screens.
  static final TextStyle kpiLarge = kpi.copyWith(fontSize: 40);

  /// Compact numeric value inside a KPI card grid.
  static final TextStyle kpiSmall = kpi.copyWith(fontSize: 20);

  static final TextStyle button = _base.copyWith(
    fontSize: 15.5,
    fontWeight: FontWeight.w600,
    height: 1.1,
    letterSpacing: 0.1,
  );

  /// Maps the Perfect HR scale onto Material's [TextTheme] so that stock
  /// widgets inherit the correct styling.
  static TextTheme textTheme(Color ink, Color inkSecondary) {
    return TextTheme(
      displaySmall: display.copyWith(color: ink),
      headlineSmall: heading1.copyWith(color: ink),
      titleLarge: heading2.copyWith(color: ink),
      titleMedium: heading3.copyWith(color: ink),
      bodyLarge: body.copyWith(color: ink),
      bodyMedium: body.copyWith(color: ink),
      bodySmall: caption.copyWith(color: inkSecondary),
      labelLarge: button.copyWith(color: ink),
      labelMedium: bodySmall.copyWith(color: inkSecondary),
      labelSmall: overline.copyWith(color: inkSecondary),
    );
  }
}

/// Perfect HR type slots that have no Material equivalent.
@immutable
class AppTextStyles extends ThemeExtension<AppTextStyles> {
  const AppTextStyles({
    required this.kpi,
    required this.kpiLarge,
    required this.kpiSmall,
    required this.overline,
    required this.bodyStrong,
  });

  final TextStyle kpi;
  final TextStyle kpiLarge;
  final TextStyle kpiSmall;
  final TextStyle overline;
  final TextStyle bodyStrong;

  factory AppTextStyles.of(Color ink, Color inkSecondary) => AppTextStyles(
        kpi: AppTypography.kpi.copyWith(color: ink),
        kpiLarge: AppTypography.kpiLarge.copyWith(color: ink),
        kpiSmall: AppTypography.kpiSmall.copyWith(color: ink),
        overline: AppTypography.overline.copyWith(color: inkSecondary),
        bodyStrong: AppTypography.bodyStrong.copyWith(color: ink),
      );

  @override
  AppTextStyles copyWith({
    TextStyle? kpi,
    TextStyle? kpiLarge,
    TextStyle? kpiSmall,
    TextStyle? overline,
    TextStyle? bodyStrong,
  }) {
    return AppTextStyles(
      kpi: kpi ?? this.kpi,
      kpiLarge: kpiLarge ?? this.kpiLarge,
      kpiSmall: kpiSmall ?? this.kpiSmall,
      overline: overline ?? this.overline,
      bodyStrong: bodyStrong ?? this.bodyStrong,
    );
  }

  @override
  AppTextStyles lerp(ThemeExtension<AppTextStyles>? other, double t) {
    if (other is! AppTextStyles) return this;
    return AppTextStyles(
      kpi: TextStyle.lerp(kpi, other.kpi, t)!,
      kpiLarge: TextStyle.lerp(kpiLarge, other.kpiLarge, t)!,
      kpiSmall: TextStyle.lerp(kpiSmall, other.kpiSmall, t)!,
      overline: TextStyle.lerp(overline, other.overline, t)!,
      bodyStrong: TextStyle.lerp(bodyStrong, other.bodyStrong, t)!,
    );
  }
}
