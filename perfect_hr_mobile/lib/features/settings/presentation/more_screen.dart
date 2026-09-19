import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/capabilities/app_capabilities.dart';
import '../../../core/capabilities/capability_providers.dart';
import '../../../core/capabilities/model_access.dart';
import '../../../core/config/app_config.dart';
import '../../../core/constants/screen_ids.dart';
import '../../../core/data/data_providers.dart';
import '../../../core/routing/app_routes.dart';
import '../../../core/session/session_controller.dart';
import '../../../core/session/session_state.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../features/authentication/application/auth_providers.dart';
import '../../../shared/extensions/theme_context.dart';
import '../../../shared/widgets/app_card.dart';

/// **SET-01 — More.**
///
/// Spec: Screen & Wireframe Blueprint §5 (SET-01), UI-UX Specification §5.
///
/// Built ahead of the rest of the settings area because two things a shipped
/// app cannot be without were both trapped behind it:
///
/// * **Sign out.** There was no way to leave a session from anywhere in the
///   app. On a shared or lost phone that is not a missing convenience, it is a
///   security defect: the only way out was to clear app data.
/// * **Security & devices** (SET-02). The screen exists and works, but its
///   route is `/more/security`, so while More was a placeholder the whole
///   security-key enrolment flow was unreachable from the app.
///
/// The "Coming soon" section is deliberate rather than hidden. The user needs
/// to be able to tell "this app cannot do that yet" apart from "this app is
/// broken", and silence reads as the second.
class MoreScreen extends ConsumerWidget {
  const MoreScreen({super.key});

  static const String screenId = ScreenIds.more;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(activeUserProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('More')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.md,
          AppSpacing.md,
          AppSpacing.md,
          AppSpacing.xxl,
        ),
        children: [
          if (user != null) _ProfileCard(user: user),
          const SizedBox(height: AppSpacing.lg),

          const _SectionHeader('Your roles'),
          const _RolesCard(),
          const SizedBox(height: AppSpacing.lg),

          const _RolePreviewSection(),
          const _DivergenceSection(),

          // Leave has no bottom-nav tab of its own — it lives under Requests,
          // which is still a placeholder — so without an entry here the only
          // routes to it are two tiles on Home. A feature reachable only from
          // one screen is a feature people stop finding.
          if (ref.watch(hasFeatureProvider(AppFeature.leave))) ...[
            const _SectionHeader('Your HR'),
            _MoreTile(
              icon: Icons.event_available_outlined,
              title: 'Leave',
              subtitle: 'Balances, apply, and the status of your requests',
              onTap: () => context.push(AppRoutes.leave),
            ),
            const SizedBox(height: AppSpacing.lg),
          ],

          const _SectionHeader('Account'),
          _MoreTile(
            icon: Icons.shield_outlined,
            title: 'Security & devices',
            subtitle: 'Security keys and passkeys for your account',
            // push, not go: this is a detail screen within the More branch and
            // the user must be able to come back with the system back gesture.
            onTap: () => context.push(AppRoutes.security),
          ),
          _MoreTile(
            icon: Icons.logout_outlined,
            title: 'Sign out',
            subtitle: 'Ends this session on this device only',
            destructive: true,
            onTap: () => _confirmSignOut(context, ref),
          ),

          const SizedBox(height: AppSpacing.lg),
          const _SectionHeader('Modules'),
          const _AvailabilityCard(),

          const SizedBox(height: AppSpacing.lg),
          const _SectionHeader('About'),
          const _AboutCard(),
        ],
      ),
    );
  }

  /// Sign-out is confirmed because it is not cheap to undo here: it revokes the
  /// token server-side and purges the local cache, so an accidental tap costs a
  /// full re-authentication and a cold re-sync on a slow connection.
  Future<void> _confirmSignOut(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Sign out?'),
        content: const Text(
          'You will need your username and password to sign in again. '
          'Other devices stay signed in.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Sign out'),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    // signOut revokes the token at the server, clears the Keystore entry and
    // — via cacheLifecycleProvider watching the session — purges this user's
    // cached data from the device. The router then redirects to Welcome on its
    // own, because the session state it keys on has changed.
    await ref.read(signInControllerProvider.notifier).signOut();
  }
}

