import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/errors/app_failure.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../shared/extensions/theme_context.dart';
import '../application/pair_device_controller.dart';

/// AUTH-05 Pair this device.
///
/// Reachable without signing in, and that is the point: a new handset cannot
/// sign in until it is paired, so a screen behind the session would be a door
/// locked from the inside. The pairing code carries the authority instead.
///
/// The copy names where the code comes from rather than assuming the user
/// knows. Someone reaching this screen is usually holding a phone and looking
/// at a browser on another machine, and "enter your pairing code" without
/// saying where to find one is the most common way this flow stalls.
class PairDeviceScreen extends ConsumerStatefulWidget {
  const PairDeviceScreen({super.key});

  @override
  ConsumerState<PairDeviceScreen> createState() => _PairDeviceScreenState();
}

class _PairDeviceScreenState extends ConsumerState<PairDeviceScreen> {
  final _formKey = GlobalKey<FormState>();
  final _loginController = TextEditingController();
  final _codeController = TextEditingController();
  final _labelController = TextEditingController(text: 'My phone');

  @override
  void dispose() {
    _loginController.dispose();
    _codeController.dispose();
    _labelController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    FocusScope.of(context).unfocus();

    final name = await ref.read(pairDeviceControllerProvider.notifier).pair(
          login: _loginController.text,
          code: _codeController.text,
          deviceLabel: _labelController.text,
        );
    if (name == null || !mounted) return;

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('This device is now paired to $name.')),
    );
    // Straight to sign-in: pairing is a step on the way in, not a destination,
    // and the account is already named on the next screen's first field.
    context.go('/login');
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(pairDeviceControllerProvider);
    final busy = state.isLoading;
    final palette = context.palette;

    return Scaffold(
      appBar: AppBar(title: const Text('Pair this device')),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: AppSpacing.page,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _Steps(palette: palette),
                    const SizedBox(height: AppSpacing.xl),

                    TextFormField(
                      controller: _loginController,
                      enabled: !busy,
                      autocorrect: false,
                      textInputAction: TextInputAction.next,
                      keyboardType: TextInputType.emailAddress,
                      decoration: const InputDecoration(
                        labelText: 'Username or email',
                        prefixIcon: Icon(Icons.person_outline),
                      ),
                      validator: (v) => (v ?? '').trim().isEmpty
                          ? 'Enter your username'
                          : null,
                    ),
                    const SizedBox(height: AppSpacing.md),

                    TextFormField(
                      controller: _codeController,
                      enabled: !busy,
                      autocorrect: false,
                      textCapitalization: TextCapitalization.characters,
                      textInputAction: TextInputAction.next,
                      maxLength: 9, // eight characters plus the dash
                      style: const TextStyle(
                        fontFamily: 'monospace',
                        letterSpacing: 4,
                        fontSize: 20,
                      ),
                      inputFormatters: [
                        // The code is Crockford-style: no I, L, O or U. Folding
                        // case here means a user typing lower case is not
                        // silently spending one of only five attempts.
                        UpperCaseFormatter(),
                      ],
                      decoration: const InputDecoration(
                        labelText: 'Pairing code',
                        hintText: 'XXXX-XXXX',
                        prefixIcon: Icon(Icons.pin_outlined),
                        counterText: '',
                      ),
                      validator: (v) {
                        final cleaned = (v ?? '').replaceAll(
                          RegExp(r'[^A-Za-z0-9]'),
                          '',
                        );
                        if (cleaned.isEmpty) return 'Enter the pairing code';
                        if (cleaned.length != 8) {
                          return 'The code is eight characters';
                        }
                        return null;
                      },
                    ),
                    const SizedBox(height: AppSpacing.md),

                    TextFormField(
                      controller: _labelController,
                      enabled: !busy,
                      textInputAction: TextInputAction.done,
                      onFieldSubmitted: (_) => busy ? null : _submit(),
                      decoration: const InputDecoration(
                        labelText: 'Name this device',
                        helperText: 'So you can tell your devices apart later.',
                        prefixIcon: Icon(Icons.smartphone_outlined),
                      ),
                      validator: (v) => (v ?? '').trim().isEmpty
                          ? 'Give this device a name'
                          : null,
                    ),

                    if (state.hasError) ...[
                      const SizedBox(height: AppSpacing.md),
                      _ErrorNotice(error: state.error!),
                    ],

                    const SizedBox(height: AppSpacing.xl),
                    FilledButton(
                      onPressed: busy ? null : _submit,
                      child: busy
                          ? const SizedBox(
                              height: 20,
                              width: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Pair this device'),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    TextButton(
                      onPressed: busy ? null : () => context.go('/login'),
                      child: const Text('Back to sign in'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Folds to upper case without moving the caret to the end on every keystroke.
class UpperCaseFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    return TextEditingValue(
      text: newValue.text.toUpperCase(),
      selection: newValue.selection,
      composing: TextRange.empty,
    );
  }
}

class _Steps extends StatelessWidget {
  const _Steps({required this.palette});

  final AppPalette palette;

  @override
  Widget build(BuildContext context) {
    const steps = [
      'Open Perfect HR in a browser and sign in.',
      'Go to Mobile App > Pair My Phone.',
      'Type the code it shows into this screen, within 10 minutes.',
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Link this phone to your account', style: context.text.titleLarge),
        const SizedBox(height: AppSpacing.xs),
        Text(
          'Your phone will create its own security key and keep it locked '
          'behind your fingerprint. The key never leaves this device.',
          style:
              context.text.bodyMedium?.copyWith(color: palette.inkSecondary),
        ),
        const SizedBox(height: AppSpacing.md),
        for (var i = 0; i < steps.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.xs),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                CircleAvatar(
                  radius: 11,
                  backgroundColor: palette.brandContainer,
                  child: Text(
                    '${i + 1}',
                    style: context.text.labelSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                      color: palette.onBrandContainer,
                    ),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(steps[i], style: context.text.bodyMedium),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _ErrorNotice extends StatelessWidget {
  const _ErrorNotice({required this.error});

  final Object error;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final message = error is AppFailure
        ? (error as AppFailure).userMessage
        : 'Something went wrong. Please try again.';

    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: palette.dangerContainer,
        borderRadius: AppRadius.cardRadius,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.error_outline, color: palette.danger, size: 20),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              message,
              style: context.text.bodySmall?.copyWith(color: palette.danger),
            ),
          ),
        ],
      ),
    );
  }
}
