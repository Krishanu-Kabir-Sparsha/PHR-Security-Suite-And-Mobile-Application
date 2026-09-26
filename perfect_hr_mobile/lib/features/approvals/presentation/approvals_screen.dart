import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../core/analytics/telemetry.dart';
import '../../../core/constants/screen_ids.dart';
import '../../../core/errors/app_failure.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../shared/components/async_state_view.dart';
import '../../../shared/extensions/theme_context.dart';
import '../../../shared/widgets/app_card.dart';
import '../../../shared/widgets/status_badge.dart';
import '../application/approvals_providers.dart';
import '../domain/override_approval.dart';

/// **Override approvals.**
///
/// The reason the native passkey path exists. An override changes a frozen
/// record, so approving one is gated on a fingerprint bound to that single
/// request — and a workflow that sent the approver to a browser each time is
/// one nobody would use.
///
/// Approve and Reject are deliberately not symmetrical. Approving raises a
/// device prompt; rejecting does not. Strong authentication is required because
/// an approval can change a record; a rejection cannot, and friction on the
/// safe answer is how people end up approving to make a dialog go away.
class ApprovalsScreen extends ConsumerStatefulWidget {
  const ApprovalsScreen({super.key});

  static const String screenId = ScreenIds.approvalInbox;

  @override
  ConsumerState<ApprovalsScreen> createState() => _ApprovalsScreenState();
}

class _ApprovalsScreenState extends ConsumerState<ApprovalsScreen> {
  @override
  void initState() {
    super.initState();
    ref.read(telemetryProvider).trackScreen(ApprovalsScreen.screenId);
  }

  @override
  Widget build(BuildContext context) {
    final queue = ref.watch(approvalQueueProvider);

    ref.listen(approvalActionProvider, (previous, next) {
      if (!next.hasError || !context.mounted) return;
      final failure = asAppFailure(next.error!, next.stackTrace);
      ScaffoldMessenger.of(context)
        ..clearSnackBars()
        ..showSnackBar(SnackBar(content: Text(failure.userMessage)));
    });

    return Scaffold(
      appBar: AppBar(title: const Text('Approvals')),
      body: RefreshIndicator(
        onRefresh: () => ref.read(approvalQueueProvider.notifier).refresh(),
        child: AsyncStateView<ApprovalQueue>(
          value: queue,
          loadingLabel: 'Checking what needs your approval',
          onRetry: () => ref.invalidate(approvalQueueProvider),
          builder: (data) => _Content(queue: data),
        ),
      ),
    );
  }
}

class _Content extends ConsumerWidget {
  const _Content({required this.queue});

  final ApprovalQueue queue;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (queue.isEmpty) {
      return ListView(
        padding: AppSpacing.page,
        children: [
          AppCard(
            child: Row(
              children: [
                Icon(
                  Icons.check_circle_outline,
                  color: context.palette.success,
                  size: AppSizes.iconMd,
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    'Nothing is waiting for your approval.',
                    style: context.text.bodyMedium,
                  ),
                ),
              ],
            ),
          ),
        ],
      );
    }

    return ListView(
      padding: AppSpacing.page,
      children: [
        for (final approval in queue.requests) _ApprovalCard(approval: approval),
      ],
    );
  }
}

class _ApprovalCard extends ConsumerWidget {
  const _ApprovalCard({required this.approval});

  final OverrideApproval approval;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final palette = context.palette;
    final busy = ref.watch(approvalActionProvider).isLoading;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: AppCard(
        accent: approval.highRisk ? palette.danger : palette.warning,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(approval.reference, style: context.text.titleMedium),
                ),
                if (approval.highRisk)
                  const StatusBadge(
                    status: AppStatus.danger,
                    label: 'High risk',
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.xxs),
            Text(approval.target, style: context.text.bodyLarge),
            const SizedBox(height: AppSpacing.xs),

            _Fact(label: 'Requested by', value: approval.requestedBy),
            if (approval.reason != null)
              _Fact(label: 'Reason', value: approval.reason!),
            if (approval.tierName != null)
              _Fact(label: 'Your step', value: approval.tierName!),
            if (approval.submittedAt != null)
              _Fact(
                label: 'Submitted',
                value: DateFormat('d MMM, HH:mm').format(approval.submittedAt!),
              ),

            if (approval.justification != null) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(
                approval.justification!,
                style: context.text.bodySmall
                    ?.copyWith(color: palette.inkSecondary),
              ),
            ],

            const SizedBox(height: AppSpacing.md),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: busy ? null : () => _confirmReject(context, ref),
                    child: const Text('Reject'),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: FilledButton.icon(
                    onPressed: busy ? null : () => _approve(context, ref),
                    icon: const Icon(Icons.fingerprint, size: AppSizes.iconSm),
                    label: const Text('Approve'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              // Said before the prompt appears, not after. A fingerprint
              // request that arrives unannounced is one people dismiss.
              'Approving asks for your fingerprint. It signs this request only.',
              style:
                  context.text.bodySmall?.copyWith(color: palette.inkTertiary),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _approve(BuildContext context, WidgetRef ref) async {
    final approved =
        await ref.read(approvalActionProvider.notifier).approve(approval);
    if (!context.mounted || !approved) return;
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(
        SnackBar(content: Text('${approval.reference} approved.')),
      );
  }

  Future<void> _confirmReject(BuildContext context, WidgetRef ref) async {
    // Confirmed because it ends the workflow: the requester has to start again.
    // Not gated on a device, though — see the class doc.
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Reject this override?'),
        content: Text(
          'This ends the request. ${approval.requestedBy} will have to raise '
          'a new one.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Go back'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Reject'),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;

    final rejected =
        await ref.read(approvalActionProvider.notifier).reject(approval);
    if (!context.mounted || !rejected) return;
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(
        SnackBar(content: Text('${approval.reference} rejected.')),
      );
  }
}

class _Fact extends StatelessWidget {
  const _Fact({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xxs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 96,
            child: Text(
              label,
              style: context.text.bodySmall
                  ?.copyWith(color: context.palette.inkTertiary),
            ),
          ),
          Expanded(child: Text(value, style: context.text.bodySmall)),
        ],
      ),
    );
  }
}
