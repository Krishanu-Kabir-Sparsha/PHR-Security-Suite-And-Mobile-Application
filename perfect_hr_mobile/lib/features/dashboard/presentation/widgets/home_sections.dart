import 'package:flutter/material.dart';

import '../../../../core/theme/app_dimensions.dart';
import '../../../../shared/extensions/theme_context.dart';
import '../../../../shared/widgets/app_card.dart';
import '../../../../shared/widgets/kpi_card.dart';
import '../../../../shared/widgets/status_badge.dart';
import '../../domain/employee_home_summary.dart';

/// E-01 · TODAY — the most-used card in the application.
///
/// Spec: Screen & Wireframe Blueprint §9, UI-UX Specification §12 (Section 1).
/// UX formula: Context (today) → Status (checked in) → Action (break/check out).
class TodayAttendanceCard extends StatelessWidget {
  const TodayAttendanceCard({
    required this.attendance,
    this.onCheckIn,
    this.onCheckOut,
    this.onBreak,
    this.isBusy = false,
    super.key,
  });

  final TodayAttendance attendance;
  final VoidCallback? onCheckIn;
  final VoidCallback? onCheckOut;
  final VoidCallback? onBreak;

  /// Disables actions while a check-in or check-out is in flight, so a double
  /// tap cannot submit twice.
  final bool isBusy;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final (label, status) = _statusFor(attendance.state);

    return AppCard(
      accent: status.accent(palette),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              StatusBadge(label: label, status: status),
              const Spacer(),
              if (attendance.shiftLabel != null)
                Text(attendance.shiftLabel!, style: context.text.bodySmall),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          if (attendance.checkInAt != null) ...[
            Text(
              _formatTime(attendance.checkInAt!),
              style: context.styles.kpiLarge,
            ),
            const SizedBox(height: AppSpacing.xxs),
            Text(
              'Worked ${attendance.workedLabel}',
              style: context.text.bodyMedium,
            ),
          ] else
            Text(
              _promptFor(attendance.state),
              style: context.text.titleMedium,
            ),
          if (attendance.workplaceLabel != null) ...[
            const SizedBox(height: AppSpacing.xs),
            Row(
              children: [
                Icon(
                  Icons.place_outlined,
                  size: AppSizes.iconSm,
                  color: palette.inkTertiary,
                ),
                const SizedBox(width: AppSpacing.xxs),
                Text(
                  attendance.workplaceLabel!,
                  style: context.text.bodySmall,
                ),
              ],
            ),
          ],
          if (_hasActions) ...[
            const SizedBox(height: AppSpacing.md),
            Row(
              children: [
                if (attendance.state.canCheckIn)
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: isBusy ? null : onCheckIn,
                      icon: const Icon(Icons.login, size: AppSizes.iconSm),
                      label: const Text('Check In'),
                    ),
                  ),
                if (attendance.state.canCheckOut) ...[
                  Expanded(
                    child: OutlinedButton(
                      onPressed: isBusy ? null : onBreak,
                      child: Text(
                        attendance.state == AttendanceState.onBreak
                            ? 'End Break'
                            : 'Break',
                      ),
                    ),
                  ),
                  const SizedBox(width: AppSpacing.xs),
                  Expanded(
                    child: FilledButton(
                      onPressed: isBusy ? null : onCheckOut,
                      child: const Text('Check Out'),
                    ),
                  ),
                ],
              ],
            ),
          ],
        ],
      ),
    );
  }

  bool get _hasActions =>
      attendance.state.canCheckIn || attendance.state.canCheckOut;

  static (String, AppStatus) _statusFor(AttendanceState state) {
    return switch (state) {
      AttendanceState.checkedIn => ('CHECKED IN', AppStatus.success),
      AttendanceState.onBreak => ('ON BREAK', AppStatus.warning),
      AttendanceState.checkedOut => ('CHECKED OUT', AppStatus.neutral),
      AttendanceState.onLeave => ('ON LEAVE', AppStatus.info),
      AttendanceState.holiday => ('HOLIDAY', AppStatus.info),
      AttendanceState.absent => ('ABSENT', AppStatus.danger),
      AttendanceState.notCheckedIn => ('NOT CHECKED IN', AppStatus.neutral),
    };
  }

  static String _promptFor(AttendanceState state) => switch (state) {
        AttendanceState.notCheckedIn => 'Ready to start your day?',
        AttendanceState.onLeave => "You're on approved leave today.",
        AttendanceState.holiday => 'Today is a public holiday.',
        AttendanceState.absent => 'No attendance recorded today.',
        _ => '',
      };

  static String _formatTime(DateTime time) {
    final hour = time.hour % 12 == 0 ? 12 : time.hour % 12;
    final minute = time.minute.toString().padLeft(2, '0');
    final period = time.hour < 12 ? 'AM' : 'PM';
    return '$hour:$minute $period';
  }
}

