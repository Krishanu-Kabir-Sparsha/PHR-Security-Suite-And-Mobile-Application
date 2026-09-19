import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/errors/app_failure.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../shared/extensions/theme_context.dart';
import '../application/auth_providers.dart';

/// AUTH-01 Sign in.
///
/// Username and password against `POST /auth/login`. This replaces the
/// Keycloak OIDC + PKCE flow originally planned: the client's networking layer
/// only ever needed a bearer token and a refresh endpoint, so having Odoo issue
/// them removes a component rather than adding one.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _loginController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _obscured = true;

  @override
  void dispose() {
    _loginController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    // Dismiss the keyboard first: the error message appears above the fold on
    // a small handset, and a raised keyboard would hide it.
    FocusScope.of(context).unfocus();

    await ref.read(signInControllerProvider.notifier).signIn(
          login: _loginController.text.trim(),
          password: _passwordController.text,
          deviceLabel: 'Perfect HR mobile',
        );
    // Navigation is not performed here. The router redirects on session state,
    // so a successful sign-in moves the app on its own; pushing a route as
    // well would race that redirect.
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(signInControllerProvider);
    final busy = state.isLoading;
    final palette = context.palette;

    return Scaffold(
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
                    Text('Perfect HR', style: context.text.headlineMedium),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      'Sign in with your Perfect HR account.',
                      style: context.text.bodyMedium
                          ?.copyWith(color: palette.inkSecondary),
                    ),
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
                      controller: _passwordController,
                      enabled: !busy,
                      obscureText: _obscured,
                      textInputAction: TextInputAction.done,
                      onFieldSubmitted: (_) => busy ? null : _submit(),
                      decoration: InputDecoration(
                        labelText: 'Password',
                        prefixIcon: const Icon(Icons.lock_outline),
                        suffixIcon: IconButton(
                          icon: Icon(
                            _obscured
                                ? Icons.visibility_outlined
                                : Icons.visibility_off_outlined,
                          ),
                          // A reveal toggle reduces failed sign-ins on phone
                          // keyboards far more than it risks shoulder-surfing.
                          tooltip: _obscured ? 'Show password' : 'Hide password',
                          onPressed: () =>
                              setState(() => _obscured = !_obscured),
                        ),
                      ),
                      validator: (v) =>
                          (v ?? '').isEmpty ? 'Enter your password' : null,
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
                          : const Text('Sign in'),
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

class _ErrorNotice extends StatelessWidget {
  const _ErrorNotice({required this.error});

  final Object error;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    // ApiClient guarantees every error crossing into the app is an AppFailure,
    // whose userMessage has already been through the mapper's safety checks.
    // The fallback covers a programming error rather than a server one.
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
          Icon(Icons.error_outline, color: palette.onDangerContainer),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              message,
              style: context.text.bodyMedium
                  ?.copyWith(color: palette.onDangerContainer),
            ),
          ),
        ],
      ),
    );
  }
}
