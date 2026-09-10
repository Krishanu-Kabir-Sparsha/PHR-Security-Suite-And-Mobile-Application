import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/theme/app_theme.dart';
import 'package:perfect_hr_mobile/shared/ai/ai_cards.dart';
import 'package:perfect_hr_mobile/shared/ai/ai_explainability_panel.dart';
import 'package:perfect_hr_mobile/shared/ai/ai_provenance.dart';

/// Covers Instructions §14 (AI Trust Rules), UI-UX Specification §5, §39, §51
/// and Screen & Wireframe Blueprint §45, §69.
///
/// The intent of these tests is not merely that the widgets render. It is that
/// a future screen author *cannot* present an AI recommendation without an
/// explanation and a statement of human accountability. If any of these fail,
/// the trust guarantee has been weakened.

Widget _wrap(Widget child) {
  return MaterialApp(
    theme: AppTheme.light(),
    home: Scaffold(body: SingleChildScrollView(child: child)),
  );
}

const _reasons = [
  AiReason('Leave balance sufficient', detail: '12 days available, 2 requested'),
  AiReason('Team coverage acceptable'),
  AiReason('No policy conflict'),
];

void main() {
  group('AI provenance labelling', () {
    test('no provenance presents AI output as fact', () {
      for (final provenance in AiProvenance.values) {
        expect(provenance.label, isNotEmpty);
      }
      // Predictions and recommendations must be self-describing as such.
      expect(AiProvenance.predictedRisk.label, contains('predicted'));
      expect(AiProvenance.recommendation.label, contains('recommendation'));
      expect(AiProvenance.assistedAnalysis.label, contains('assisted'));
    });

    test('a predicted risk requires a confidence value', () {
      expect(AiProvenance.predictedRisk.requiresConfidence, isTrue);
    });

    testWidgets('AI surfaces are labelled as AI', (tester) async {
      await tester.pumpWidget(
        _wrap(
          const AiInsightCard(
            what: 'Productivity decreased 8% this week.',
            why: 'Main factor: workload concentration.',
          ),
        ),
      );
      expect(find.text('AI-GENERATED INSIGHT'), findsOneWidget);
      expect(find.byIcon(Icons.auto_awesome), findsOneWidget);
    });
  });

  group('AiInsightCard', () {
    testWidgets('renders what, why and recommendation in order',
        (tester) async {
      await tester.pumpWidget(
        _wrap(
          const AiInsightCard(
            what: 'Productivity decreased 8% this week.',
            why: 'Workload increased 14%.',
            recommendation: 'Rebalance workload across two team members.',
          ),
        ),
      );

      expect(find.text('Productivity decreased 8% this week.'), findsOneWidget);
      expect(find.text('Workload increased 14%.'), findsOneWidget);
      expect(
        find.text('Rebalance workload across two team members.'),
        findsOneWidget,
      );
    });

    test('a predicted risk without confidence is rejected', () {
      expect(
        () => AiInsightCard(
          what: 'Attrition risk increased in Engineering.',
          provenance: AiProvenance.predictedRisk,
        ),
        throwsAssertionError,
      );
    });

    test('a predicted risk with confidence is accepted', () {
      expect(
        () => AiInsightCard(
          what: 'Attrition risk increased in Engineering.',
          provenance: AiProvenance.predictedRisk,
          confidence: 0.81,
        ),
        returnsNormally,
      );
    });
  });

  group('AiRecommendationCard — human accountability', () {
    testWidgets('always renders the decision authority statement',
        (tester) async {
      await tester.pumpWidget(
        _wrap(
          AiRecommendationCard(
            recommendation: 'Recommended: Approve',
            reasons: _reasons,
            decisionAuthority:
                'Final decision remains with the authorized manager.',
            confidence: 0.89,
          ),
        ),
      );

      expect(
        find.text('Final decision remains with the authorized manager.'),
        findsOneWidget,
      );
    });

    testWidgets('exposes an explainability entry point', (tester) async {
      await tester.pumpWidget(
        _wrap(
          AiRecommendationCard(
            recommendation: 'Recommended: Approve',
            reasons: _reasons,
            decisionAuthority: 'Final decision remains with the manager.',
          ),
        ),
      );

      expect(find.text('Why this recommendation?'), findsOneWidget);
    });

    testWidgets('opening explainability shows every reason', (tester) async {
      await tester.pumpWidget(
        _wrap(
          AiRecommendationCard(
            recommendation: 'Recommended: Approve',
            reasons: _reasons,
            decisionAuthority: 'Final decision remains with the manager.',
            confidence: 0.89,
          ),
        ),
      );

      await tester.tap(find.text('Why this recommendation?'));
      await tester.pumpAndSettle();

      expect(find.text('WHY?'), findsOneWidget);
      for (final reason in _reasons) {
        expect(find.text(reason.text), findsWidgets);
      }
      expect(find.text('Confidence 89%'), findsOneWidget);
    });

    test('a recommendation without reasons is rejected', () {
      expect(
        () => AiRecommendationCard(
          recommendation: 'Recommended: Approve',
          reasons: const [],
          decisionAuthority: 'Final decision remains with the manager.',
        ),
        throwsAssertionError,
      );
    });

    testWidgets('decision actions are rendered for the human to choose',
        (tester) async {
      var approved = false;
      var rejected = false;

      await tester.pumpWidget(
        _wrap(
          AiRecommendationCard(
            recommendation: 'Recommended: Approve',
            reasons: _reasons,
            decisionAuthority: 'Final decision remains with the manager.',
            decisionActions: [
              AiAction(
                label: 'Approve',
                isPrimary: true,
                onPressed: () => approved = true,
              ),
              AiAction(
                label: 'Reject',
                isDestructive: true,
                onPressed: () => rejected = true,
              ),
            ],
          ),
        ),
      );

      await tester.tap(find.text('Approve'));
      expect(approved, isTrue);
      expect(rejected, isFalse);
    });
  });

  group('AiExplainabilityPanel', () {
    testWidgets('follows Recommendation → Why → Authority', (tester) async {
      await tester.pumpWidget(
        _wrap(
          const AiExplainabilityPanel(
            conclusion: 'Recommended: APPROVE',
            reasons: _reasons,
            confidence: 0.89,
          ),
        ),
      );

      expect(find.text('Recommended: APPROVE'), findsOneWidget);
      expect(find.text('WHY?'), findsOneWidget);
      expect(
        find.text('Final decision remains with the authorized approver.'),
        findsOneWidget,
      );
    });

    test('cannot be constructed without reasons', () {
      expect(
        () => AiExplainabilityPanel(
          conclusion: 'Recommended: APPROVE',
          reasons: const [],
        ),
        throwsAssertionError,
      );
    });
  });

  group('AiConfidenceBadge', () {
    testWidgets('states the confidence numerically', (tester) async {
      await tester.pumpWidget(
        _wrap(const AiConfidenceBadge(confidence: 0.81)),
      );
      expect(find.text('Confidence 81%'), findsOneWidget);
    });

    test('rejects an out-of-range confidence', () {
      expect(() => AiConfidenceBadge(confidence: 1.4), throwsAssertionError);
      expect(() => AiConfidenceBadge(confidence: -0.1), throwsAssertionError);
    });
  });

  group('RiskIndicator', () {
    testWidgets('describes risk as predicted, not observed', (tester) async {
      await tester.pumpWidget(
        _wrap(const RiskIndicator(level: RiskLevel.high)),
      );
      expect(find.text('High — AI-predicted risk'), findsOneWidget);
    });

    testWidgets('pairs an icon with the colour so severity is not colour-only',
        (tester) async {
      await tester.pumpWidget(
        _wrap(const RiskIndicator(level: RiskLevel.high)),
      );
      expect(find.byIcon(Icons.warning_amber_outlined), findsOneWidget);
    });
  });
}
