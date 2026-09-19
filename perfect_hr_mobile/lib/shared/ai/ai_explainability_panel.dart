import 'package:flutter/material.dart';

import '../../core/theme/app_dimensions.dart';
import '../extensions/theme_context.dart';
import 'ai_provenance.dart';

/// One piece of evidence behind an AI conclusion.
///
/// [satisfied] renders a tick or a caution glyph, matching the Blueprint AI-03
/// treatment (✓ Leave balance sufficient / ! Kubernetes gap).
@immutable
class AiReason {
  const AiReason(this.text, {this.satisfied = true, this.detail});

  final String text;
  final bool satisfied;

  /// Optional supporting figure, e.g. "12 days available, 2 requested".
  final String? detail;
}

/// AI-03 — Explainability Panel.
///
/// Spec: Screen & Wireframe Blueprint §45, UI-UX Specification §5 and §39,
/// Instructions §14.
///
/// Whenever AI provides a recommendation the user must be able to inspect the
/// rationale. This panel is the single implementation of that requirement, so
/// it is present in Release 1 even though the standalone AI-04 insight screen
/// is deferred — a Release 1 screen (M-05 Approval Detail) already shows an AI
/// recommendation, and a recommendation without an explanation would breach
/// the trust rules. See Project State Q3.
class AiExplainabilityPanel extends StatelessWidget {
  // Deliberately NOT a const constructor, and the assert is why. `List.length`
  // is not const-evaluable, so a `const AiExplainabilityPanel(...)` cannot
  // compile at all — it fails with `const_eval_property_access`. The choice is
  // between the const optimisation and the assert, and the assert wins: it is
  // the mechanism that makes AD-14 real, stopping an AI conclusion from being
  // rendered without its reasons. Dart offers no const-evaluable way to check
  // a list is non-empty, so a widget that cannot verify its own invariant at
  // compile time should not advertise a const constructor.
  AiExplainabilityPanel({
    required this.conclusion,
    required this.reasons,
    this.provenance = AiProvenance.recommendation,
    this.confidence,
    this.decisionAuthority = _defaultAuthority,
    this.onViewData,
    super.key,
  }) : assert(
          reasons.isNotEmpty,
          'An AI conclusion must be accompanied by its reasons '
          '(UI-UX §5 Explainability).',
        );

  /// What the AI concluded, e.g. "Recommended: Approve".
  final String conclusion;

  final List<AiReason> reasons;
  final AiProvenance provenance;
  final double? confidence;

  /// Who holds the decision. Never omit for sensitive HR domains.
  final String decisionAuthority;

  /// Opens the underlying data the conclusion was drawn from.
  final VoidCallback? onViewData;

  static const String _defaultAuthority =
      'Final decision remains with the authorized approver.';

  /// Presents the panel as a modal bottom sheet.
  static Future<void> show(
    BuildContext context, {
    required String conclusion,
    required List<AiReason> reasons,
    AiProvenance provenance = AiProvenance.recommendation,
    double? confidence,
    String decisionAuthority = _defaultAuthority,
    VoidCallback? onViewData,
  }) {
    return showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.md,
            0,
            AppSpacing.md,
            AppSpacing.md,
          ),
          child: AiExplainabilityPanel(
            conclusion: conclusion,
            reasons: reasons,
            provenance: provenance,
            confidence: confidence,
            decisionAuthority: decisionAuthority,
            onViewData: onViewData,
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        AiLabel(
          provenance: provenance,
          trailing: confidence == null
              ? null
              : AiConfidenceBadge(confidence: confidence!),
        ),
        const SizedBox(height: AppSpacing.sm),
        Text(conclusion, style: context.text.titleMedium),
        const SizedBox(height: AppSpacing.md),
        Text('WHY?', style: context.styles.overline),
        const SizedBox(height: AppSpacing.xs),
        for (final reason in reasons)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.xs),
            child: _ReasonRow(reason: reason),
          ),
        if (onViewData != null) ...[
          const SizedBox(height: AppSpacing.xs),
          OutlinedButton.icon(
            onPressed: onViewData,
            icon: const Icon(Icons.table_chart_outlined, size: AppSizes.iconSm),
            label: const Text('View Data'),
          ),
        ],
        const SizedBox(height: AppSpacing.md),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(AppSpacing.sm),
          decoration: BoxDecoration(
            color: palette.surfaceAlt,
            borderRadius: AppRadius.controlRadius,
          ),
          child: Row(
            children: [
              Icon(
                Icons.gavel_outlined,
                size: AppSizes.iconSm,
                color: palette.inkSecondary,
              ),
              const SizedBox(width: AppSpacing.xs),
              Expanded(
                child: Text(decisionAuthority, style: context.text.bodySmall),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ReasonRow extends StatelessWidget {
  const _ReasonRow({required this.reason});

  final AiReason reason;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final color = reason.satisfied ? palette.success : palette.warning;
    final icon = reason.satisfied ? Icons.check : Icons.priority_high;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 2),
          child: Icon(icon, size: 15, color: color),
        ),
        const SizedBox(width: AppSpacing.xs),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(reason.text, style: context.text.bodyMedium),
              if (reason.detail != null)
                Text(reason.detail!, style: context.text.bodySmall),
            ],
          ),
        ),
      ],
    );
  }
}
