import 'package:flutter/material.dart';

import '../../core/theme/app_dimensions.dart';
import '../extensions/theme_context.dart';
import '../widgets/app_card.dart';
import 'ai_explainability_panel.dart';
import 'ai_provenance.dart';

/// An action offered by an AI surface.
@immutable
class AiAction {
  const AiAction({
    required this.label,
    required this.onPressed,
    this.isPrimary = false,
    this.isDestructive = false,
  });

  final String label;
  final VoidCallback onPressed;
  final bool isPrimary;

  /// Destructive actions require confirmation before executing
  /// (Screen Blueprint §54). The confirming dialog is the caller's
  /// responsibility; this flag drives the styling.
  final bool isDestructive;
}

/// AI Insight Card.
///
/// Spec: UI-UX Specification §38, Screen & Wireframe Blueprint §55,
/// Instructions §13.
///
/// Structure enforced by the constructor: What happened → Why → What should I
/// do → Action. [what] is required; [why] and actions are optional because a
/// descriptive insight legitimately has none. A *recommendation*, by contrast,
/// must be explainable — use [AiRecommendationCard] for those.
class AiInsightCard extends StatelessWidget {
  const AiInsightCard({
    required this.what,
    this.why,
    this.recommendation,
    this.provenance = AiProvenance.generatedInsight,
    this.confidence,
    this.actions = const [],
    this.onTap,
    super.key,
  }) : assert(
          provenance != AiProvenance.predictedRisk || confidence != null,
          'A predicted risk must state its confidence '
          '(UI-UX §39). Use AiProvenance.generatedInsight for descriptive '
          'output, or supply a confidence value.',
        );

  /// What happened. E.g. "Productivity decreased 8% this week."
  final String what;

  /// Why it happened. E.g. "Main factor: workload concentration."
  final String? why;

  /// What the user might do about it.
  final String? recommendation;

  final AiProvenance provenance;
  final double? confidence;
  final List<AiAction> actions;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    return AppCard(
      onTap: onTap,
      background: palette.aiContainer,
      borderColor: palette.ai.withValues(alpha: 0.22),
      semanticLabel: '${provenance.label}. $what',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AiLabel(
            provenance: provenance,
            trailing: confidence == null
                ? null
                : AiConfidenceBadge(confidence: confidence!, compact: true),
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            what,
            style: context.text.bodyMedium?.copyWith(
              color: palette.onAiContainer,
              fontWeight: FontWeight.w600,
            ),
          ),
          if (why != null) ...[
            const SizedBox(height: AppSpacing.xxs),
            Text(
              why!,
              style: context.text.bodySmall
                  ?.copyWith(color: palette.onAiContainer),
            ),
          ],
          if (recommendation != null) ...[
            const SizedBox(height: AppSpacing.xs),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  Icons.lightbulb_outline,
                  size: AppSizes.iconSm,
                  color: palette.ai,
                ),
                const SizedBox(width: AppSpacing.xxs + 2),
                Expanded(
                  child: Text(
                    recommendation!,
                    style: context.text.bodySmall
                        ?.copyWith(color: palette.onAiContainer),
                  ),
                ),
              ],
            ),
          ],
          if (actions.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.sm),
            _AiActionRow(actions: actions),
          ],
        ],
      ),
    );
  }
}

/// AI Recommendation Card — for AI output that precedes a human decision.
///
/// Spec: UI-UX Specification §29 and §51, Screen & Wireframe Blueprint §45 and
/// §69, Instructions §14.
///
/// Deliberate design constraint: [reasons] and [decisionAuthority] are
/// required, so it is not possible to render an AI recommendation in Perfect HR
/// without both an explanation and a statement of human accountability. The
/// pattern this enforces is:
///
///   AI recommends → Authorized human decides → System records
///
/// Use for: leave and attendance approvals, recruitment shortlisting,
/// performance and attrition interventions, compensation.
class AiRecommendationCard extends StatelessWidget {
  // Not const, for the same reason as AiExplainabilityPanel: `List.length` is
  // not const-evaluable, so a const invocation cannot compile. Nothing calls
  // this with `const` today, which is the only reason analysis passed before —
  // the first person to write `const AiRecommendationCard(...)` would have hit
  // it. Keeping the assert and dropping const preserves AD-14.
  AiRecommendationCard({
    required this.recommendation,
    required this.reasons,
    required this.decisionAuthority,
    this.confidence,
    this.provenance = AiProvenance.recommendation,
    this.decisionActions = const [],
    this.onViewData,
    super.key,
  }) : assert(
          reasons.isNotEmpty,
          'An AI recommendation must carry its reasons '
          '(UI-UX §5, Instructions §14).',
        );

