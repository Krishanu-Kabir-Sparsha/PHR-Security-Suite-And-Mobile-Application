import 'package:flutter/material.dart';

/// Perfect HR colour tokens.
///
/// Spec: UI-UX Specification §7 (Color System), §56 (Design Tokens).
/// Project Instructions §12 — colours must never be hard-coded at call sites.
/// Access via `Theme.of(context).extension<AppPalette>()!` or the
/// `context.palette` extension in `shared/extensions/theme_context.dart`.
///
/// PROPOSED BRAND PALETTE — pending product-owner approval (Project State Q6).
/// The UI-UX Specification requires "a distinctive Perfect HR brand colour" but
/// does not name one. These values are a proposal, centralised so that a single
/// edit re-skins the entire application.
@immutable
class AppPalette extends ThemeExtension<AppPalette> {
  const AppPalette({
    required this.brand,
    required this.brandStrong,
    required this.brandContainer,
    required this.onBrand,
    required this.onBrandContainer,
    required this.ai,
    required this.aiContainer,
    required this.onAiContainer,
    required this.success,
    required this.successContainer,
    required this.onSuccessContainer,
    required this.warning,
    required this.warningContainer,
    required this.onWarningContainer,
    required this.danger,
    required this.dangerContainer,
    required this.onDangerContainer,
    required this.info,
    required this.infoContainer,
    required this.onInfoContainer,
    required this.canvas,
    required this.surface,
    required this.surfaceAlt,
    required this.border,
    required this.borderStrong,
    required this.ink,
    required this.inkSecondary,
    required this.inkTertiary,
    required this.inkInverse,
    required this.skeletonBase,
    required this.skeletonHighlight,
    required this.scrim,
  });

  /// Primary CTA, active navigation, key actions, selected states.
  final Color brand;
  final Color brandStrong;
  final Color brandContainer;
  final Color onBrand;
  final Color onBrandContainer;

  /// Reserved exclusively for AI-generated content so that AI provenance is
  /// visually unambiguous (UI-UX §51, Instructions §13–14).
  final Color ai;
  final Color aiContainer;
  final Color onAiContainer;

  /// Semantic: Approved, Present, Completed, Healthy.
  final Color success;
  final Color successContainer;
  final Color onSuccessContainer;

  /// Semantic: Pending, Attention Required, Approaching Limit.
  final Color warning;
  final Color warningContainer;
  final Color onWarningContainer;

  /// Semantic: Rejected, Failed, Critical.
  final Color danger;
  final Color dangerContainer;
  final Color onDangerContainer;

  /// Semantic: Insights, Recommendations, Notifications.
  final Color info;
  final Color infoContainer;
  final Color onInfoContainer;

  final Color canvas;
  final Color surface;
  final Color surfaceAlt;
  final Color border;
  final Color borderStrong;
  final Color ink;
  final Color inkSecondary;
  final Color inkTertiary;
  final Color inkInverse;
  final Color skeletonBase;
  final Color skeletonHighlight;
  final Color scrim;

  static const AppPalette light = AppPalette(
    brand: Color(0xFF1B4B8F),
    brandStrong: Color(0xFF143A70),
    brandContainer: Color(0xFFE8EFF9),
    onBrand: Color(0xFFFFFFFF),
    onBrandContainer: Color(0xFF10305E),
    ai: Color(0xFF5B4BD6),
    aiContainer: Color(0xFFF0EEFC),
    onAiContainer: Color(0xFF352A8C),
    success: Color(0xFF1E8E5A),
    successContainer: Color(0xFFE4F4EC),
    onSuccessContainer: Color(0xFF12603C),
    warning: Color(0xFFB07000),
    warningContainer: Color(0xFFFDF1DC),
    onWarningContainer: Color(0xFF7A4E00),
    danger: Color(0xFFC2323B),
    dangerContainer: Color(0xFFFBE9EA),
    onDangerContainer: Color(0xFF8A2129),
    info: Color(0xFF1667C4),
    infoContainer: Color(0xFFE6F0FC),
    onInfoContainer: Color(0xFF0F4A8F),
    canvas: Color(0xFFF6F8FB),
    surface: Color(0xFFFFFFFF),
    surfaceAlt: Color(0xFFF0F3F7),
    border: Color(0xFFE1E6ED),
    borderStrong: Color(0xFFC6CEDA),
    ink: Color(0xFF111827),
    inkSecondary: Color(0xFF475467),
    inkTertiary: Color(0xFF6E7891),
    inkInverse: Color(0xFFFFFFFF),
    skeletonBase: Color(0xFFE8ECF2),
    skeletonHighlight: Color(0xFFF4F6FA),
    scrim: Color(0x66111827),
  );

  static const AppPalette dark = AppPalette(
    brand: Color(0xFF7FA8E5),
    brandStrong: Color(0xFFA6C4F0),
    brandContainer: Color(0xFF16304F),
    onBrand: Color(0xFF0A1B31),
    onBrandContainer: Color(0xFFD3E2F7),
    ai: Color(0xFF9B8FF0),
    aiContainer: Color(0xFF241F4A),
    onAiContainer: Color(0xFFDCD6FB),
    success: Color(0xFF5FC292),
    successContainer: Color(0xFF113527),
    onSuccessContainer: Color(0xFFC5E9D6),
    warning: Color(0xFFE0A73F),
    warningContainer: Color(0xFF3A2A08),
    onWarningContainer: Color(0xFFF6DFB4),
    danger: Color(0xFFE98A90),
    dangerContainer: Color(0xFF421619),
    onDangerContainer: Color(0xFFF8D2D5),
    info: Color(0xFF6FA8E8),
    infoContainer: Color(0xFF11294A),
    onInfoContainer: Color(0xFFCFE1F8),
    canvas: Color(0xFF0E1218),
    surface: Color(0xFF161B23),
    surfaceAlt: Color(0xFF1E242E),
    border: Color(0xFF2A313D),
    borderStrong: Color(0xFF3D4553),
    ink: Color(0xFFF2F4F7),
    inkSecondary: Color(0xFFB0B8C6),
    inkTertiary: Color(0xFF8A93A3),
    inkInverse: Color(0xFF111827),
    skeletonBase: Color(0xFF232A34),
    skeletonHighlight: Color(0xFF2D3542),
    scrim: Color(0x99000000),
  );

