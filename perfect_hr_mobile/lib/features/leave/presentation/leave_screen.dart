import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../core/analytics/telemetry.dart';
import '../../../core/capabilities/capability_providers.dart';
import '../../../core/capabilities/model_access.dart';
import '../../../core/constants/screen_ids.dart';
import '../../../core/data/cache_policy.dart';
import '../../../core/errors/app_failure.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../shared/components/async_state_view.dart';
import '../../../shared/components/ux_states.dart';
import '../../../shared/extensions/theme_context.dart';
import '../../../shared/widgets/app_card.dart';
import '../application/leave_providers.dart';
import '../domain/leave_models.dart';
import 'apply_leave_sheet.dart';

/// **E-05 — Leave.**
///
/// Spec: Screen & Wireframe Blueprint §13, UI-UX Specification §16.
///
/// Balances first, then the employee's own requests. Balances are what people
/// open this screen to check, and they are also what makes the Apply button
/// meaningful — offering "Apply" above a balance nobody has read invites a
/// request that will be refused.
///
/// | Aspect | Value |
/// | --- | --- |
/// | API | `GET /me/leave`, `POST /me/leave/apply`, `.../cancel` |
/// | Cache | `CachePolicy.activityList` (5 min), invalidated on every action |
class LeaveScreen extends ConsumerStatefulWidget {
  const LeaveScreen({super.key});

  static const String screenId = ScreenIds.leaveDashboard;

  @override
  ConsumerState<LeaveScreen> createState() => _LeaveScreenState();
}

class _LeaveScreenState extends ConsumerState<LeaveScreen> {
  @override
  void initState() {
    super.initState();
    ref.read(telemetryProvider).trackScreen(LeaveScreen.screenId);
  }

  @override
  Widget build(BuildContext context) {
    final snapshot = ref.watch(leaveProvider);

    ref.listen(leaveActionProvider, (previous, next) {
      if (!next.hasError || !context.mounted) return;
      final failure = asAppFailure(next.error!, next.stackTrace);
      ScaffoldMessenger.of(context)
        ..clearSnackBars()
        ..showSnackBar(SnackBar(content: Text(failure.userMessage)));
    });

    return Scaffold(
      appBar: AppBar(title: const Text('Leave')),
      body: RefreshIndicator(
        onRefresh: () => ref.read(leaveProvider.notifier).refresh(),
        child: AsyncStateView<DataSnapshot<LeaveOverview>>(
          value: snapshot,
          loadingLabel: 'Loading your leave',
          onRetry: () => ref.invalidate(leaveProvider),
          builder: (data) => _Content(snapshot: data),
        ),
      ),
    );
  }
}

class _Content extends ConsumerWidget {
  const _Content({required this.snapshot});

  final DataSnapshot<LeaveOverview> snapshot;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final overview = snapshot.data;
    final requestable = overview.requestable;

    // Two different reasons Apply can be unavailable, and they need different
    // sentences: nothing left to request, versus not permitted to request.
    final mayApply = ref.watch(
      canProvider((model: OdooModels.leave, operation: ModelOperation.create)),
    );

    return ListView(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.md,
        AppSpacing.md,
        AppSpacing.md,
        AppSpacing.xxl,
      ),
      children: [
        if (snapshot.isStale) ...[
          AppStaleDataBanner(
            lastSyncedAt: snapshot.syncedAt,
            onRefresh: () => ref.read(leaveProvider.notifier).refresh(),
          ),
          const SizedBox(height: AppSpacing.md),
        ],

        const AppSectionHeader(title: 'Balances'),
        if (overview.balances.isEmpty)
          AppCard(
            child: Text(
              'No leave has been allocated to you yet. '
              'Your HR team sets this up.',
              style: context.text.bodyMedium,
            ),
          )
        else
          for (final balance in overview.balances) _BalanceCard(balance: balance),

        const SizedBox(height: AppSpacing.md),
        SizedBox(
          height: AppSizes.buttonHeight,
          child: FilledButton.icon(
            // Disabled when nothing can be requested, rather than hidden: a
            // missing button reads as a broken screen, while a disabled one
            // with the explanation below it explains itself.
            onPressed: requestable.isEmpty || !mayApply
                ? null
                : () => showApplyLeaveSheet(context, balances: requestable),
            icon: const Icon(Icons.event_available_outlined),
            label: const Text('Apply for Leave'),
          ),
        ),
        if (!mayApply) ...[
          const SizedBox(height: AppSpacing.xs),
          Text(
            // Distinct from the empty-balance case above. "You have no days
            // left" and "you are not permitted to request leave" send the
            // person to different people for a remedy.
            'Your role does not include requesting leave. '
            'Your HR team can change this.',
            style: context.text.bodySmall
                ?.copyWith(color: context.palette.inkTertiary),
          ),
        ],

        const SizedBox(height: AppSpacing.lg),
        const AppSectionHeader(title: 'My requests'),
        if (overview.requests.isEmpty)
          AppCard(
            child: Text(
              "You haven't requested any leave yet.",
              style: context.text.bodyMedium,
            ),
          )
        else
          for (final request in overview.requests)
            _RequestCard(request: request),
      ],
    );
  }
}

