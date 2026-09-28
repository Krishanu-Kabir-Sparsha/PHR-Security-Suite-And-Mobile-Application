import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/errors/app_failure.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../shared/extensions/theme_context.dart';
import '../../../shared/widgets/app_card.dart';
import '../application/subscription_providers.dart';
import '../domain/workspace_subscription.dart';

/// **SET-03 — Subscription.**
///
/// The workspace's own Perfect HR plan: what it is, when it renews, and how
/// much of it is being used.
///
/// Reached only from More, and only by administrators. The gate is on the
/// server — this screen is drawn for somebody who could, in principle, be
/// refused, so every failure path has to read as an answer rather than as a
/// broken screen.
///
/// The question it exists to answer is one people ask on a phone, usually
/// because a renewal notice arrived on one. Before this, it could only be
/// answered by opening the customer portal on a desktop.
class SubscriptionScreen extends ConsumerWidget {
  const SubscriptionScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(workspaceSubscriptionProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Subscription')),
      body: RefreshIndicator(
        // Usage is measured live on the server, so pulling to refresh is the
        // difference between a figure from a minute ago and one from now.
        onRefresh: () async => ref.refresh(workspaceSubscriptionProvider.future),
        child: async.when(
          loading: () => const _Centred(child: CircularProgressIndicator()),
          error: (error, _) => _ErrorView(error: error),
          data: (result) {
            if (!result.available || result.subscription == null) {
              return const _NoSubscriptionView();
            }
            return _SubscriptionView(subscription: result.subscription!);
          },
        ),
      ),
    );
  }
}

class _Centred extends StatelessWidget {
  const _Centred({required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          const SizedBox(height: AppSpacing.xxxl),
          Center(child: child),
        ],
      );
}

