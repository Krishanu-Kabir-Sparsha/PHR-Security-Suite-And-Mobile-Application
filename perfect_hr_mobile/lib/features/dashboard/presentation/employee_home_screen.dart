import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/analytics/telemetry.dart';
import '../../../core/constants/screen_ids.dart';
import '../../../core/data/cache_policy.dart';
import '../../../core/routing/app_routes.dart';
import '../../../core/session/session_controller.dart';
import '../../authentication/application/auth_providers.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../shared/ai/ai_cards.dart';
import '../../../shared/ai/ai_provenance.dart';
import '../../../shared/components/app_shell.dart';
import '../../../shared/components/async_state_view.dart';
import '../../../shared/components/ux_states.dart';
import '../../../shared/extensions/theme_context.dart';
import '../../../shared/widgets/app_card.dart';
import '../application/employee_home_providers.dart';
import '../domain/employee_home_summary.dart';
import 'widgets/home_sections.dart';
import '../../attendance/application/attendance_providers.dart';

/// **E-01 — Employee Home.**
///
/// Spec: Screen & Wireframe Blueprint §9, UI-UX Specification §12 and §55,
/// Functional Blueprint Module E01. One of the four flagship experiences
/// (Instructions §50) — its promise is "manage my HR life".
///
/// Section order is fixed by UI-UX §55:
/// TODAY → Quick Actions → My HR Status → AI Insight → Pending Items,
/// which is the Context → Status → Insight → Action formula (§54).
///
/// | Aspect | Value |
/// | --- | --- |
/// | Role | Employee (Manager/HR/Executive have their own home) |
/// | Entry | App launch after authentication; Home tab |
/// | Exit | Attendance, Leave, Requests, Payroll, AI, Notifications |
/// | API | `GET /me/home` — PROPOSED, see `ApiEmployeeHomeRepository` |
/// | Permission | Authenticated employee; performance tile omitted when absent |
/// | Cache | `CachePolicy.dashboard` (2 min), stale banner when served |
/// | States | All six handled via `AsyncStateView` |
class EmployeeHomeScreen extends ConsumerStatefulWidget {
  const EmployeeHomeScreen({super.key});

  static const String screenId = ScreenIds.employeeHome;

  @override
  ConsumerState<EmployeeHomeScreen> createState() =>
      _EmployeeHomeScreenState();
}