  @override
  AppPalette copyWith({
    Color? brand,
    Color? brandStrong,
    Color? brandContainer,
    Color? onBrand,
    Color? onBrandContainer,
    Color? ai,
    Color? aiContainer,
    Color? onAiContainer,
    Color? success,
    Color? successContainer,
    Color? onSuccessContainer,
    Color? warning,
    Color? warningContainer,
    Color? onWarningContainer,
    Color? danger,
    Color? dangerContainer,
    Color? onDangerContainer,
    Color? info,
    Color? infoContainer,
    Color? onInfoContainer,
    Color? canvas,
    Color? surface,
    Color? surfaceAlt,
    Color? border,
    Color? borderStrong,
    Color? ink,
    Color? inkSecondary,
    Color? inkTertiary,
    Color? inkInverse,
    Color? skeletonBase,
    Color? skeletonHighlight,
    Color? scrim,
  }) {
    return AppPalette(
      brand: brand ?? this.brand,
      brandStrong: brandStrong ?? this.brandStrong,
      brandContainer: brandContainer ?? this.brandContainer,
      onBrand: onBrand ?? this.onBrand,
      onBrandContainer: onBrandContainer ?? this.onBrandContainer,
      ai: ai ?? this.ai,
      aiContainer: aiContainer ?? this.aiContainer,
      onAiContainer: onAiContainer ?? this.onAiContainer,
      success: success ?? this.success,
      successContainer: successContainer ?? this.successContainer,
      onSuccessContainer: onSuccessContainer ?? this.onSuccessContainer,
      warning: warning ?? this.warning,
      warningContainer: warningContainer ?? this.warningContainer,
      onWarningContainer: onWarningContainer ?? this.onWarningContainer,
      danger: danger ?? this.danger,
      dangerContainer: dangerContainer ?? this.dangerContainer,
      onDangerContainer: onDangerContainer ?? this.onDangerContainer,
      info: info ?? this.info,
      infoContainer: infoContainer ?? this.infoContainer,
      onInfoContainer: onInfoContainer ?? this.onInfoContainer,
      canvas: canvas ?? this.canvas,
      surface: surface ?? this.surface,
      surfaceAlt: surfaceAlt ?? this.surfaceAlt,
      border: border ?? this.border,
      borderStrong: borderStrong ?? this.borderStrong,
      ink: ink ?? this.ink,
      inkSecondary: inkSecondary ?? this.inkSecondary,
      inkTertiary: inkTertiary ?? this.inkTertiary,
      inkInverse: inkInverse ?? this.inkInverse,
      skeletonBase: skeletonBase ?? this.skeletonBase,
      skeletonHighlight: skeletonHighlight ?? this.skeletonHighlight,
      scrim: scrim ?? this.scrim,
    );
  }

  @override
  AppPalette lerp(ThemeExtension<AppPalette>? other, double t) {
    if (other is! AppPalette) return this;
    Color l(Color a, Color b) => Color.lerp(a, b, t)!;
    return AppPalette(
      brand: l(brand, other.brand),
      brandStrong: l(brandStrong, other.brandStrong),
      brandContainer: l(brandContainer, other.brandContainer),
      onBrand: l(onBrand, other.onBrand),
      onBrandContainer: l(onBrandContainer, other.onBrandContainer),
      ai: l(ai, other.ai),
      aiContainer: l(aiContainer, other.aiContainer),
      onAiContainer: l(onAiContainer, other.onAiContainer),
      success: l(success, other.success),
      successContainer: l(successContainer, other.successContainer),
      onSuccessContainer: l(onSuccessContainer, other.onSuccessContainer),
      warning: l(warning, other.warning),
      warningContainer: l(warningContainer, other.warningContainer),
      onWarningContainer: l(onWarningContainer, other.onWarningContainer),
      danger: l(danger, other.danger),
      dangerContainer: l(dangerContainer, other.dangerContainer),
      onDangerContainer: l(onDangerContainer, other.onDangerContainer),
      info: l(info, other.info),
      infoContainer: l(infoContainer, other.infoContainer),
      onInfoContainer: l(onInfoContainer, other.onInfoContainer),
      canvas: l(canvas, other.canvas),
      surface: l(surface, other.surface),
      surfaceAlt: l(surfaceAlt, other.surfaceAlt),
      border: l(border, other.border),
      borderStrong: l(borderStrong, other.borderStrong),
      ink: l(ink, other.ink),
      inkSecondary: l(inkSecondary, other.inkSecondary),
      inkTertiary: l(inkTertiary, other.inkTertiary),
      inkInverse: l(inkInverse, other.inkInverse),
      skeletonBase: l(skeletonBase, other.skeletonBase),
      skeletonHighlight: l(skeletonHighlight, other.skeletonHighlight),
      scrim: l(scrim, other.scrim),
    );
  }
}