/// A deployment with no plan — an on-premise install, or one provisioned
/// outside the SaaS pipeline.
///
/// Said plainly rather than shown as an empty plan card. "There is no
/// subscription here" and "we could not read your subscription" are different
/// sentences, and only one of them is worth contacting anybody about.
class _NoSubscriptionView extends StatelessWidget {
  const _NoSubscriptionView();

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.md),
      children: [
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'No subscription on this workspace',
                style: context.text.titleMedium,
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                'This workspace is not billed through Perfect HR, so there is '
                'no plan to show. Everything else in the app works normally.',
                style: context.text.bodyMedium
                    ?.copyWith(color: context.palette.inkSecondary),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.error});
  final Object error;

  @override
  Widget build(BuildContext context) {
    // A 403 here is not a fault. It means somebody's access changed between
    // the menu being drawn and this screen opening, and saying so is more
    // useful than "something went wrong".
    final failure = error is AppFailure ? error as AppFailure : null;
    final forbidden = failure?.code == 'subscription_forbidden';

    return ListView(
      padding: const EdgeInsets.all(AppSpacing.md),
      children: [
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                forbidden ? 'Not available to you' : 'Could not load your plan',
                style: context.text.titleMedium,
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                failure?.userMessage ??
                    'Pull down to try again. Your plan is unaffected either '
                        'way — this screen only reads it.',
                style: context.text.bodyMedium
                    ?.copyWith(color: context.palette.inkSecondary),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _SubscriptionView extends StatelessWidget {
  const _SubscriptionView({required this.subscription});

  final WorkspaceSubscription subscription;

  @override
  Widget build(BuildContext context) {
    final plan = subscription;

    return ListView(
      padding: const EdgeInsets.all(AppSpacing.md),
      children: [
        _HealthBanner(subscription: plan),
        const SizedBox(height: AppSpacing.md),
        _PlanCard(subscription: plan),
        if (plan.users != null || plan.storage != null) ...[
          const SizedBox(height: AppSpacing.md),
          _SectionHeader('Usage'),
          _UsageCard(subscription: plan),
        ],
        if (plan.apps.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.md),
          _SectionHeader('What your workspace runs'),
          _AppsCard(apps: plan.apps),
        ],
        if (plan.manageUrl != null || plan.upgradeUrl != null) ...[
          const SizedBox(height: AppSpacing.md),
          _PortalActions(subscription: plan),
        ],
        if (plan.syncedAt != null) ...[
          const SizedBox(height: AppSpacing.md),
          // These facts come from a snapshot written by the billing server,
          // not from a live call. Saying when they were last confirmed is the
          // difference between a stale number and a wrong one.
          Text(
            'Plan details last confirmed ${_friendlyDateTime(plan.syncedAt!)}. '
            'Usage figures above are measured now.',
            style: context.text.bodySmall
                ?.copyWith(color: context.palette.inkTertiary),
          ),
        ],
        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }
}

/// The one-line verdict, coloured only where something needs doing.
class _HealthBanner extends StatelessWidget {
  const _HealthBanner({required this.subscription});

  final WorkspaceSubscription subscription;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final health = subscription.health;

    // Deliberately narrow. Amber is reserved for a trial or an approaching
    // renewal; red for a service that has actually stopped. A banner that is
    // coloured every day is one nobody reads.
    final (Color tint, Color ground, IconData icon) = switch (health) {
      SubscriptionHealth.suspended || SubscriptionHealth.ended => (
          palette.onDangerContainer,
          palette.dangerContainer,
          Icons.error_outline,
        ),
      SubscriptionHealth.trial || SubscriptionHealth.renewing => (
          palette.onWarningContainer,
          palette.warningContainer,
          Icons.schedule_outlined,
        ),
      SubscriptionHealth.setup => (
          palette.onInfoContainer,
          palette.infoContainer,
          Icons.hourglass_empty_outlined,
        ),
      _ => (
          palette.onSuccessContainer,
          palette.successContainer,
          Icons.check_circle_outline,
        ),
    };

    return AppCard(
      background: ground,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: tint, size: AppSizes.iconMd),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              subscription.headline,
              style: context.text.bodyMedium
                  ?.copyWith(color: tint, fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }
}

class _PlanCard extends StatelessWidget {
  const _PlanCard({required this.subscription});

  final WorkspaceSubscription subscription;

  @override
  Widget build(BuildContext context) {
    final plan = subscription;
    final palette = context.palette;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(
                  plan.planName ?? 'Your plan',
                  style: context.text.titleLarge,
                ),
              ),
              if (plan.isTrial)
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.xs,
                    vertical: AppSpacing.xxs,
                  ),
                  decoration: BoxDecoration(
                    color: palette.warningContainer,
                    borderRadius: BorderRadius.circular(AppRadius.pill),
                  ),
                  child: Text(
                    'Free trial',
                    style: context.text.labelSmall
                        ?.copyWith(color: palette.onWarningContainer),
                  ),
                ),
            ],
          ),
          if (plan.price != null) ...[
            const SizedBox(height: AppSpacing.xxs),
            Text(
              plan.price!.display,
              style: context.text.titleMedium?.copyWith(color: palette.brand),
            ),
          ],
          const SizedBox(height: AppSpacing.sm),
          Divider(color: palette.border, height: AppSpacing.md),
          if (plan.planLabel != null) _Fact(label: 'Billing', value: plan.planLabel!),
          if (plan.statusLabel != null)
            _Fact(label: 'Status', value: plan.statusLabel!),
          if (plan.startedOn != null)
            _Fact(label: 'Started', value: _friendlyDate(plan.startedOn!)),
          if (plan.renewsOn != null)
            _Fact(
              label: plan.isTrial ? 'Trial ends' : 'Renews',
              value: _withCountdown(plan.renewsOn!, plan.daysLeft),
            ),
          if (plan.reference != null)
            _Fact(label: 'Reference', value: plan.reference!),
        ],
      ),
    );
  }

  /// "1 January 2027 · in 97 days", where the countdown is known and future.
  ///
  /// A negative count is dropped rather than rendered as "in -3 days" — the
  /// headline above already says the plan has ended, and repeating it as
  /// arithmetic adds nothing.
  static String _withCountdown(String date, int? daysLeft) {
    final friendly = _friendlyDate(date);
    if (daysLeft == null || daysLeft < 0) return friendly;
    if (daysLeft == 0) return '$friendly · today';
    return '$friendly · in $daysLeft ${daysLeft == 1 ? 'day' : 'days'}';
  }
}

class _UsageCard extends StatelessWidget {
  const _UsageCard({required this.subscription});

  final WorkspaceSubscription subscription;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (subscription.users != null)
            _QuotaBar(label: 'People with a login', quota: subscription.users!),
          if (subscription.users != null && subscription.storage != null)
            const SizedBox(height: AppSpacing.md),
          if (subscription.storage != null)
            _QuotaBar(label: 'Storage', quota: subscription.storage!),
          const SizedBox(height: AppSpacing.sm),
          Text(
            // Said explicitly, because a progress bar next to a limit is read
            // as a threshold that will stop something. Here it never does.
            'Going over a limit never stops anyone working. We will get in '
            'touch about your plan instead.',
            style: context.text.bodySmall
                ?.copyWith(color: context.palette.inkTertiary),
          ),
        ],
      ),
    );
  }
}