  /// E.g. "Recommended: Approve".
  final String recommendation;

  /// The evidence. Surfaced inline and in the explainability panel.
  final List<AiReason> reasons;

  /// Who decides. E.g. "Final decision remains with the authorized manager."
  final String decisionAuthority;

  final double? confidence;
  final AiProvenance provenance;

  /// The human decision buttons, e.g. Approve / Reject / Request Clarification.
  final List<AiAction> decisionActions;

  final VoidCallback? onViewData;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    return AppCard(
      accent: palette.ai,
      semanticLabel: '${provenance.label}. $recommendation',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AiLabel(
            provenance: provenance,
            trailing: confidence == null
                ? null
                : AiConfidenceBadge(confidence: confidence!, compact: true),
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(recommendation, style: context.text.titleMedium),
          const SizedBox(height: AppSpacing.sm),
          for (final reason in reasons.take(3))
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xxs),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 3),
                    child: Icon(
                      reason.satisfied ? Icons.check : Icons.priority_high,
                      size: 14,
                      color:
                          reason.satisfied ? palette.success : palette.warning,
                    ),
                  ),
                  const SizedBox(width: AppSpacing.xs),
                  Expanded(
                    child: Text(reason.text, style: context.text.bodySmall),
                  ),
                ],
              ),
            ),
          const SizedBox(height: AppSpacing.xs),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: () => AiExplainabilityPanel.show(
                context,
                conclusion: recommendation,
                reasons: reasons,
                provenance: provenance,
                confidence: confidence,
                decisionAuthority: decisionAuthority,
                onViewData: onViewData,
              ),
              icon: const Icon(Icons.help_outline, size: AppSizes.iconSm),
              label: const Text('Why this recommendation?'),
              style: TextButton.styleFrom(
                padding: EdgeInsets.zero,
                minimumSize: const Size(0, AppSizes.minTouchTarget),
              ),
            ),
          ),
          if (decisionActions.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.xs),
            _AiActionRow(actions: decisionActions),
          ],
          const SizedBox(height: AppSpacing.sm),
          Divider(color: palette.border, height: 1),
          const SizedBox(height: AppSpacing.xs),
          // Always rendered. Human accountability is not optional.
          Row(
            children: [
              Icon(
                Icons.gavel_outlined,
                size: 14,
                color: palette.inkTertiary,
              ),
              const SizedBox(width: AppSpacing.xs),
              Expanded(
                child: Text(
                  decisionAuthority,
                  style: context.text.bodySmall
                      ?.copyWith(color: palette.inkTertiary),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _AiActionRow extends StatelessWidget {
  const _AiActionRow({required this.actions});

  final List<AiAction> actions;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    return Wrap(
      spacing: AppSpacing.xs,
      runSpacing: AppSpacing.xs,
      children: [
        for (final action in actions)
          if (action.isPrimary)
            FilledButton(
              onPressed: action.onPressed,
              style: FilledButton.styleFrom(
                minimumSize: const Size(0, AppSizes.minTouchTarget),
                backgroundColor:
                    action.isDestructive ? palette.danger : palette.brand,
                padding:
                    const EdgeInsets.symmetric(horizontal: AppSpacing.md),
              ),
              child: Text(action.label),
            )
          else
            OutlinedButton(
              onPressed: action.onPressed,
              style: OutlinedButton.styleFrom(
                minimumSize: const Size(0, AppSizes.minTouchTarget),
                foregroundColor:
                    action.isDestructive ? palette.danger : palette.brand,
                padding:
                    const EdgeInsets.symmetric(horizontal: AppSpacing.md),
              ),
              child: Text(action.label),
            ),
      ],
    );
  }
}