class _BalanceCard extends StatelessWidget {
  const _BalanceCard({required this.balance});

  final LeaveBalance balance;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final allocated = balance.allocatedDays;
    // Guarded: an unlimited type has no allocation, and dividing by it would
    // produce NaN and a blank bar rather than an error anyone would notice.
    final fraction = allocated > 0
        ? (balance.remainingDays / allocated).clamp(0.0, 1.0)
        : null;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xs),
      child: AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    balance.label,
                    style: context.text.bodyLarge,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Text(
                  '${_days(balance.remainingDays)} left',
                  style: context.text.titleMedium,
                ),
              ],
            ),
            if (fraction != null) ...[
              const SizedBox(height: AppSpacing.xs),
              ClipRRect(
                borderRadius: AppRadius.pillRadius,
                child: LinearProgressIndicator(
                  value: fraction,
                  minHeight: 6,
                  backgroundColor: palette.surfaceAlt,
                ),
              ),
              const SizedBox(height: AppSpacing.xxs),
              Text(
                '${_days(balance.takenDays)} taken of '
                '${_days(allocated)} allocated',
                style: context.text.bodySmall
                    ?.copyWith(color: palette.inkTertiary),
              ),
            ] else ...[
              const SizedBox(height: AppSpacing.xxs),
              Text(
                'No allocation required',
                style: context.text.bodySmall
                    ?.copyWith(color: palette.inkTertiary),
              ),
            ],
          ],
        ),
      ),
    );
  }

  /// Half-days are real in Odoo, so 0.5 must not be rounded away — but "10.0
  /// days" reads badly, so a whole number loses its decimal.
  static String _days(double value) {
    final whole = value == value.roundToDouble();
    return '${whole ? value.toStringAsFixed(0) : value.toStringAsFixed(1)} '
        '${value == 1 ? 'day' : 'days'}';
  }
}

class _RequestCard extends ConsumerWidget {
  const _RequestCard({required this.request});

  final LeaveRequest request;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final palette = context.palette;
    final busy = ref.watch(leaveActionProvider).isLoading;

    final tint = switch (request.state) {
      LeaveState.approved => palette.success,
      LeaveState.refused => palette.danger,
      LeaveState.cancelled => palette.inkTertiary,
      _ => palette.warning,
    };

    final format = DateFormat('d MMM');
    final range = request.dateFrom == request.dateTo
        ? format.format(request.dateFrom)
        : '${format.format(request.dateFrom)} – '
            '${format.format(request.dateTo)}';

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xs),
      child: AppCard(
        accent: tint,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    request.typeLabel,
                    style: context.text.bodyLarge,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Text(
                  // The server's own wording. Odoo's approval chain is
                  // configurable per type, so "Waiting second approval" is
                  // meaningless on a single-approver type and only the server
                  // knows which this is.
                  request.stateLabel,
                  style: context.text.bodySmall?.copyWith(color: tint),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.xxs),
            Text(
              '$range · ${request.days == request.days.roundToDouble() ? request.days.toStringAsFixed(0) : request.days.toStringAsFixed(1)} '
              '${request.days == 1 ? 'day' : 'days'}',
              style: context.text.bodySmall,
            ),
            if (request.reason != null && request.reason!.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.xxs),
              Text(
                request.reason!,
                style: context.text.bodySmall
                    ?.copyWith(color: palette.inkTertiary),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            ],
            if (request.canCancel) ...[
              const SizedBox(height: AppSpacing.xs),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: busy
                      ? null
                      : () => _confirmCancel(context, ref),
                  child: const Text('Cancel request'),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Future<void> _confirmCancel(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Cancel this request?'),
        content: Text(
          'Your ${request.typeLabel} request will be withdrawn. '
          'You can apply again afterwards.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Keep it'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Cancel request'),
          ),
        ],
      ),
    );

    if (confirmed != true) return;
    await ref.read(leaveActionProvider.notifier).cancel(request.id);
  }
}
