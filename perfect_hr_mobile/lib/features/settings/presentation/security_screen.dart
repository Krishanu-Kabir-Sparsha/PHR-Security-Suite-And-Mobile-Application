import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/theme/app_dimensions.dart';
import '../../../shared/components/async_state_view.dart';
import '../../../shared/extensions/theme_context.dart';
import '../../../shared/widgets/app_card.dart';
import '../../../shared/widgets/status_badge.dart';
import '../application/authenticator_providers.dart';
import '../domain/authenticator_status.dart';

/// SET-02 Security — security keys and passkeys.
///
/// The enrolment ceremony deliberately does not happen in this app.
///
/// Android's WebView has no FIDO2 support, so an embedded enrolment page would
/// render its button and then never raise a fingerprint prompt. The ceremony
/// has to run in a real browser, and that is also the better outcome: the
/// credential binds to the same relying party as a desktop enrolment, so a
/// phone enrolled here is the *same* credential the web client sees. It also
/// means no Digital Asset Links file and no dependency on the APK's signing
/// fingerprint, so re-signing the app cannot orphan everyone's credentials.
///
/// The app's job is therefore to report status honestly and hand over to the
/// browser.
class SecurityScreen extends ConsumerWidget {
  const SecurityScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final value = ref.watch(authenticatorStatusProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Security')),
      body: RefreshIndicator(
        onRefresh: () => ref.read(authenticatorStatusProvider.notifier).reload(),
        child: AsyncStateView<AuthenticatorStatus>(
          value: value,
          loadingLabel: 'Checking your security keys',
          onRetry: () => ref.invalidate(authenticatorStatusProvider),
          builder: (status) => _Content(status: status),
        ),
      ),
    );
  }
}

class _Content extends ConsumerWidget {
  const _Content({required this.status});

  final AuthenticatorStatus status;

  Future<void> _openEnrolment(BuildContext context, WidgetRef ref) async {
    final url = status.enrolUrl;
    if (url == null || url.isEmpty) return;

    // externalApplication, never an in-app WebView. See the class doc: a
    // WebView cannot run the ceremony at all.
    final opened = await launchUrl(
      Uri.parse(url),
      mode: LaunchMode.externalApplication,
    );
    if (!context.mounted) return;

    if (!opened) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Could not open a browser on this device.'),
        ),
      );
      return;
    }

    // The browser is a separate app, so there is no callback telling us the
    // ceremony finished. Rather than guess, offer an explicit re-check.
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        duration: const Duration(seconds: 8),
        content: const Text(
          'Finish enrolling in the browser, then tap Refresh.',
        ),
        action: SnackBarAction(
          label: 'Refresh',
          onPressed: () =>
              ref.read(authenticatorStatusProvider.notifier).reload(),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final palette = context.palette;

    return ListView(
      padding: AppSpacing.page,
      children: [
        _SummaryCard(status: status),
        const SizedBox(height: AppSpacing.lg),

        if (!status.configured)
          AppCard(
            accent: palette.warning,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Enrolment is not available yet',
                    style: context.text.titleMedium),
                const SizedBox(height: AppSpacing.sm),
                Text(
                  'Your administrator has not finished setting up security '
                  'keys on the server. There is nothing you need to do.',
                  style: context.text.bodyMedium,
                ),
              ],
            ),
          )
        else ...[
          FilledButton.icon(
            onPressed: () => _openEnrolment(context, ref),
            icon: const Icon(Icons.security),
            label: Text(
              status.enrolled == 0 ? 'Enrol this device' : 'Add another device',
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            status.requiresWebSession
                ? 'This opens your browser, where you may be asked to sign in '
                    'once. Your fingerprint or face is checked by the device '
                    'itself and never leaves it.'
                : 'This opens your browser to complete enrolment.',
            style: context.text.bodySmall?.copyWith(color: palette.inkSecondary),
          ),
        ],

        const SizedBox(height: AppSpacing.xl),
        const AppSectionHeader(title: 'YOUR DEVICES'),
        const SizedBox(height: AppSpacing.sm),

        if (status.devices.isEmpty)
          AppCard(
            child: Text(
              'No security key is enrolled on your account yet.',
              style: context.text.bodyMedium,
            ),
          )
        else
          for (final device in status.devices) ...[
            _DeviceTile(device: device),
            const SizedBox(height: AppSpacing.sm),
          ],
      ],
    );
  }
}

class _SummaryCard extends StatelessWidget {
  const _SummaryCard({required this.status});

  final AuthenticatorStatus status;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    // Three distinct states, and the middle one matters. "Not required" is not
    // the same as "you are done": a user whose role needs no key should not be
    // congratulated for having none.
    final (AppStatus tone, String label, String explanation) = switch (status) {
      _ when status.required_ == 0 => (
          AppStatus.neutral,
          'Not required',
          'Your role does not require a security key. You can still enrol one.',
        ),
      _ when status.sufficient => (
          AppStatus.success,
          'Protected',
          'You have the security keys your role requires.',
        ),
      _ => (
          AppStatus.warning,
          'Action needed',
          status.enrolled == 0
              ? 'Your role requires a security key before you can approve '
                  'anything. Enrol one to continue.'
              : 'Your role requires ${status.required_} devices. Enrol '
                  '${status.outstanding} more, while the one you have still '
                  'works — recovery without a working device needs two other '
                  'approvers.',
        ),
    };

    return AppCard(
      accent: tone == AppStatus.success ? palette.success : palette.warning,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              StatusBadge(label: label, status: tone),
              const Spacer(),
              Text(
                '${status.enrolled} of ${status.required_}',
                style: context.text.titleMedium,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(explanation, style: context.text.bodyMedium),
          if (status.relyingParty != null) ...[
            const SizedBox(height: AppSpacing.sm),
            Text(
              'Keys are registered to ${status.relyingParty}',
              style:
                  context.text.bodySmall?.copyWith(color: palette.inkSecondary),
            ),
          ],
        ],
      ),
    );
  }
}

class _DeviceTile extends StatelessWidget {
  const _DeviceTile({required this.device});

  final EnrolledAuthenticator device;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final enrolled = device.enrolledAt;

    return AppCard(
      child: Row(
        children: [
          Icon(Icons.vpn_key, color: palette.inkSecondary),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(device.label, style: context.text.titleSmall),
                if (enrolled != null)
                  Text(
                    'Enrolled ${enrolled.day}/${enrolled.month}/${enrolled.year}',
                    style: context.text.bodySmall
                        ?.copyWith(color: palette.inkSecondary),
                  ),
                if (device.backedUp)
                  // Said plainly rather than hidden: a synced passkey is not
                  // bound to this handset, which changes what holding it proves.
                  Text(
                    'Synced to a cloud keychain',
                    style: context.text.bodySmall
                        ?.copyWith(color: palette.warning),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
