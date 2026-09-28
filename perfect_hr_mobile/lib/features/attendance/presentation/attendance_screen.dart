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
import '../../dashboard/domain/employee_home_summary.dart';
import '../application/attendance_providers.dart';
import '../domain/attendance_overview.dart';

/// **E-02 — Attendance.**
///
/// Spec: Screen & Wireframe Blueprint §10, UI-UX Specification §13.
///
/// One button, and the server decides what it does. The label is derived from
/// the state the server last reported, never from what this screen believes it
/// did a moment ago — a phone that has been offline cannot know whether a kiosk
/// or biometric punch has happened since, and `hr_attendance_gateway` on this
/// deployment means device punches are routine.
///
/// | Aspect | Value |
/// | --- | --- |
/// | Role | Any employee |
/// | API | `GET /me/attendance`, `POST /me/attendance/toggle` |
/// | Cache | `CachePolicy.dashboard` (2 min), invalidated on every punch |
/// | States | All six via `AsyncStateView` |
class AttendanceScreen extends ConsumerStatefulWidget {
  const AttendanceScreen({super.key});

  static const String screenId = ScreenIds.attendanceHome;

  @override
  ConsumerState<AttendanceScreen> createState() => _AttendanceScreenState();
}

class _AttendanceScreenState extends ConsumerState<AttendanceScreen> {
  @override
  void initState() {
    super.initState();
    ref.read(telemetryProvider).trackScreen(AttendanceScreen.screenId);
  }

  @override
  Widget build(BuildContext context) {
    final snapshot = ref.watch(attendanceProvider);

    // A failed punch is announced here rather than inside the content, so it
    // is seen even when the list below is still showing the previous state.
    ref.listen(attendanceToggleProvider, (previous, next) {
      if (!next.hasError || !context.mounted) return;
      final failure = asAppFailure(next.error!, next.stackTrace);
      ScaffoldMessenger.of(context)
        ..clearSnackBars()
        ..showSnackBar(SnackBar(content: Text(failure.userMessage)));
    });

    return Scaffold(
      appBar: AppBar(title: const Text('Attendance')),
      body: RefreshIndicator(
        onRefresh: () => ref.read(attendanceProvider.notifier).refresh(),
        child: AsyncStateView<DataSnapshot<AttendanceOverview>>(
          value: snapshot,
          loadingLabel: 'Loading your attendance',
          onRetry: () => ref.invalidate(attendanceProvider),
          builder: (data) => _Content(snapshot: data),
        ),
      ),
    );
  }
}

class _Content extends ConsumerWidget {
  const _Content({required this.snapshot});

  final DataSnapshot<AttendanceOverview> snapshot;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final overview = snapshot.data;

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
            onRefresh: () => ref.read(attendanceProvider.notifier).refresh(),
          ),
          const SizedBox(height: AppSpacing.md),
        ],
        _TodayCard(overview: overview),
        const SizedBox(height: AppSpacing.lg),
        _SummaryRow(overview: overview),
        const SizedBox(height: AppSpacing.lg),
        const AppSectionHeader(title: 'Recent'),
        if (overview.days.isEmpty)
          AppCard(
            child: Text(
              'No attendance has been recorded in the last month.',
              style: context.text.bodyMedium,
            ),
          )
        else
          for (final day in overview.days) _DayRow(day: day),
      ],
    );
  }
}

class _TodayCard extends ConsumerWidget {
  const _TodayCard({required this.overview});

  final AttendanceOverview overview;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final palette = context.palette;
    final today = overview.today;
    final busy = ref.watch(attendanceToggleProvider).isLoading;
    final onLeave = today.state == AttendanceState.onLeave;

    // Gated on the server's own answer, not on a role name. Someone whose
    // Plaza role does not carry create on hr.attendance would otherwise be
    // shown a button that can only 403 — and a 403 reads as a broken app, not
    // as a deliberate restriction.
    final mayPunch = ref.watch(
      canProvider((
        model: OdooModels.attendance,
        operation: ModelOperation.create,
      )),
    );