class _QuotaBar extends StatelessWidget {
  const _QuotaBar({required this.label, required this.quota});

  final String label;
  final QuotaUsage quota;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final tint = quota.nearLimit ? palette.warning : palette.brand;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(child: Text(label, style: context.text.bodyMedium)),
            Text(
              quota.display,
              style: context.text.bodyMedium?.copyWith(
                fontWeight: FontWeight.w600,
                // Digits that line up column to column, so two bars can be
                // compared at a glance.
                fontFeatures: const [FontFeature.tabularFigures()],
              ),
            ),
          ],
        ),
        if (!quota.unlimited && quota.ratio != null) ...[
          const SizedBox(height: AppSpacing.xxs),
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadius.pill),
            child: LinearProgressIndicator(
              value: quota.ratio,
              minHeight: 6,
              backgroundColor: palette.surfaceAlt,
              valueColor: AlwaysStoppedAnimation<Color>(tint),
            ),
          ),
        ],
        if (quota.unlimited) ...[
          const SizedBox(height: AppSpacing.xxs),
          Text(
            'No limit on your plan',
            style:
                context.text.bodySmall?.copyWith(color: palette.inkTertiary),
          ),
        ],
      ],
    );
  }
}

class _AppsCard extends StatelessWidget {
  const _AppsCard({required this.apps});

  final List<String> apps;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    return AppCard(
      child: Wrap(
        spacing: AppSpacing.xs,
        runSpacing: AppSpacing.xs,
        children: [
          for (final app in apps)
            Container(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.xs,
                vertical: AppSpacing.xxs,
              ),
              decoration: BoxDecoration(
                color: palette.surfaceAlt,
                borderRadius: BorderRadius.circular(AppRadius.sm),
                border: Border.all(color: palette.border),
              ),
              child: Text(app, style: context.text.bodySmall),
            ),
        ],
      ),
    );
  }
}

/// Links back to the customer portal, where the plan is actually changed.
///
/// The app deliberately does not offer to upgrade in place. Changing a plan is
/// a purchase, and a purchase belongs where the terms, the invoice history and
/// the payment methods already are.
class _PortalActions extends StatelessWidget {
  const _PortalActions({required this.subscription});

  final WorkspaceSubscription subscription;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        if (subscription.manageUrl != null)
          SizedBox(
            width: double.infinity,
            child: FilledButton.tonalIcon(
              onPressed: () => _open(context, subscription.manageUrl!),
              icon: const Icon(Icons.open_in_new),
              label: const Text('Manage plan'),
            ),
          ),
        if (subscription.upgradeUrl != null) ...[
          const SizedBox(height: AppSpacing.xs),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () => _open(context, subscription.upgradeUrl!),
              icon: const Icon(Icons.arrow_upward),
              label: const Text('Upgrade or add storage'),
            ),
          ),
        ],
      ],
    );
  }

  Future<void> _open(BuildContext context, String url) async {
    final uri = Uri.tryParse(url);
    // A malformed or unopenable link is reported rather than swallowed: the
    // button visibly did nothing otherwise, which reads as a broken app.
    final opened = uri != null &&
        await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!opened && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("Couldn't open the customer portal on this device."),
        ),
      );
    }
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader(this.title);
  final String title;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.xs),
        child: Text(
          title,
          style: context.text.labelLarge
              ?.copyWith(color: context.palette.inkSecondary),
        ),
      );
}

class _Fact extends StatelessWidget {
  const _Fact({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.xxs),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 108,
              child: Text(
                label,
                style: context.text.bodySmall
                    ?.copyWith(color: context.palette.inkSecondary),
              ),
            ),
            Expanded(child: Text(value, style: context.text.bodyMedium)),
          ],
        ),
      );
}

/// `2027-01-01` as `1 January 2027`, or unchanged when it will not parse.
///
/// These are plain dates from the server, with no time and no zone, so they are
/// formatted rather than converted — running them through the local-time path
/// would shift a renewal date across a day boundary for anyone west of UTC.
String _friendlyDate(String raw) {
  final parsed = DateTime.tryParse(raw);
  if (parsed == null) return raw;
  return DateFormat.yMMMMd().format(parsed);
}

String _friendlyDateTime(String raw) {
  final parsed = DateTime.tryParse(raw);
  if (parsed == null) return raw;
  return DateFormat.yMMMd().add_jm().format(parsed);
}
