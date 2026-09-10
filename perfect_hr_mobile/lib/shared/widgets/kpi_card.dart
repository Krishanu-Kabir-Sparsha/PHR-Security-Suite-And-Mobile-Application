import 'package:flutter/material.dart';

import '../../core/theme/app_dimensions.dart';
import '../extensions/theme_context.dart';
import 'app_card.dart';
import 'status_badge.dart';

/// A single KPI with optional trend and drill-down.
///
/// Spec: UI-UX Specification §8 (KPI type slot), §53 (dashboard rule: 3–5 KPIs),
/// Screen & Wireframe Blueprint §67 (KPI → Drill Down). Every major KPI should
/// be interactive, so [onTap] is expected rather than optional in practice.
class KpiCard extends StatelessWidget {
  const KpiCard({
    required this.label,
    required this.value,
    this.unit,
    this.delta,
    this.isPositiveGood = true,
    this.status,
    this.onTap,
    this.compact = false,
    super.key,
  });

  final String label;

  /// Pre-formatted value, e.g. "1,248", "8.2%", "৳ 42,500".
  /// Formatting belongs to the feature layer, not this widget.
  final String value;

  final String? unit;

  /// Period-over-period change. Null hides the trend indicator.
  final double? delta;

  /// Whether an increase in this metric is desirable.
  final bool isPositiveGood;

  /// Optional semantic tint for the value (e.g. danger for critical attrition).
  final AppStatus? status;

  final VoidCallback? onTap;

  /// Compact variant for a two- or three-across grid.
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final valueColor =
        status == null ? palette.ink : status!.accent(palette);

    return AppCard(
      onTap: onTap,
      padding: EdgeInsets.all(compact ? AppSpacing.sm : AppSpacing.md),
      semanticLabel: [
        label,
        value,
        if (unit != null) unit!,
      ].join(' '),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  label.toUpperCase(),
                  style: context.styles.overline,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (onTap != null)
                Icon(
                  Icons.chevron_right,
                  size: AppSizes.iconSm,
                  color: palette.inkTertiary,
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Flexible(
                child: Text(
                  value,
                  style: (compact
                          ? context.styles.kpiSmall
                          : context.styles.kpi)
                      .copyWith(color: valueColor),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (unit != null) ...[
                const SizedBox(width: AppSpacing.xxs),
                Text(unit!, style: context.text.bodySmall),
              ],
            ],
          ),
          if (delta != null) ...[
            const SizedBox(height: AppSpacing.xxs),
            TrendIndicator(delta: delta!, isPositiveGood: isPositiveGood),
          ],
        ],
      ),
    );
  }
}

/// Responsive KPI grid honouring the 3–5 KPI dashboard rule (UI-UX §53).
///
/// Widens to three columns on large phones and unfolded foldables rather than
/// assuming a single device resolution (Blueprint §75).
class KpiGrid extends StatelessWidget {
  const KpiGrid({required this.children, this.spacing = AppSpacing.sm, super.key});

  final List<Widget> children;
  final double spacing;

  @override
  Widget build(BuildContext context) {
    final columns = AppBreakpoints.isExpanded(context.screenWidth) ? 3 : 2;

    return LayoutBuilder(
      builder: (context, constraints) {
        final itemWidth =
            (constraints.maxWidth - spacing * (columns - 1)) / columns;
        return Wrap(
          spacing: spacing,
          runSpacing: spacing,
          children: [
            for (final child in children)
              SizedBox(width: itemWidth, child: child),
          ],
        );
      },
    );
  }
}

/// Labelled progress bar, e.g. goal completion or role readiness.
/// Always states the numeric value so progress is not conveyed by width alone.
class AppProgressBar extends StatelessWidget {
  const AppProgressBar({
    required this.value,
    this.label,
    this.showPercentage = true,
    super.key,
  }) : assert(value >= 0 && value <= 1, 'value must be a 0..1 fraction');

  final double value;
  final String? label;
  final bool showPercentage;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final percentage = '${(value * 100).round()}%';

    return Semantics(
      label: label == null ? percentage : '$label, $percentage',
      excludeSemantics: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (label != null || showPercentage)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xxs),
              child: Row(
                children: [
                  if (label != null)
                    Expanded(child: Text(label!, style: context.text.bodySmall)),
                  if (showPercentage)
                    Text(percentage, style: context.styles.bodyStrong),
                ],
              ),
            ),
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadius.pill),
            child: LinearProgressIndicator(
              value: value,
              minHeight: 8,
              backgroundColor: palette.surfaceAlt,
              valueColor: AlwaysStoppedAnimation(palette.brand),
            ),
          ),
        ],
      ),
    );
  }
}