/// E-01 · QUICK ACTIONS.
///
/// UI-UX §12 (Section 2) and Principle 3, Action Over Navigation: the four
/// highest-frequency employee actions, reachable in one tap from home.
class QuickActionsGrid extends StatelessWidget {
  const QuickActionsGrid({required this.actions, super.key});

  final List<QuickAction> actions;

  @override
  Widget build(BuildContext context) {
    final columns =
        AppBreakpoints.isExpanded(context.screenWidth) ? 4 : 2;

    return LayoutBuilder(
      builder: (context, constraints) {
        const spacing = AppSpacing.sm;
        final width =
            (constraints.maxWidth - spacing * (columns - 1)) / columns;
        return Wrap(
          spacing: spacing,
          runSpacing: spacing,
          children: [
            for (final action in actions)
              SizedBox(
                width: width,
                child: _QuickActionTile(action: action),
              ),
          ],
        );
      },
    );
  }
}

@immutable
class QuickAction {
  const QuickAction({
    required this.label,
    required this.icon,
    required this.onTap,
    this.isEnabled = true,
  });

  final String label;
  final IconData icon;
  final VoidCallback onTap;

  /// A disabled action is still shown, so the interface does not reshuffle
  /// as permissions or attendance state change.
  final bool isEnabled;
}

class _QuickActionTile extends StatelessWidget {
  const _QuickActionTile({required this.action});

  final QuickAction action;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final enabled = action.isEnabled;

    return AppCard(
      onTap: enabled ? action.onTap : null,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.md,
      ),
      semanticLabel: action.label,
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.all(AppSpacing.xs),
            decoration: BoxDecoration(
              color: enabled ? palette.brandContainer : palette.surfaceAlt,
              borderRadius: AppRadius.controlRadius,
            ),
            child: Icon(
              action.icon,
              size: AppSizes.iconMd,
              color: enabled ? palette.brand : palette.inkTertiary,
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            action.label,
            textAlign: TextAlign.center,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: context.text.bodySmall?.copyWith(
              color: enabled ? palette.ink : palette.inkTertiary,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

/// E-01 · MY HR — leave balance and performance.
///
/// Performance is read-only score and direction only. Project State Q2: the
/// full E-12 dashboard is Release 2, and this tile deliberately cannot grow
/// into it.
class MyHrStrip extends StatelessWidget {
  const MyHrStrip({
    required this.leave,
    this.performance,
    this.onLeaveTap,
    this.onPerformanceTap,
    super.key,
  });

  final LeaveBalanceSummary? leave;
  final PerformanceSummary? performance;
  final VoidCallback? onLeaveTap;
  final VoidCallback? onPerformanceTap;

  @override
  Widget build(BuildContext context) {
    final tiles = <Widget>[
      if (leave != null)
        KpiCard(
          label: '${leave!.label} Leave',
          value: leave!.remainingLabel,
          unit: 'days',
          compact: true,
          onTap: onLeaveTap,
        ),
      // Omitted rather than shown as 0% when there is no record or the data
      // scope excludes it.
      if (performance != null)
        KpiCard(
          label: 'Performance',
          value: '${(performance!.score * 100).round()}%',
          delta: performance!.deltaPoints,
          isPositiveGood: true,
          compact: true,
          onTap: onPerformanceTap,
        ),
    ];

    if (tiles.isEmpty) return const SizedBox.shrink();
    return KpiGrid(children: tiles);
  }
}

/// E-01 · PENDING — items awaiting the employee or an approver.
class PendingItemsList extends StatelessWidget {
  const PendingItemsList({required this.items, this.onTap, super.key});

  final List<PendingItem> items;
  final void Function(PendingItem item)? onTap;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    return Column(
      children: [
        for (var index = 0; index < items.length; index++) ...[
          AppCard(
            onTap: onTap == null ? null : () => onTap!(items[index]),
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.sm,
              vertical: AppSpacing.sm,
            ),
            child: Row(
              children: [
                Icon(
                  _iconFor(items[index].kind),
                  size: AppSizes.iconMd,
                  color: palette.inkSecondary,
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        items[index].title,
                        style: context.styles.bodyStrong,
                      ),
                      if (items[index].subtitle.isNotEmpty)
                        Text(
                          items[index].subtitle,
                          style: context.text.bodySmall,
                        ),
                    ],
                  ),
                ),
                Icon(
                  Icons.chevron_right,
                  size: AppSizes.iconSm,
                  color: palette.inkTertiary,
                ),
              ],
            ),
          ),
          if (index < items.length - 1)
            const SizedBox(height: AppSpacing.xs),
        ],
      ],
    );
  }

  static IconData _iconFor(PendingItemKind kind) => switch (kind) {
        PendingItemKind.leave => Icons.event_available_outlined,
        PendingItemKind.attendanceCorrection => Icons.edit_calendar_outlined,
        PendingItemKind.hrRequest => Icons.description_outlined,
        PendingItemKind.performanceReview => Icons.trending_up_outlined,
        PendingItemKind.learning => Icons.school_outlined,
      };
}
