import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_typography.dart';

/// Terse, safe access to Perfect HR design tokens from a [BuildContext].
///
/// Instructions §12 — call sites read tokens, never literals.
extension ThemeContextX on BuildContext {
  ThemeData get theme => Theme.of(this);

  /// Perfect HR semantic colour tokens.
  AppPalette get palette =>
      Theme.of(this).extension<AppPalette>() ?? AppPalette.light;

  /// Perfect HR type slots with no Material equivalent (KPI, overline).
  AppTextStyles get styles =>
      Theme.of(this).extension<AppTextStyles>() ??
      AppTextStyles.of(AppPalette.light.ink, AppPalette.light.inkSecondary);

  TextTheme get text => Theme.of(this).textTheme;

  bool get isDark => Theme.of(this).brightness == Brightness.dark;

  double get screenWidth => MediaQuery.sizeOf(this).width;
}