class _ProfileCard extends StatelessWidget {
  const _ProfileCard({required this.user});

  final SessionUser user;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    return AppCard(
      child: Row(
        children: [
          CircleAvatar(
            radius: AppSizes.avatarMd / 2,
            backgroundColor: palette.brandContainer,
            foregroundImage: user.avatarUrl == null
                ? null
                : NetworkImage(_absolute(user.avatarUrl!)),
            child: Icon(
              Icons.person_outline,
              color: palette.onBrandContainer,
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  user.displayName,
                  style: context.text.titleMedium,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                if (user.jobTitle != null)
                  Text(
                    user.jobTitle!,
                    style: context.text.bodySmall,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                const SizedBox(height: AppSpacing.xxs),
                Text(
                  '${user.tenantName} · ${user.role.experienceLabel}',
                  style: context.text.bodySmall
                      ?.copyWith(color: palette.inkTertiary),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// The API returns the avatar as a server-relative path (`/web/image/...`),
  /// which `NetworkImage` cannot resolve on its own. The API base URL carries
  /// the `/api/mobile/v1` suffix, so the origin has to be taken from it rather
  /// than the whole string being used as a prefix.
  static String _absolute(String path) {
    if (path.startsWith('http')) return path;
    final base = Uri.parse(AppConfig.current.apiBaseUrl);
    return base.replace(path: path, query: null).toString();
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader(this.title);

  final String title;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xs),
      child: Text(
        title.toUpperCase(),
        style: context.styles.overline
            .copyWith(color: context.palette.inkTertiary),
      ),
    );
  }
}

class _MoreTile extends StatelessWidget {
  const _MoreTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
    this.destructive = false,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;
  final bool destructive;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final tint = destructive ? palette.danger : palette.ink;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xs),
      child: AppCard(
        onTap: onTap,
        semanticLabel: title,
        child: Row(
          children: [
            Icon(icon, size: AppSizes.iconMd, color: tint),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: context.text.bodyLarge?.copyWith(color: tint),
                  ),
                  Text(
                    subtitle,
                    style: context.text.bodySmall
                        ?.copyWith(color: palette.inkTertiary),
                  ),
                ],
              ),
            ),
            Icon(
              Icons.chevron_right,
              size: AppSizes.iconMd,
              color: palette.inkTertiary,
            ),
          ],
        ),
      ),
    );
  }
}

/// What this server offers, and how much of it the app has caught up with.
///
/// Read from `GET /me/capabilities`, never hard-coded. The app must not claim a
/// feature the deployment cannot serve, and equally must not hide one it can.
///
/// Three states are shown separately because they call for three different
/// actions, and collapsing them into one "coming soon" list hid that:
///
/// * **Ready** — built and available to you now.
/// * **On your server, not yet in the app** — the Odoo module is installed and
///   the data is there; this is app work, and it is the build queue.
/// * **Not installed** — nothing to build until the module is added in Odoo.
///   No amount of app work makes these appear.
class _AvailabilityCard extends ConsumerWidget {
  const _AvailabilityCard();

  /// Features with a real screen behind them today. Every other feature the
  /// server reports is queued rather than available.
  ///
  /// Update this in the same commit that adds the screen — it is what moves a
  /// feature from "coming to the app" to "ready to use", and a stale entry here
  /// tells the user something untrue in both directions.
  static const Set<AppFeature> _built = {
    AppFeature.securityKeys,
    AppFeature.attendance,
    AppFeature.leave,
  };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(capabilitiesProvider);
    final capabilities = async.valueOrNull;

