import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_dimensions.dart';
import '../extensions/theme_context.dart';
import '../widgets/app_card.dart';

/// Scaffold placeholder for a route whose screen is not yet implemented.
///
/// Deliberately explicit: it names the Blueprint screen ID, the screen's
/// purpose and the task that will build it. Instructions §45 — a feature is
/// not complete because a route resolves, so a placeholder must not be
/// mistakable for a finished screen during review or demo.
///
/// Every one of these is replaced by a real screen in a later task. When the
/// last one is gone, Release 1 route coverage is complete.
class ScreenPlaceholder extends StatelessWidget {
  const ScreenPlaceholder({
    required this.screenId,
    required this.title,
    required this.purpose,
    required this.plannedTask,
    super.key,
  });

  final String screenId;
  final String title;
  final String purpose;
  final String plannedTask;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final canPop = GoRouter.of(context).canPop();

    return Scaffold(
      appBar: AppBar(
        title: Text(title),
        leading: canPop
            ? IconButton(
                icon: const Icon(Icons.arrow_back),
                onPressed: () => context.pop(),
                tooltip: 'Back',
              )
            : null,
      ),
      body: SingleChildScrollView(
        padding: AppSpacing.page,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            AppCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: AppSpacing.xs,
                          vertical: AppSpacing.xxs,
                        ),
                        decoration: BoxDecoration(
                          color: palette.brandContainer,
                          borderRadius: AppRadius.pillRadius,
                        ),
                        child: Text(
                          screenId,
                          style: context.text.bodySmall?.copyWith(
                            color: palette.onBrandContainer,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      const SizedBox(width: AppSpacing.xs),
                      Expanded(
                        child: Text(
                          'Not implemented',
                          style: context.text.bodySmall,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(title, style: context.text.titleMedium),
                  const SizedBox(height: AppSpacing.xxs),
                  Text(purpose, style: context.text.bodySmall),
                  const SizedBox(height: AppSpacing.md),
                  Divider(color: palette.border, height: 1),
                  const SizedBox(height: AppSpacing.xs),
                  Row(
                    children: [
                      Icon(
                        Icons.schedule_outlined,
                        size: AppSizes.iconSm,
                        color: palette.inkTertiary,
                      ),
                      const SizedBox(width: AppSpacing.xs),
                      Expanded(
                        child: Text(
                          plannedTask,
                          style: context.text.bodySmall
                              ?.copyWith(color: palette.inkTertiary),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
