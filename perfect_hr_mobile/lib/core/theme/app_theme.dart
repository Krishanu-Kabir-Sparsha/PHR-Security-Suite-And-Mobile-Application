import 'package:flutter/material.dart';

import 'app_colors.dart';
import 'app_dimensions.dart';
import 'app_typography.dart';

/// Assembles [ThemeData] from Perfect HR design tokens.
///
/// Spec: UI-UX Specification §6 (Design System), §56 (Design Tokens).
/// Instructions §12 — this is the only place component defaults are declared.
abstract final class AppTheme {
  static ThemeData light() => _build(AppPalette.light, Brightness.light);

  static ThemeData dark() => _build(AppPalette.dark, Brightness.dark);

  static ThemeData _build(AppPalette p, Brightness brightness) {
    final colorScheme = ColorScheme(
      brightness: brightness,
      primary: p.brand,
      onPrimary: p.onBrand,
      primaryContainer: p.brandContainer,
      onPrimaryContainer: p.onBrandContainer,
      secondary: p.ai,
      onSecondary: p.onBrand,
      secondaryContainer: p.aiContainer,
      onSecondaryContainer: p.onAiContainer,
      error: p.danger,
      onError: p.onBrand,
      errorContainer: p.dangerContainer,
      onErrorContainer: p.onDangerContainer,
      surface: p.surface,
      onSurface: p.ink,
      surfaceContainerHighest: p.surfaceAlt,
      onSurfaceVariant: p.inkSecondary,
      outline: p.borderStrong,
      outlineVariant: p.border,
      scrim: p.scrim,
    );

    final textTheme = AppTypography.textTheme(p.ink, p.inkSecondary);

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: p.canvas,
      canvasColor: p.canvas,
      textTheme: textTheme,
      fontFamily: AppTypography.fontFamily,
      splashFactory: InkSparkle.splashFactory,
      extensions: <ThemeExtension<dynamic>>[
        p,
        AppTextStyles.of(p.ink, p.inkSecondary),
      ],
      appBarTheme: AppBarTheme(
        backgroundColor: p.canvas,
        surfaceTintColor: Colors.transparent,
        foregroundColor: p.ink,
        elevation: AppElevation.none,
        scrolledUnderElevation: AppElevation.raised,
        centerTitle: false,
        titleTextStyle: AppTypography.heading2.copyWith(color: p.ink),
        iconTheme: IconThemeData(color: p.ink, size: AppSizes.iconMd),
      ),
      cardTheme: CardThemeData(
        color: p.surface,
        surfaceTintColor: Colors.transparent,
        elevation: AppElevation.card,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: AppRadius.cardRadius,
          side: BorderSide(color: p.border),
        ),
      ),
      dividerTheme: DividerThemeData(
        color: p.border,
        thickness: 1,
        space: 1,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: p.brand,
          foregroundColor: p.onBrand,
          disabledBackgroundColor: p.surfaceAlt,
          disabledForegroundColor: p.inkTertiary,
          minimumSize: const Size.fromHeight(AppSizes.buttonHeight),
          textStyle: AppTypography.button,
          shape: const RoundedRectangleBorder(
            borderRadius: AppRadius.controlRadius,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: p.brand,
          minimumSize: const Size.fromHeight(AppSizes.buttonHeight),
          side: BorderSide(color: p.borderStrong),
          textStyle: AppTypography.button,
          shape: const RoundedRectangleBorder(
            borderRadius: AppRadius.controlRadius,
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: p.brand,
          textStyle: AppTypography.button,
          minimumSize: const Size(AppSizes.minTouchTarget, AppSizes.minTouchTarget),
          shape: const RoundedRectangleBorder(
            borderRadius: AppRadius.controlRadius,
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: p.surface,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.md,
        ),
        hintStyle: AppTypography.body.copyWith(color: p.inkTertiary),
        labelStyle: AppTypography.bodySmall.copyWith(color: p.inkSecondary),
        border: OutlineInputBorder(
          borderRadius: AppRadius.controlRadius,
          borderSide: BorderSide(color: p.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: AppRadius.controlRadius,
          borderSide: BorderSide(color: p.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: AppRadius.controlRadius,
          borderSide: BorderSide(color: p.brand, width: 1.6),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: AppRadius.controlRadius,
          borderSide: BorderSide(color: p.danger),
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        height: AppSizes.bottomNavHeight,
        backgroundColor: p.surface,
        surfaceTintColor: Colors.transparent,
        indicatorColor: p.brandContainer,
        elevation: AppElevation.raised,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        iconTheme: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return IconThemeData(
            size: AppSizes.iconMd,
            color: selected ? p.brand : p.inkTertiary,
          );
        }),
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return AppTypography.caption.copyWith(
            color: selected ? p.brand : p.inkTertiary,
            fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
          );
        }),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: p.surface,
        surfaceTintColor: Colors.transparent,
        elevation: AppElevation.sheet,
        modalElevation: AppElevation.sheet,
        shape: const RoundedRectangleBorder(borderRadius: AppRadius.sheetRadius),
        showDragHandle: true,
        dragHandleColor: p.borderStrong,
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: p.surface,
        surfaceTintColor: Colors.transparent,
        elevation: AppElevation.dialog,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
        titleTextStyle: AppTypography.heading2.copyWith(color: p.ink),
        contentTextStyle: AppTypography.body.copyWith(color: p.inkSecondary),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: p.surfaceAlt,
        side: BorderSide(color: p.border),
        labelStyle: AppTypography.bodySmall.copyWith(color: p.inkSecondary),
        shape: const RoundedRectangleBorder(borderRadius: AppRadius.pillRadius),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: p.ink,
        contentTextStyle: AppTypography.body.copyWith(color: p.inkInverse),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
        ),
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(
        color: p.brand,
        linearTrackColor: p.surfaceAlt,
        circularTrackColor: p.surfaceAlt,
      ),
      tabBarTheme: TabBarThemeData(
        labelColor: p.brand,
        unselectedLabelColor: p.inkTertiary,
        labelStyle: AppTypography.bodyStrong,
        unselectedLabelStyle: AppTypography.body,
        indicatorSize: TabBarIndicatorSize.tab,
        dividerColor: p.border,
      ),
      listTileTheme: ListTileThemeData(
        iconColor: p.inkSecondary,
        titleTextStyle: AppTypography.body.copyWith(color: p.ink),
        subtitleTextStyle: AppTypography.caption.copyWith(color: p.inkSecondary),
        minVerticalPadding: AppSpacing.sm,
      ),
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected) ? p.onBrand : p.surface,
        ),
        trackColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected) ? p.brand : p.borderStrong,
        ),
      ),
    );
  }
}