    if (async.isLoading && capabilities == null) {
      return const AppCard(
        child: Row(
          children: [
            SizedBox(
              width: AppSizes.iconSm,
              height: AppSizes.iconSm,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            SizedBox(width: AppSpacing.sm),
            Text('Checking what your server offers'),
          ],
        ),
      );
    }

    if (capabilities == null || capabilities.features.isEmpty) {
      // Either the server predates the capabilities endpoint or the call did
      // not get through. Saying so is better than an empty card, which reads
      // as "your server has nothing".
      return AppCard(
        child: Text(
          "The app couldn't read your server's module list. Everything you can "
          'see elsewhere in the app is still real data from your account.',
          style: context.text.bodySmall,
        ),
      );
    }

    final ready = <AppFeature>[];
    final queued = <AppFeature>[];
    for (final feature in AppFeature.values) {
      if (!capabilities.has(feature)) continue;
      (_built.contains(feature) ? ready : queued).add(feature);
    }
    final absent = AppFeature.values
        .where((f) => !capabilities.has(f))
        .toList();

    final palette = context.palette;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!capabilities.hasEmployeeRecord) ...[
            Text(
              'Your login is not linked to an employee record yet, so your own '
              'attendance and leave cannot be shown. Ask HR to complete your '
              'profile in Perfect HR.',
              style: context.text.bodySmall
                  ?.copyWith(color: palette.onWarningContainer),
            ),
            const SizedBox(height: AppSpacing.sm),
          ],
          _group(
            context,
            'Ready to use',
            ready,
            Icons.check_circle_outline,
            palette.success,
          ),
          _group(
            context,
            'On your server, coming to the app',
            queued,
            Icons.schedule_outlined,
            palette.inkTertiary,
          ),
          _group(
            context,
            'Not installed on your server',
            absent,
            Icons.remove_circle_outline,
            palette.inkTertiary,
            showModule: true,
          ),
        ],
      ),
    );
  }

  Widget _group(
    BuildContext context,
    String title,
    List<AppFeature> features,
    IconData icon,
    Color tint, {
    bool showModule = false,
  }) {
    if (features.isEmpty) return const SizedBox.shrink();
    final palette = context.palette;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: context.text.bodySmall
                ?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: AppSpacing.xxs),
          for (final feature in features)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xxs),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(icon, size: AppSizes.iconSm, color: tint),
                  const SizedBox(width: AppSpacing.xs),
                  Expanded(
                    child: Text(
                      showModule && feature.odooModule != null
                          ? '${feature.label} — needs ${feature.odooModule}'
                          : feature.label,
                      style: context.text.bodySmall
                          ?.copyWith(color: palette.inkSecondary),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

/// Build and connection facts.
///
/// Present so that "am I looking at real data?" is answerable inside the app.
/// Without it the only way to tell live data from mock data is to recognise the
/// mock names, and the previous build shipped with a dev switcher that silently
/// put a real session on fabricated figures.
class _AboutCard extends ConsumerWidget {
  const _AboutCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final config = AppConfig.current;
    final mode = ref.watch(dataSourceModeProvider);
    final modules = ref.watch(resolvedCapabilitiesProvider).hrModulesInstalled;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _fact(context, 'Server', Uri.parse(config.apiBaseUrl).host),
          _fact(context, 'Build', config.flavor.name),
          _fact(
            context,
            'Data',
            mode == DataSourceMode.live
                ? 'Live from your account'
                : 'Sample data (development)',
            warn: mode != DataSourceMode.live,
          ),
          // The installed HR modules, verbatim. This answers "what does my
          // server actually run?" from the phone, without needing someone with
          // Odoo backend access to go and look.
          if (modules.isNotEmpty)
            _fact(context, 'HR modules', modules.join(', ')),
        ],
      ),
    );
  }

  Widget _fact(
    BuildContext context,
    String label,
    String value, {
    bool warn = false,
  }) {
    final palette = context.palette;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xxs),
      child: Row(
        children: [
          SizedBox(
            width: 72,
            child: Text(
              label,
              style: context.text.bodySmall
                  ?.copyWith(color: palette.inkTertiary),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: context.text.bodySmall?.copyWith(
                color: warn ? palette.warning : palette.ink,
                fontWeight: warn ? FontWeight.w600 : null,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// The Plaza Model roles the user holds, and what each one obliges.
///
/// Shown because a role is the answer to most "why can't I do X?" questions,
/// and because the approval tier is the reason someone is asked to enrol a
/// security key — a demand that is otherwise unexplained and therefore ignored.
class _RolesCard extends ConsumerWidget {
  const _RolesCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final roles = ref.watch(plazaRolesProvider);
    final palette = context.palette;

    if (roles.isEmpty) {
      return AppCard(
        child: Text(
          'No Perfect HR role is assigned to your account. You can still use '
          'anything your Odoo groups permit — roles add approval duties on '
          'top of that.',
          style: context.text.bodySmall,
        ),
      );
    }

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final role in roles) ...[
            Row(
              children: [
                Expanded(
                  child: Text(role.name, style: context.text.bodyLarge),
                ),
                if (role.approvalTier.isApprover)
                  Text(
                    role.approvalTier.label,
                    style: context.text.bodySmall
                        ?.copyWith(color: palette.warning),
                  ),
              ],
            ),
            Text(
              role.code,
              style: context.text.bodySmall
                  ?.copyWith(color: palette.inkTertiary),
            ),
            for (final duty in role.duties)
              if (duty.transactionType != null)
                Padding(
                  padding: const EdgeInsets.only(top: AppSpacing.xxs),
                  child: Text(
                    // Spelled out because "create" and "approve" on the same
                    // transaction class is the thing the segregation-of-duties
                    // control exists to prevent, and a person should be able to
                    // see which side of it they are on.
                    '${duty.capability == RoleCapability.approve ? 'Approves' : 'Prepares'}'
                    ' · ${_transactionLabel(duty.transactionType!)}',
                    style: context.text.bodySmall,
                  ),
                ),
            if (role.requiresWebauthn)
              Padding(
                padding: const EdgeInsets.only(top: AppSpacing.xxs),
                child: Text(
                  'This role requires a registered security key.',
                  style: context.text.bodySmall
                      ?.copyWith(color: palette.warning),
                ),
              ),
            if (role != roles.last) ...[
              const SizedBox(height: AppSpacing.xs),
              Divider(color: palette.border, height: 1),
              const SizedBox(height: AppSpacing.xs),
            ],
          ],
        ],
      ),
    );
  }

  static String _transactionLabel(TransactionType type) => switch (type) {
        TransactionType.leaveRequest => 'Leave requests',
        TransactionType.attendanceRecord => 'Attendance records',
        TransactionType.payrollRun => 'Payroll runs',
        TransactionType.employeeMaster => 'Employee records',
        TransactionType.recruitment => 'Recruitment',
        TransactionType.saleOrder => 'Sales orders',
        TransactionType.purchaseOrder => 'Purchase orders',
        TransactionType.customerInvoice => 'Customer invoices',
        TransactionType.vendorBill => 'Vendor bills',
        TransactionType.vendorPayment => 'Vendor payments',
        TransactionType.journalEntry => 'Journal entries',
        TransactionType.stockMove => 'Stock movements',
        TransactionType.masterData => 'Master data',
      };
}

