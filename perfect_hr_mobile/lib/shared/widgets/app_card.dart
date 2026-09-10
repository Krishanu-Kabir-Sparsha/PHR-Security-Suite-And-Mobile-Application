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

  final Color? background;
  final Color? borderColor;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    Widget content = Padding(padding: padding, child: child);

    if (accent != null) {
      content = Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(width: 3, color: accent),
          Expanded(child: content),
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
