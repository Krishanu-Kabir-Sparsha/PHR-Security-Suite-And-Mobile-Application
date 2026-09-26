import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/routing/app_routes.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../authentication/application/auth_providers.dart';
import '../../authentication/application/pair_device_controller.dart';
import '../../../shared/components/async_state_view.dart';
import '../../../shared/extensions/theme_context.dart';
import '../../../shared/widgets/app_card.dart';
import '../../../shared/widgets/status_badge.dart';
import '../../../core/errors/app_failure.dart';
import '../application/authenticator_providers.dart';
import '../application/enrolment_controller.dart';
import '../domain/authenticator_status.dart';

/// SET-02 Security — how this account proves it is you.
///
/// There are two kinds of proof here and the screen's whole job is to keep
/// them distinguishable, because they are not interchangeable:
///
/// **Passkeys** are the W3C standard, created and used through a browser. They
/// can sync to a cloud keychain, which means one passkey may be usable from
/// several machines — good for convenience, and the reason a synced one is
/// flagged where a final-approval role is involved.
///
/// **A paired app** holds a keypair this server issued to one installation on
/// one handset. It never syncs and no browser can use it.
///
/// Neither ceremony runs inside this app. A passkey cannot: Android's WebView
/// has no FIDO2 support, and the native credential API needs the OS vendor to
/// validate an app-to-domain association, which refuses on this deployment
/// with nothing actionable to show the user. So passkeys go through a real
/// browser, and pairing goes through AUTH-05 with a code from the web.
///
/// The app's job is to report status honestly and hand over to whichever of
/// those two actually works.
class SecurityScreen extends ConsumerWidget {
  const SecurityScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final value = ref.watch(authenticatorStatusProvider);

    // Announced here rather than inside the content, so it is seen even while
    // the list below is still showing the previous state.
    ref.listen(enrolmentControllerProvider, (previous, next) {
      if (!next.hasError || !context.mounted) return;
      final failure = asAppFailure(next.error!, next.stackTrace);
      ScaffoldMessenger.of(context)
        ..clearSnackBars()
        ..showSnackBar(SnackBar(content: Text(failure.userMessage)));
    });

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

  // Native passkey enrolment is deliberately NOT offered here.
  //
  // Creating a passkey from inside the app needs the operating system vendor
  // to validate an app-to-domain association on the handset. On this
  // deployment that validation refuses -- "[50152] RP ID cannot be validated"
  // -- and it refuses inside Google Play Services, where there is no
  // server-side fault to correct and no error the user can act on. Offering
  // the button anyway meant a prominent primary action that always failed.
  //
  // The two routes that do work are both here instead: pair this device (its
  // own key, this app, no vendor involved) and the browser, which runs the
  // real WebAuthn ceremony and has worked throughout. EnrolmentController is
  // kept and still tested, so this is one widget away from returning if the
  // association ever validates.

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
          Text(
            'Perfect HR asks for two things when you sign in: your password, '
            'and proof that it is really you. This screen is about the '
            'second one.',
            style: context.text.bodyMedium,
          ),
          const SizedBox(height: AppSpacing.md),
          Text(
            // The privacy promise decides whether somebody is willing to do
            // any of this, so it is stated once, plainly, and up front.
            'Your fingerprint or face is checked by the device itself and '
            'never leaves it.',
            style: context.text.bodySmall?.copyWith(color: palette.inkSecondary),
          ),
          const SizedBox(height: AppSpacing.md),
          // The browser route, which runs the real WebAuthn ceremony and works.
          // A passkey is what a laptop or a hardware key holds, so this stays
          // available even on a phone that is already paired.
          TextButton.icon(
            onPressed: () => _openEnrolment(context, ref),
            icon: const Icon(Icons.open_in_new, size: AppSizes.iconSm),
            label: const Text('Add a passkey using a browser'),
          ),
        ],

        const SizedBox(height: AppSpacing.xl),
        const AppSectionHeader(title: 'THIS DEVICE'),
        const SizedBox(height: AppSpacing.sm),
        const _PairedDeviceCard(),

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

/// Whether this installation holds a key of its own, and how to change that.
///
/// Separate from YOUR DEVICES above, which lists what the *account* holds.
/// Conflating the two is how a user ends up reading "2 devices registered" on
/// a handset that cannot sign in, because both of them are somewhere else.
class _PairedDeviceCard extends ConsumerWidget {
  const _PairedDeviceCard();

  Future<void> _unpair(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Unpair this device?'),
        content: const Text(
          'This device will stop being able to confirm sign-ins and '
          'approvals. Your account keeps its other devices.\n\n'
          'To use this one again you will need a new pairing code from a '
          'browser.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Unpair'),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;

    await ref.read(pairDeviceControllerProvider.notifier).unpair();
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('This device is no longer paired.')),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final palette = context.palette;

    return ref.watch(deviceBindingProvider).maybeWhen(
          orElse: () => const SizedBox.shrink(),
          data: (binding) {
            if (binding == null) {
              return AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Not paired yet', style: context.text.titleMedium),
                    const SizedBox(height: AppSpacing.sm),
                    Text(
                      'Pairing lets this phone confirm it is you with your '
                      'fingerprint, without going through a browser. Get a '
                      'code from Mobile App > Pair My Phone in Perfect HR on '
                      'the web.',
                      style: context.text.bodyMedium,
                    ),
                    const SizedBox(height: AppSpacing.md),
                    FilledButton.icon(
                      onPressed: () => context.push(AppRoutes.pairDevice),
                      icon: const Icon(Icons.smartphone_outlined,
                          size: AppSizes.iconSm),
                      label: const Text('Pair this device'),
                    ),
                  ],
                ),
              );
            }
            return AppCard(
              accent: palette.success,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.verified_user_outlined,
                          color: palette.success, size: AppSizes.iconSm),
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: Text(
                          'Paired as ${binding.label}',
                          style: context.text.titleMedium,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    'Signed in as ${binding.login}. This device holds its own '
                    'security key, kept behind your fingerprint. The key never '
                    'leaves this phone and is not included in backups.',
                    style: context.text.bodyMedium,
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  TextButton(
                    onPressed: () => _unpair(context, ref),
                    child: const Text('Unpair this device'),
                  ),
                ],
              ),
            );
          },
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
          // Different icon per kind, because the list is otherwise three
          // identical rows and the user cannot tell which entry is the phone
          // in their hand from which is a passkey in a cloud keychain.
          Icon(
            device.isPairedApp ? Icons.smartphone : Icons.vpn_key,
            color: palette.inkSecondary,
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(device.label, style: context.text.titleSmall),
                Text(
                  device.isPairedApp
                      ? 'Paired app - used by Perfect HR on that device'
                      : 'Passkey - used by a browser',
                  style: context.text.bodySmall
                      ?.copyWith(color: palette.inkSecondary),
                ),
                if (enrolled != null)
                  Text(
                    'Added ${enrolled.day}/${enrolled.month}/${enrolled.year}',
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


/// The enrolment button, which narrates the two prompts.
///
/// A ceremony raises a system sheet that hides the app, and the user comes back
/// to a screen that has changed. Naming the stage is what tells them whether the
/// prompt they just answered was for the old device or the new one — the single
/// most confusing part of adding a second device.
