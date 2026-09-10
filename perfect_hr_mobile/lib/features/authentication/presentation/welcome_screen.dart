import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/config/app_config.dart';
import '../../../core/session/session_controller.dart';
import '../../../core/session/user_role.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../shared/extensions/theme_context.dart';
import '../../../shared/widgets/app_card.dart';

/// AUTH-01 — Welcome.
///
/// Spec: Screen & Wireframe Blueprint §5, UI-UX Specification §45.
///
/// Task 1 scope: the visual structure only. Sign In is inert until Task 3
/// wires Keycloak OIDC + PKCE. The dev role switcher below exists so the
/// role-aware shell can be reviewed before authentication lands, and is
/// compiled out of UAT and production behaviour by [AppConfig.allowsDevTools].
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
              FilledButton(
                onPressed: null, // Task 3 — Authentication.
                child: const Text('Get Started'),
              ),
              const SizedBox(height: AppSpacing.xs),
              TextButton(
                onPressed: null, // Task 3 — Authentication.
                child: const Text('Sign In'),
              ),
              if (showDevTools) ...[
                const SizedBox(height: AppSpacing.lg),
                _DevRoleSwitcher(
                  onSelected: (role) => ref
                      .read(sessionControllerProvider.notifier)
                      .devSwitchRole(role),
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

/// DEV/QA ONLY — enters the shell as a chosen role without authenticating.
class _DevRoleSwitcher extends StatelessWidget {
  const _DevRoleSwitcher({required this.onSelected});

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
                'DEVELOPMENT BUILD',
                style: context.styles.overline
                    .copyWith(color: palette.onWarningContainer),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xxs),
          Text(
            'Enter the role-aware shell without authenticating. '
            'Not present in UAT or production builds.',
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
