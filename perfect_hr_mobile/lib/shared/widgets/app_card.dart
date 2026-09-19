import 'package:flutter/material.dart';

import '../../core/theme/app_dimensions.dart';
import '../extensions/theme_context.dart';

/// Base surface for all Perfect HR content blocks.
///
/// Spec: UI-UX Specification §6.1, §9. Bordered, low-elevation surfaces keep
/// the interface calm rather than dashboard-heavy.
class AppCard extends StatelessWidget {
  const AppCard({
    required this.child,
    this.padding = AppSpacing.card,
    this.onTap,
    this.accent,
    this.background,
    this.borderColor,
    this.semanticLabel,
    super.key,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;

  /// Optional 3px leading accent bar, used to carry semantic meaning
  /// (e.g. risk level) without relying on colour alone elsewhere.
  final Color? accent;

  /// Width of the leading accent bar, and of the inset that keeps content
  /// clear of it. One constant so the two can never drift apart.
  static const double _accentWidth = 3;

  final Color? background;
  final Color? borderColor;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    Widget content = Padding(padding: padding, child: child);

    if (accent != null) {
      // The accent bar is drawn as a Stack overlay rather than a Row child.
      //
      // The previous form was a Row with CrossAxisAlignment.stretch, which asks
      // every child to fill the Row's cross-axis extent. Inside a scrollable
      // the Row's height is unbounded, so that extent is infinity and layout
      // died with "BoxConstraints forces an infinite height". It only showed up
      // in the AI card tests, where the card is rendered without a bounding
      // height, and the failure then cascaded into thousands of misleading
      // semantics assertions.
      //
      // A left BorderSide on the DecoratedBox below would be tidier still, but
      // Flutter forbids a non-uniform Border together with a borderRadius, and
      // the rounded corner is part of the spec (UI-UX 6.1).
      //
      // The Stack takes its size from `content`, the only non-positioned child,
      // so nothing is unbounded. The padding keeps the 3px inset the Row's
      // Expanded used to provide, so text does not slide under the bar.
      content = Stack(
        children: [
          Padding(
            padding: const EdgeInsets.only(left: _accentWidth),
            child: content,
          ),
          Positioned(
            left: 0,
            top: 0,
            bottom: 0,
            width: _accentWidth,
            child: ColoredBox(color: accent!),
          ),
        ],
      );
    }

    final card = DecoratedBox(
      decoration: BoxDecoration(
        color: background ?? palette.surface,
        borderRadius: AppRadius.cardRadius,
        border: Border.all(color: borderColor ?? palette.border),
      ),
      child: ClipRRect(
        borderRadius: AppRadius.cardRadius,
        child: onTap == null
            ? content
            : Material(
                color: Colors.transparent,
                child: InkWell(onTap: onTap, child: content),
              ),
      ),
    );

    if (semanticLabel == null) return card;
    return Semantics(
      label: semanticLabel,
      button: onTap != null,
      container: true,
      child: card,
    );
  }
}

/// Uppercase section label above a group of cards, e.g. "TODAY".
class AppSectionHeader extends StatelessWidget {
  const AppSectionHeader({
    required this.title,
    this.actionLabel,
    this.onAction,
    super.key,
  });

  final String title;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xs),
      child: Row(
        children: [
          Expanded(
            child: Semantics(
              header: true,
              child: Text(title.toUpperCase(), style: context.styles.overline),
            ),
          ),
          if (actionLabel != null && onAction != null)
            TextButton(
              onPressed: onAction,
              style: TextButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs),
                minimumSize: const Size(0, AppSizes.minTouchTarget),
              ),
              child: Text(actionLabel!),
            ),
        ],
      ),
    );
  }
}