class _EmployeeHomeScreenState extends ConsumerState<EmployeeHomeScreen> {
  @override
  void initState() {
    super.initState();
    // Screen-view telemetry keyed by Blueprint ID (Instructions §20, §27).
    ref.read(telemetryProvider).trackScreen(EmployeeHomeScreen.screenId);
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(activeUserProvider);
    final snapshot = ref.watch(employeeHomeProvider);

    // Header sits outside the scroll area and the content fills the rest.
    // A CustomScrollView with the content in SliverFillRemaining would nest
    // two independent scrollables, and the centred message states need a
    // bounded height, which an unbounded sliver child cannot give them.
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.md,
                AppSpacing.md,
                AppSpacing.md,
                AppSpacing.xs,
              ),
              child: AppDashboardHeader(
                greeting: _greeting(user?.greetingName),
                subtitle: user?.jobTitle,
                avatarUrl: user?.avatarUrl,
                notificationCount:
                    snapshot.valueOrNull?.data.unreadNotifications ?? 0,
                onAvatarTap: () => context.go(AppRoutes.profile),
                onNotificationsTap: () =>
                    context.push(AppRoutes.notifications),
              ),
            ),
            Expanded(
              // Wrapping the state view means pull-to-refresh also works from
              // the error and offline states, which is where a user most wants
              // to retry.
              child: RefreshIndicator(
                onRefresh: () =>
                    ref.read(employeeHomeProvider.notifier).refresh(),
                child: AsyncStateView<DataSnapshot<EmployeeHomeSummary>>(
                  value: snapshot,
                  loadingLabel: 'Loading your day',
                  onRetry: () => ref.invalidate(employeeHomeProvider),
                  onGoBack: () => context.go(AppRoutes.more),
                  builder: (data) => _HomeContent(snapshot: data),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Time-of-day greeting, matching the Blueprint's "Good morning, Rahim".
  static String _greeting(String? name) {
    final hour = DateTime.now().hour;
    final part = hour < 12
        ? 'Good morning'
        : hour < 17
            ? 'Good afternoon'
            : 'Good evening';
    return name == null || name.isEmpty ? part : '$part, $name';
  }
}

class _HomeContent extends ConsumerWidget {
  const _HomeContent({required this.snapshot});

  final DataSnapshot<EmployeeHomeSummary> snapshot;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final summary = snapshot.data;

    return ListView(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.md,
        0,
        AppSpacing.md,
        AppSpacing.xxl,
      ),
      children: [
        // UI-UX §48 — say plainly when data is not live.
        if (snapshot.isStale) ...[
          AppStaleDataBanner(
            lastSyncedAt: snapshot.syncedAt,
            onRefresh: () =>
                ref.read(employeeHomeProvider.notifier).refresh(),
          ),
          const SizedBox(height: AppSpacing.md),
        ],

        // What signing in did to attendance, said once.
        const _SignInAttendanceNotice(),

        // Section 1 — TODAY
        const AppSectionHeader(title: 'Today'),
        TodayAttendanceCard(
          attendance: summary.attendance,
          onCheckIn: () => _openAttendance(context),
          onCheckOut: () => _openAttendance(context),
          onBreak: () => _openAttendance(context),
          // Handled here rather than by sending them to the Attendance tab.
          // A forgotten session blocks every check-in, so the fix has to be
          // reachable from the screen that first tells them about it.
          onResolveStale: () => _resolveStale(context, ref),
        ),
        const SizedBox(height: AppSpacing.lg),

        // Section 2 — QUICK ACTIONS
        const AppSectionHeader(title: 'Quick Actions'),
        QuickActionsGrid(
          actions: [
            QuickAction(
              label: summary.attendance.state.canCheckIn
                  ? 'Check In'
                  : 'Attendance',
              icon: Icons.schedule_outlined,
              onTap: () => context.go(AppRoutes.attendance),
            ),
            QuickAction(
              label: 'Apply Leave',
              icon: Icons.event_available_outlined,
              onTap: () => context.go(AppRoutes.applyLeave),
            ),
            QuickAction(
              label: 'HR Request',
              icon: Icons.description_outlined,
              onTap: () => context.go(AppRoutes.requests),
            ),
            QuickAction(
              label: 'Payslip',
              icon: Icons.payments_outlined,
              onTap: () => context.go(AppRoutes.payroll),
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.lg),

        // Section 3 — MY HR
        if (summary.primaryLeaveBalance != null ||
            summary.performance != null) ...[
          const AppSectionHeader(title: 'My HR'),
          MyHrStrip(
            leave: summary.primaryLeaveBalance,
            performance: summary.performance,
            onLeaveTap: () => context.go(AppRoutes.leave),
            // Release 1 has no employee performance screen (Q2), so the tile
            // is informational. It becomes tappable when E-12 lands.
            onPerformanceTap: null,
          ),
          const SizedBox(height: AppSpacing.lg),
        ],

        // Section 4 — AI INSIGHT
        if (summary.aiInsight != null) ...[
          _AiInsightSection(insight: summary.aiInsight!),
          const SizedBox(height: AppSpacing.lg),
        ],

        // Section 5 — PENDING
        const AppSectionHeader(title: 'Pending'),
        if (summary.pendingItems.isEmpty)
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
                    // UI-UX §46 — never a bare "No requests."
                    "You're all caught up. Nothing is waiting on you.",
                    style: context.text.bodyMedium,
                  ),
                ),
              ],
            ),
          )
        else
          PendingItemsList(
            items: summary.pendingItems,
            onTap: (item) => _openPendingItem(context, item),
          ),
      ],
    );
  }

  void _openAttendance(BuildContext context) {
    // Check-in itself is E-02/E-03 (Task 5). Routing there rather than posting
    // from home keeps location verification and policy handling in one place,
    // and avoids a submission with no visible confirmation.
    context.go(AppRoutes.attendance);
  }

  void _openPendingItem(BuildContext context, PendingItem item) {
    switch (item.kind) {
      case PendingItemKind.leave:
        context.go(AppRoutes.leave);
      case PendingItemKind.attendanceCorrection:
        context.go(AppRoutes.attendanceCorrection);
      case PendingItemKind.hrRequest:
        context.go(AppRoutes.requestDetailFor(item.id));
      case PendingItemKind.performanceReview:
      case PendingItemKind.learning:
        // Release 2 screens. Until they exist, the Requests inbox is the
        // closest honest destination.
        context.go(AppRoutes.requests);
    }
  }
}