    final (label, accent) = switch (today.state) {
      AttendanceState.checkedIn ||
      AttendanceState.onBreak =>
        ('CHECKED IN', palette.success),
      AttendanceState.checkedOut => ('CHECKED OUT', palette.inkTertiary),
      AttendanceState.onLeave => ('ON LEAVE', palette.info),
      _ => ('NOT CHECKED IN', palette.inkTertiary),
    };

    return AppCard(
      accent: accent,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _StatusPill(label: label, tint: accent),
          const SizedBox(height: AppSpacing.sm),
          Text(
            switch (today.state) {
              AttendanceState.checkedIn ||
              AttendanceState.onBreak =>
                'Working since ${_time(today.checkInAt)}',
              AttendanceState.checkedOut =>
                'Done for today — ${today.workedLabel}',
              AttendanceState.onLeave => "You're on approved leave today",
              _ => 'Ready to start your day?',
            },
            style: context.text.titleMedium,
          ),
          if (today.workedMinutes > 0) ...[
            const SizedBox(height: AppSpacing.xxs),
            Text(
              'Worked today: ${today.workedLabel}',
              style: context.text.bodySmall,
            ),
          ],
          if (overview.shiftLabel != null || overview.workplaceLabel != null) ...[
            const SizedBox(height: AppSpacing.xxs),
            Text(
              [overview.shiftLabel, overview.workplaceLabel]
                  .whereType<String>()
                  .join(' · '),
              style: context.text.bodySmall
                  ?.copyWith(color: palette.inkTertiary),
            ),
          ],
          const SizedBox(height: AppSpacing.md),
          SizedBox(
            height: AppSizes.buttonHeight,
            child: FilledButton.icon(
              // Disabled only while a punch is in flight, or on approved
              // leave. Not disabled on "checked out": a second shift, or a
              // correction to a premature check-out, are both legitimate, and
              // the server is the one that decides whether to accept it.
              onPressed: busy || onLeave || !mayPunch
                  ? null
                  : () => _punch(context, ref),
              icon: busy
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Icon(
                      today.state.isWorking ? Icons.logout : Icons.login,
                    ),
              label: Text(
                busy
                    ? 'Recording…'
                    : today.state.isWorking
                        ? 'Check Out'
                        : 'Check In',
              ),
            ),
          ),
          // Offered only while a session is open, because a break lives
          // inside one. Shown for `on_break` too, where it reads End Break.
          if (today.state.isWorking) ...[
            const SizedBox(height: AppSpacing.xs),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: busy
                    ? null
                    : () => ref
                        .read(attendanceToggleProvider.notifier)
                        .toggleBreak(),
                icon: Icon(
                  today.state == AttendanceState.onBreak
                      ? Icons.play_arrow_outlined
                      : Icons.pause_outlined,
                ),
                label: Text(
                  today.state == AttendanceState.onBreak
                      ? 'End Break'
                      : 'Take a Break',
                ),
              ),
            ),
          ],
          if (today.state == AttendanceState.onBreak) ...[
            const SizedBox(height: AppSpacing.xs),
            Text(
              // Said plainly, because the alternative is somebody checking
              // out mid-break and finding the button refuses them.
              'Your break time is deducted from today. End the break before '
              'you check out.',
              style: context.text.bodySmall
                  ?.copyWith(color: palette.inkTertiary),
            ),
          ],
          if (!mayPunch) ...[
            const SizedBox(height: AppSpacing.xs),
            Text(
              // Named as a permission, not as a fault. Someone in this state
              // needs to know who to ask, and "something went wrong" sends
              // them to the wrong person.
              'Your role does not include recording attendance. '
              'Your HR team can change this.',
              style: context.text.bodySmall
                  ?.copyWith(color: palette.inkTertiary),
            ),
          ],
        ],
      ),
    );
  }

  static String _time(DateTime? value) =>
      value == null ? '—' : DateFormat.jm().format(value);

  /// Punch, and if the server says it looks off-site, ask why and send again.
  ///
  /// The second attempt is what makes the location rule an accountability
  /// control rather than a lockout: nobody is ever left unable to start work,
  /// and every exception carries a reason the employee wrote at the time.
  static Future<void> _punch(BuildContext context, WidgetRef ref) async {
    final controller = ref.read(attendanceToggleProvider.notifier);
    final result = await controller.toggle();
    if (result != null || !context.mounted) return;

    // Keyed on the server's own code, not on the failure type. An off-site
    // refusal is a 403 and therefore a PermissionFailure; a stale session is
    // a 409 and a ValidationFailure. Matching on type would have tied this to
    // an HTTP status the server is free to change.
    final failure = ref.read(attendanceToggleProvider).error;
    if (failure is! AppFailure || failure.code != 'off_site') return;

    final reason = await showDialog<String>(
      context: context,
      builder: (context) => _OffSiteReasonDialog(message: failure.userMessage),
    );
    if (reason == null || reason.trim().isEmpty || !context.mounted) return;
    await controller.toggle(offSiteReason: reason.trim());
  }
}