/// Where the Plaza catalog and Odoo's real permissions disagree.
///
/// Renders nothing for anyone who cannot act on it — the server sends an empty
/// list to everyone outside compliance, so this is a second line of defence
/// rather than the control itself.
///
/// Excess access is listed first and separately. "Granted but never written
/// down" is a finding someone must chase; "declared but not granted" only means
/// a feature will be missing from somebody's app.
class _DivergenceSection extends ConsumerWidget {
  const _DivergenceSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final findings = ref.watch(divergenceProvider);
    if (findings.isEmpty) return const SizedBox.shrink();

    final palette = context.palette;
    final excess = findings.where((f) => f.isExcessAccess).toList();
    final gaps = findings.where((f) => !f.isExcessAccess).toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionHeader('Access review'),
        AppCard(
          accent: excess.isEmpty ? palette.info : palette.warning,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Your access does not match the role catalog. The catalog is '
                'what the monthly review reads, so it would sign off on a '
                'description of the system that is not accurate.',
                style: context.text.bodySmall,
              ),
              if (excess.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  'MORE ACCESS THAN DECLARED',
                  style: context.styles.overline
                      .copyWith(color: palette.warning),
                ),
                for (final finding in excess)
                  Padding(
                    padding: const EdgeInsets.only(top: AppSpacing.xxs),
                    child: Text(
                      '${finding.model} — ${finding.summary}',
                      style: context.text.bodySmall,
                    ),
                  ),
              ],
              if (gaps.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  'DECLARED BUT NOT GRANTED',
                  style: context.styles.overline
                      .copyWith(color: palette.inkTertiary),
                ),
                for (final finding in gaps)
                  Padding(
                    padding: const EdgeInsets.only(top: AppSpacing.xxs),
                    child: Text(
                      '${finding.model} — ${finding.summary}',
                      style: context.text.bodySmall
                          ?.copyWith(color: palette.inkTertiary),
                    ),
                  ),
              ],
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
      ],
    );
  }
}

