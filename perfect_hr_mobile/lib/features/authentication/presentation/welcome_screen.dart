import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/config/app_config.dart';
import '../../../core/data/data_providers.dart';
import '../../../core/session/session_controller.dart';
import '../../../core/routing/app_routes.dart';
import '../../../core/session/user_role.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../shared/extensions/theme_context.dart';
import '../../../shared/widgets/app_card.dart';

/// AUTH-01 — Welcome.
///
/// Spec: Screen & Wireframe Blueprint §5, UI-UX Specification §45.
///
/// Sign In routes to AUTH-01 proper, which authenticates against the Odoo
/// mobile API. (Keycloak was the original plan and is no longer used: the
/// client only ever needed a bearer token and a refresh endpoint.)
///
/// The dev role switcher below exists so the role-aware shell can be reviewed
/// without a server, and is absent from UAT and production via
/// [AppConfig.allowsDevTools].
class WelcomeScreen extends ConsumerWidget {
  const WelcomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final palette = context.palette;
    final showDevTools = AppConfig.current.allowsDevTools;

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: AppSpacing.page,
          child: Column(
            children: [
              const Spacer(),
              Container(
                width: 72,
                height: 72,
                decoration: BoxDecoration(
                  color: palette.brand,
                  borderRadius: BorderRadius.circular(AppRadius.lg),
                ),
                child: Icon(
                  Icons.groups_2_outlined,
                  color: palette.onBrand,
                  size: 36,
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              Text(
                'PERFECT HR',
                style: context.text.headlineSmall
                    ?.copyWith(letterSpacing: 1.5, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                'AI-Powered Workforce Companion',
                style: context.text.bodyMedium,
                textAlign: TextAlign.center,
              ),
              const Spacer(),
              // One action, not two. There is no self-service sign-up in an
              // HR product -- accounts are created by HR -- so a separate
              // "Get Started" could only lead to this same screen, and two
              // buttons that do the same thing make people hesitate over
              // which one is correct.
              FilledButton(
                onPressed: () => context.go(AppRoutes.login),
                child: const Text('Sign In'),
              ),
              if (showDevTools) ...[
                const SizedBox(height: AppSpacing.lg),
                _DesignPreviewSwitcher(
                  onSelected: (role) {
                    // Mock data goes with a fabricated role, and has to. This
                    // session has no token behind it, so every live request
                    // would come back 401 and the whole shell would render as
                    // "session expired" -- which looks like a broken app
                    // rather than a preview. A fake user sees fake data, and
                    // it is labelled as such on every screen.
                    ref.read(dataSourceModeProvider.notifier).useMocks();
                    ref
                        .read(sessionControllerProvider.notifier)
                        .devSwitchRole(role);
                  },
                ),
              ],
              const SizedBox(height: AppSpacing.md),
            ],
          ),
        ),
      ),
    );
  }
}

/// DEV/QA ONLY — renders the shell for a chosen persona, on sample data.
///
/// **This is a layout preview, not a role preview, and the copy says so.**
///
/// It cannot show real permissions and must not appear to: there is no token,
/// so nothing can be asked of the server, and the fabricated permission set it
/// used to carry was pure invention — it granted things the signed-in user
/// might not have and withheld things they did.
///
/// The real thing lives in **More → View as role**, which asks the server what
/// a Plaza role actually permits, is restricted to catalog administrators, and
/// keeps a banner on screen throughout. Use that to check a role's
/// configuration; use this only to look at the shell without a server.
class _DesignPreviewSwitcher extends StatelessWidget {
  const _DesignPreviewSwitcher({required this.onSelected});

  final ValueChanged<UserRole> onSelected;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    return AppCard(
      background: palette.warningContainer,
      borderColor: palette.warning,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.construction_outlined,
                size: AppSizes.iconSm,
                color: palette.onWarningContainer,
              ),
              const SizedBox(width: AppSpacing.xs),
              Text(
                'LAYOUT PREVIEW · SAMPLE DATA',
                style: context.styles.overline
                    .copyWith(color: palette.onWarningContainer),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xxs),
          Text(
            'Renders the shell for a persona using sample data, without '
            'signing in. It does NOT show real permissions — sign in and use '
            'More > View as role for that. Absent from UAT and production.',
            style: context.text.bodySmall
                ?.copyWith(color: palette.onWarningContainer),
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.xs,
            runSpacing: AppSpacing.xs,
            children: [
              for (final role in UserRole.values)
                OutlinedButton(
                  onPressed: () => onSelected(role),
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size(0, 40),
                    padding:
                        const EdgeInsets.symmetric(horizontal: AppSpacing.sm),
                    foregroundColor: palette.onWarningContainer,
                    side: BorderSide(color: palette.warning),
                  ),
                  child: Text(_shortLabel(role)),
                ),
            ],
          ),
        ],
      ),
    );
  }

  static String _shortLabel(UserRole role) => switch (role) {
        UserRole.employee => 'Employee',
        UserRole.manager => 'Manager',
        UserRole.hr => 'HR',
        UserRole.chro => 'CHRO',
        UserRole.executive => 'CEO',
        UserRole.superAdmin => 'Super Admin',
      };
}