/// Asks why somebody is checking in away from their work location.
///
/// A free-text field rather than a list of reasons. The list would be wrong
/// on its first day — site visit, client meeting, delivery, power cut at the
/// office, working from a cafe because the lift is broken — and an employee
/// forced to pick the nearest wrong option teaches HR nothing.
class _OffSiteReasonDialog extends StatefulWidget {
  const _OffSiteReasonDialog({required this.message});

  final String message;

  @override
  State<_OffSiteReasonDialog> createState() => _OffSiteReasonDialogState();
}

class _OffSiteReasonDialogState extends State<_OffSiteReasonDialog> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Working away from your usual place?'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(widget.message),
          const SizedBox(height: AppSpacing.md),
          TextField(
            controller: _controller,
            autofocus: true,
            maxLines: 2,
            maxLength: 200,
            textCapitalization: TextCapitalization.sentences,
            decoration: const InputDecoration(
              labelText: 'What are you doing today?',
              hintText: 'Client visit at Gulshan',
            ),
            onSubmitted: (value) => Navigator.of(context).pop(value),
          ),
          Text(
            'Your check-in will be recorded with this note for HR.',
            style: context.text.bodySmall
                ?.copyWith(color: context.palette.inkTertiary),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(_controller.text),
          child: const Text('Check in anyway'),
        ),
      ],
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({required this.label, required this.tint});

  final String label;
  final Color tint;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.xs,
        vertical: AppSpacing.xxs,
      ),
      decoration: BoxDecoration(
        color: tint.withValues(alpha: 0.12),
        borderRadius: AppRadius.pillRadius,
      ),
      child: Text(
        label,
        style: context.styles.overline.copyWith(color: tint),
      ),
    );
  }
}

class _SummaryRow extends StatelessWidget {
  const _SummaryRow({required this.overview});

  final AttendanceOverview overview;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: _Metric(
            label: 'Days present',
            value: '${overview.daysPresent}',
          ),
        ),
        const SizedBox(width: AppSpacing.sm),
        Expanded(
          child: _Metric(
            label: 'Average day',
            value: overview.averageDayLabel,
          ),
        ),
      ],
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label.toUpperCase(),
            style: context.styles.overline
                .copyWith(color: context.palette.inkTertiary),
          ),
          const SizedBox(height: AppSpacing.xxs),
          Text(value, style: context.text.titleLarge),
        ],
      ),
    );
  }
}

class _DayRow extends StatelessWidget {
  const _DayRow({required this.day});

  final AttendanceDay day;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final first = day.sessions.isEmpty ? null : day.sessions.first;
    final last = day.sessions.isEmpty ? null : day.sessions.last;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xs),
      child: AppCard(
        child: Row(
          children: [
            SizedBox(
              width: 52,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    DateFormat.d().format(day.date),
                    style: context.text.titleMedium,
                  ),
                  Text(
                    DateFormat.E().format(day.date),
                    style: context.text.bodySmall
                        ?.copyWith(color: palette.inkTertiary),
                  ),
                ],
              ),
            ),
            Expanded(
              child: Text(
                first == null
                    ? '—'
                    : '${DateFormat.jm().format(first.checkIn)}'
                        ' → '
                        '${last?.checkOut == null ? 'still in' : DateFormat.jm().format(last!.checkOut!)}',
                style: context.text.bodyMedium,
              ),
            ),
            Text(
              day.workedLabel,
              style: context.text.bodyMedium?.copyWith(
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