/// **Role preview.** What a Plaza role actually permits, per the server.
///
/// Distinct from the layout preview on the Welcome screen, which fabricates a
/// persona and shows sample data. This asks the server to answer as if the user
/// held only the chosen role, and the answer comes from `ir.model.access` for
/// that role's backing group — so a preview that looks wrong is a real finding
/// about the configuration, not a quirk of the app.
///
/// Offered only to catalog administrators: the list of roles is empty for
/// everyone else, because enumerating the access model of roles you do not hold
/// is reconnaissance rather than a feature. The server refuses independently.
class _RolePreviewSection extends ConsumerWidget {
  const _RolePreviewSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final roles = ref.watch(assignableRolesProvider);
    final previewing = ref.watch(previewingRoleProvider);

    if (roles.isEmpty && previewing == null) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionHeader('View as role'),
        _MoreTile(
          icon: Icons.visibility_outlined,
          title: previewing == null ? 'Preview a role' : 'Previewing: ${previewing.name}',
          subtitle: previewing == null
              ? 'See what a role in the security catalog actually permits'
              : 'Tap to change or return to your own access',
          onTap: () => _pick(context, ref, roles),
        ),
        const SizedBox(height: AppSpacing.lg),
      ],
    );
  }

  Future<void> _pick(
    BuildContext context,
    WidgetRef ref,
    List<AssignableRole> roles,
  ) async {
    final selected = await showModalBottomSheet<String?>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            ListTile(
              leading: const Icon(Icons.person_outline),
              title: const Text('My own access'),
              subtitle: const Text('Stop previewing'),
              // Empty string rather than null: null is also what a dismissed
              // sheet returns, and "stop previewing" must not be silently lost
              // when someone taps it deliberately.
              onTap: () => Navigator.of(sheetContext).pop(''),
            ),
            const Divider(height: 1),
            for (final role in roles)
              ListTile(
                title: Text(role.name),
                subtitle: Text(
                  role.approvalTier.isApprover
                      ? '${role.code} · ${role.approvalTier.label}'
                      : role.code,
                ),
                onTap: () => Navigator.of(sheetContext).pop(role.code),
              ),
          ],
        ),
      ),
    );

    if (selected == null) return;
    ref.read(previewRoleProvider.notifier).state =
        selected.isEmpty ? null : selected;
  }
}

/// Shown on every screen while a role preview is active.
///
/// Persistent and deliberately loud. A preview that looks like the real thing
/// is worse than no preview: an administrator could conclude their own access
/// was wrong and change a configuration that was never broken.
class RolePreviewBanner extends ConsumerWidget {
  const RolePreviewBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final previewing = ref.watch(previewingRoleProvider);
    if (previewing == null) return const SizedBox.shrink();

    final palette = context.palette;

    return Material(
      color: palette.warningContainer,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.md,
            vertical: AppSpacing.xs,
          ),
          child: Row(
            children: [
              Icon(
                Icons.visibility_outlined,
                size: AppSizes.iconSm,
                color: palette.onWarningContainer,
              ),
              const SizedBox(width: AppSpacing.xs),
              Expanded(
                child: Text(
                  'Viewing as ${previewing.name} — not your own access',
                  style: context.text.bodySmall
                      ?.copyWith(color: palette.onWarningContainer),
                ),
              ),
              TextButton(
                onPressed: () =>
                    ref.read(previewRoleProvider.notifier).state = null,
                child: const Text('Exit'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
