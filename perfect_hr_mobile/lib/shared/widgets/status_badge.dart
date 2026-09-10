import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimensions.dart';
import '../extensions/theme_context.dart';

/// Semantic status, mapped to the tokens in UI-UX Specification §7.
enum AppStatus {
  /// Approved, Present, Completed, Healthy.
  success,

  /// Pending, Attention Required, Approaching Limit.
  warning,

  /// Rejected, Failed, Critical.
  danger,

  /// Insight, Recommendation, Notification.
  info,

  /// No semantic weight.
  neutral;

  Color foreground(AppPalette p) => switch (this) {
        AppStatus.success => p.onSuccessContainer,
        AppStatus.warning => p.onWarningContainer,
        AppStatus.danger => p.onDangerContainer,
        AppStatus.info => p.onInfoContainer,
        AppStatus.neutral => p.inkSecondary,
      };

  Color background(AppPalette p) => switch (this) {
        AppStatus.success => p.successContainer,
        AppStatus.warning => p.warningContainer,
        AppStatus.danger => p.dangerContainer,
        AppStatus.info => p.infoContainer,
        AppStatus.neutral => p.surfaceAlt,
      };

  Color accent(AppPalette p) => switch (this) {
        AppStatus.success => p.success,
        AppStatus.warning => p.warning,
        AppStatus.danger => p.danger,
        AppStatus.info => p.info,
        AppStatus.neutral => p.inkTertiary,
      };

  /// Shape carried alongside colour so status is never colour-only
  /// (UI-UX §49, Instructions §26). Mirrors the Blueprint E-04 legend:
  /// ● Present  ◐ Late  ○ Absent  ◇ Leave
  IconData get glyph => switch (this) {
        AppStatus.success => Icons.circle,
        AppStatus.warning => Icons.change_history,
        AppStatus.danger => Icons.square,
        AppStatus.info => Icons.auto_awesome,
        AppStatus.neutral => Icons.circle_outlined,
      };
}

/// Compact status pill. Always pairs a glyph with the colour.
class StatusBadge extends StatelessWidget {
  const StatusBadge({
    required this.label,
    required this.status,
    this.showGlyph = true,
    super.key,
  });

  final String label;
  final AppStatus status;
  final bool showGlyph;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.xs,
        vertical: AppSpacing.xxs,
      ),
      decoration: BoxDecoration(
        color: status.background(palette),
        borderRadius: AppRadius.pillRadius,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (showGlyph) ...[
            Icon(status.glyph, size: 9, color: status.accent(palette)),
            const SizedBox(width: AppSpacing.xxs + 2),
          ],
          Text(
            label,
            style: context.text.bodySmall?.copyWith(
              color: status.foreground(palette),
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

/// Directional change indicator, e.g. "↑ 4.2%".
///
/// [isPositiveGood] must be set deliberately: rising attrition is bad while
/// rising productivity is good, and the colour has to follow the meaning
/// rather than the arrow direction.
class TrendIndicator extends StatelessWidget {
  const TrendIndicator({
    required this.delta,
    required this.isPositiveGood,
    this.suffix = '%',
    super.key,
  });

  final double delta;
  final bool isPositiveGood;
  final String suffix;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final rising = delta > 0;
    final flat = delta == 0;
    final good = flat ? null : (rising == isPositiveGood);

    final color = switch (good) {
      null => palette.inkTertiary,
      true => palette.success,
      false => palette.danger,
    };

    final icon = flat
        ? Icons.remove
        : rising
            ? Icons.arrow_upward
            : Icons.arrow_downward;

    final direction = flat ? 'unchanged' : (rising ? 'up' : 'down');
    final magnitude = '${delta.abs().toStringAsFixed(1)}$suffix';

    return Semantics(
      label: flat ? 'Unchanged' : '$direction $magnitude',
      excludeSemantics: true,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: color),
          const SizedBox(width: 2),
          Text(
            magnitude,
            style: context.text.bodySmall
                ?.copyWith(color: color, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}