/// Confirms what signing in did to today's attendance, once.
///
/// Shown for a check-in that was actually recorded, and for the outcomes a
/// person would otherwise be left wondering about — being on approved leave,
/// having no employee record, or the write having failed. Deliberately silent
/// for "already checked in" and for a company that has the feature off: those
/// need no explanation and a banner for them is noise that teaches people to
/// ignore this one.
///
/// Dismissed by tapping, and cleared on sign-out. It is never persisted, so it
/// cannot reappear tomorrow claiming somebody has just been checked in.
/// Close a session left open on an earlier day, and say what happened.
Future<void> _resolveStale(BuildContext context, WidgetRef ref) async {
  final messenger = ScaffoldMessenger.of(context);
  final ok = await ref
      .read(attendanceToggleProvider.notifier)
      .resolveStale();
  if (!context.mounted) return;
  messenger.showSnackBar(
    SnackBar(
      content: Text(
        ok
            ? 'That session has been closed. You can check in now.'
            : 'That session could not be closed. Please ask HR to correct it.',
      ),
    ),
  );
}

class _SignInAttendanceNotice extends ConsumerWidget {
  const _SignInAttendanceNotice();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final attendance = ref.watch(lastSignInAttendanceProvider);
    if (attendance == null) return const SizedBox.shrink();

    final message = attendance.message ?? attendance.describe;
    if (message.isEmpty) return const SizedBox.shrink();
    if (!attendance.wasRecorded && !attendance.isWorthExplaining) {
      return const SizedBox.shrink();
    }

    final palette = context.palette;
    final good = attendance.wasRecorded;
    final at = attendance.checkInAt;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Material(
        color: good ? palette.successContainer : palette.infoContainer,
        borderRadius: AppRadius.cardRadius,
        child: InkWell(
          borderRadius: AppRadius.cardRadius,
          onTap: () =>
              ref.read(lastSignInAttendanceProvider.notifier).state = null,
          child: Padding(
            padding: AppSpacing.card,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  good ? Icons.how_to_reg_outlined : Icons.info_outline,
                  color: good
                      ? palette.onSuccessContainer
                      : palette.onInfoContainer,
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    at != null && good
                        ? '$message Checked in at '
                            '${TimeOfDay.fromDateTime(at.toLocal()).format(context)}.'
                        : message,
                    style: context.text.bodyMedium?.copyWith(
                      color: good
                          ? palette.onSuccessContainer
                          : palette.onInfoContainer,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _AiInsightSection extends ConsumerWidget {
  const _AiInsightSection({required this.insight});

  final HomeAiInsight insight;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // A forward-looking insight must be labelled as a prediction and must
    // carry a confidence value; AiInsightCard asserts this (Instructions §14).
    // If the server marked it a prediction but omitted confidence, degrade to
    // a descriptive insight rather than crash or overstate certainty.
    final isPrediction = insight.isPrediction && insight.confidence != null;

    return AiInsightCard(
      what: insight.headline,
      why: insight.explanation,
      recommendation: insight.recommendation,
      provenance: isPrediction
          ? AiProvenance.predictedRisk
          : AiProvenance.generatedInsight,
      confidence: isPrediction ? insight.confidence : null,
      actions: [
        if (insight.insightId != null)
          AiAction(
            label: 'View Insight',
            onPressed: () {
              ref.read(telemetryProvider).track(
                    AnalyticsEvent.aiRecommendationViewed,
                    parameters: {'screen_id': EmployeeHomeScreen.screenId},
                  );
              context.go(AppRoutes.ai);
            },
          ),
      ],
    );
  }
}
