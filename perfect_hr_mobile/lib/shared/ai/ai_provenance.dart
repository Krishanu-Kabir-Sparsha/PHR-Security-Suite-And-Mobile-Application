import 'package:flutter/material.dart';

import '../../core/theme/app_dimensions.dart';
import '../extensions/theme_context.dart';

/// How an AI output must be described to the user.
///
/// Spec: UI-UX Specification §51 (AI Safety UX), §39 (Confidence &
/// Explainability), Instructions §14 (AI Trust Rules).
///
/// AI output must never be presented as guaranteed truth when it is a
/// prediction or a recommendation. Every AI surface in Perfect HR declares its
/// provenance through this enum, so the wording is consistent across Employee,
/// Manager, HR and Executive experiences and cannot drift screen by screen.
enum AiProvenance {
  /// Descriptive AI output, e.g. a daily attendance summary.
  generatedInsight('AI-generated insight'),

  /// AI analysis supporting a human assessment, e.g. performance.
  assistedAnalysis('AI-assisted analysis'),

  /// Forward-looking probability, e.g. attrition. Never a statement of fact
  /// about an employee (Functional Blueprint §23).
  predictedRisk('AI-predicted risk'),

  /// A suggested course of action awaiting a human decision.
  recommendation('AI recommendation'),

  /// Conversational assistant response.
  assistantResponse('Perfect HR AI');

  const AiProvenance(this.label);

  final String label;

  /// Whether this provenance requires a confidence value to be shown.
  /// Predictions without a stated confidence would read as certainty.
  bool get requiresConfidence => this == AiProvenance.predictedRisk;
}

/// The Perfect HR AI mark: a sparkle plus the provenance label.
///
/// Sits at the top of every AI surface so AI involvement is never ambiguous
/// (Instructions §13 — AI must not read as a bolted-on chatbot, and must not
/// be decorative either).
class AiLabel extends StatelessWidget {
  const AiLabel({
    this.provenance = AiProvenance.generatedInsight,
    this.trailing,
    super.key,
  });

  final AiProvenance provenance;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return Row(
      children: [
        Icon(Icons.auto_awesome, size: 14, color: palette.ai),
        const SizedBox(width: AppSpacing.xxs + 2),
        Expanded(
          child: Text(
            provenance.label.toUpperCase(),
            style: context.styles.overline.copyWith(color: palette.ai),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ),
        if (trailing != null) trailing!,
      ],
    );
  }
}

/// Prediction confidence, e.g. "Confidence 89%".
///
/// UI-UX §39: the product must avoid presenting predictions as guaranteed
/// outcomes. Confidence is expressed as a band as well as a number, because a
/// bare percentage invites false precision.
class AiConfidenceBadge extends StatelessWidget {
  const AiConfidenceBadge({required this.confidence, this.compact = false, super.key})
      : assert(
          confidence >= 0 && confidence <= 1,
          'confidence must be a 0..1 fraction',
        );

  final double confidence;
  final bool compact;

  String get _band {
    if (confidence >= 0.8) return 'High';
    if (confidence >= 0.6) return 'Moderate';
    return 'Low';
  }

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final percentage = (confidence * 100).round();

    return Semantics(
      label: '$_band confidence, $percentage percent',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.xs,
          vertical: AppSpacing.xxs,
        ),
        decoration: BoxDecoration(
          color: palette.aiContainer,
          borderRadius: AppRadius.pillRadius,
          border: Border.all(color: palette.ai.withValues(alpha: 0.25)),
        ),
        child: Text(
          compact ? '$percentage%' : 'Confidence $percentage%',
          style: context.text.bodySmall?.copyWith(
            color: palette.onAiContainer,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

/// Risk severity levels used across attrition, performance and workforce
/// intelligence (Functional Blueprint §23, Screen Blueprint §78).
enum RiskLevel {
  low('Low'),
  medium('Medium'),
  high('High'),
  critical('Critical');

  const RiskLevel(this.label);

  final String label;
}

/// Risk pill. Pairs an icon with the colour so severity is never conveyed by
/// colour alone (UI-UX §49).
class RiskIndicator extends StatelessWidget {
  const RiskIndicator({
    required this.level,
    this.provenance = AiProvenance.predictedRisk,
    this.showProvenance = true,
    super.key,
  });

  final RiskLevel level;

  /// Defaults to a *predicted* risk. Do not override to something more
  /// assertive unless the value is an observed fact rather than a forecast.
  final AiProvenance provenance;

  final bool showProvenance;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    final (color, background, icon) = switch (level) {
      RiskLevel.low => (
          palette.success,
          palette.successContainer,
          Icons.check_circle_outline,
        ),
      RiskLevel.medium => (
          palette.warning,
          palette.warningContainer,
          Icons.error_outline,
        ),
      RiskLevel.high => (
          palette.danger,
          palette.dangerContainer,
          Icons.warning_amber_outlined,
        ),
      RiskLevel.critical => (
          palette.danger,
          palette.dangerContainer,
          Icons.report_gmailerrorred_outlined,
        ),
    };

    final text = showProvenance
        ? '${level.label} — ${provenance.label}'
        : level.label;

    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.xs,
        vertical: AppSpacing.xxs,
      ),
      decoration: BoxDecoration(
        color: background,
        borderRadius: AppRadius.pillRadius,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 13, color: color),
          const SizedBox(width: AppSpacing.xxs + 2),
          Text(
            text,
            style: context.text.bodySmall
                ?.copyWith(color: color, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}
