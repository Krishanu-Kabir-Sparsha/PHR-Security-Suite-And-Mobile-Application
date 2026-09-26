import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/config/app_config.dart';
import '../../../core/errors/app_failure.dart';
import '../../../core/routing/app_routes.dart';
import '../../../core/tenant/tenant_config.dart';
import '../../../core/tenant/tenant_providers.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../shared/extensions/theme_context.dart';
import '../application/auth_providers.dart';

/// AUTH-01 Sign in.
///
/// Four questions in a fixed order, and the order is the point:
///
///     workspace     which customer's Perfect HR is this?
///     company       which organisation inside it?
///     method        password only, or password and fingerprint?
///     credentials   work email or Employee ID, and the password
///
/// Each answer narrows what the next one means. The workspace decides which
/// server is being talked to, the company decides which policy applies, and
/// the policy decides whether a fingerprint is going to be asked for — so a
/// person knows they will need their thumb *before* typing a password rather
/// than after.
///
/// Steps that have only one possible answer are skipped rather than shown. A
/// single-company tenant never sees the company step; a company with one
/// permitted method never sees the method toggle. A screen that asks a
/// question with one answer teaches people to stop reading it.
///
/// One route rather than three. Sign-in is a single task and a person moving
/// back a step is correcting an answer, not navigating — separate routes would
/// put that in the system back stack alongside everything else.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

enum _Step { workspace, company, credentials }

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _credentialsKey = GlobalKey<FormState>();
  final _workspaceController = TextEditingController();
  final _loginController = TextEditingController();
  final _passwordController = TextEditingController();

  _Step _step = _Step.workspace;
  bool _obscured = true;
  bool _resolving = false;
  String? _workspaceError;

  TenantCompany? _company;
  String? _mode;

  @override
  void initState() {
    super.initState();
    // A remembered workspace skips straight past its own step. Restored before
    // the first frame in main(), so this does not flash.
    final tenant = ref.read(tenantControllerProvider);
    if (tenant != null) {
      _workspaceController.text = tenant.baseUrl;
      _step = tenant.companyStepRequired ? _Step.company : _Step.credentials;
    }
  }

  @override
  void dispose() {
    _workspaceController.dispose();
    _loginController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  // ---------------------------------------------------------------- workspace

  Future<void> _resolveWorkspace() async {
    FocusScope.of(context).unfocus();
    setState(() {
      _resolving = true;
      _workspaceError = null;
    });

    try {
      final baseUrl = normaliseWorkspaceUrl(_workspaceController.text);
      final config =
          await ref.read(tenantRepositoryProvider).resolve(baseUrl);
      await ref.read(tenantControllerProvider.notifier).adopt(config);
      if (!mounted) return;
      setState(() {
        _resolving = false;
        _workspaceController.text = config.baseUrl;
        _company = null;
        _mode = null;
        _step = config.companyStepRequired ? _Step.company : _Step.credentials;
      });
    } on WorkspaceAddressError catch (error) {
      if (!mounted) return;
      setState(() {
        _resolving = false;
        _workspaceError = error.message;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _resolving = false;
        _workspaceError = error is AppFailure
            ? error.userMessage
            : 'That address could not be reached. Check it and try again.';
      });
    }
  }

  /// Back to the workspace step, forgetting the current one.
  ///
  /// Forgetting is right here and nowhere else: this is the explicit "sign in
  /// somewhere else" path. An ordinary sign-out keeps the address, because it
  /// is not a credential and retyping it every morning would be a worse app.
  Future<void> _changeWorkspace() async {
    await ref.read(tenantControllerProvider.notifier).forget();
    if (!mounted) return;
    setState(() {
      _step = _Step.workspace;
      _company = null;
      _mode = null;
      _workspaceError = null;
      _passwordController.clear();
    });
  }

  // ------------------------------------------------------------------ company

  void _chooseCompany(TenantCompany company) {
    setState(() {
      _company = company;
      // Preselect the company's own preference, which the server sends first.
      // Only carried forward when there is a genuine choice; otherwise the
      // server decides and the app says nothing about it.
      _mode = company.offersChoice ? company.authModes.first : null;
      _step = _Step.credentials;
    });
  }

  // -------------------------------------------------------------- credentials

  Future<void> _submit() async {
    if (!(_credentialsKey.currentState?.validate() ?? false)) return;
    // Dismiss the keyboard first: the error appears above the fold on a small
    // handset, and a raised keyboard would hide it.
    FocusScope.of(context).unfocus();

    await ref.read(signInControllerProvider.notifier).signIn(
          login: _loginController.text.trim(),
          password: _passwordController.text,
          deviceLabel: 'Perfect HR mobile',
          companyId: _company?.id,
          authMode: _mode,
        );
    // Navigation is not performed here. The router redirects on session state,
    // so a successful sign-in moves the app on its own; pushing a route as
    // well would race that redirect.
  }

  // --------------------------------------------------------------------- view

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(signInControllerProvider);
    final tenant = ref.watch(tenantControllerProvider);
    final busy = state.isLoading || _resolving;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: AppSpacing.page,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _Masthead(tenant: tenant, step: _step),
                  const SizedBox(height: AppSpacing.xl),
                  AnimatedSwitcher(
                    duration: const Duration(milliseconds: 180),
                    child: switch (_step) {
                      _Step.workspace => _workspaceStep(busy),
                      _Step.company => _companyStep(busy, tenant),
                      _Step.credentials => _credentialsStep(busy, state),
                    },
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _workspaceStep(bool busy) {
    return Column(
      key: const ValueKey(_Step.workspace),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextField(
          controller: _workspaceController,
          enabled: !busy,
          autocorrect: false,
          textInputAction: TextInputAction.go,
          keyboardType: TextInputType.url,
          onSubmitted: (_) => busy ? null : _resolveWorkspace(),
          decoration: InputDecoration(
            labelText: 'Perfect HR address',
            hintText: 'yourcompany.perfecthr.net',
            prefixIcon: const Icon(Icons.language_outlined),
            errorText: _workspaceError,
            // Not a placeholder: a bare name is what people read off an
            // induction email, and the field accepts it.
            helperText: 'Your company name on its own works too.',
            helperMaxLines: 2,
          ),
        ),
        if (_workspaceError == null) ...[
          const SizedBox(height: AppSpacing.sm),
          _Hint(
            icon: Icons.lock_outline,
            text: 'Your password is never sent until this address confirms it '
                'is a Perfect HR workspace.',
          ),
        ],
        const SizedBox(height: AppSpacing.xl),
        FilledButton(
          onPressed: busy ? null : _resolveWorkspace,
          child: busy ? const _ButtonSpinner() : const Text('Continue'),
        ),
      ],
    );
  }

  Widget _companyStep(bool busy, TenantConfig? tenant) {
    final companies = ref.watch(tenantCompaniesProvider(tenant?.baseUrl ?? ''));

    return Column(
      key: const ValueKey(_Step.company),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        companies.when(
          loading: () => const Padding(
            padding: EdgeInsets.symmetric(vertical: AppSpacing.xl),
            child: Center(child: CircularProgressIndicator()),
          ),
          error: (error, _) => Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _ErrorNotice(error: error),
              const SizedBox(height: AppSpacing.md),
              // The step is optional by design, so a failure to load it must
              // not be a dead end. Carrying on places the user in their own
              // default company, which is what a tenant publishing nothing
              // does anyway.
              OutlinedButton(
                onPressed: () => setState(() => _step = _Step.credentials),
                child: const Text('Continue without choosing'),
              ),
            ],
          ),
          data: (list) {
            if (list.isEmpty) {
              // Nothing published. Skip rather than show an empty list — the
              // server will use each user's own company.
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (mounted && _step == _Step.company) {
                  setState(() => _step = _Step.credentials);
                }
              });
              return const SizedBox.shrink();
            }
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (final company in list) ...[
                  _CompanyTile(
                    company: company,
                    tenant: tenant,
                    onTap: busy ? null : () => _chooseCompany(company),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                ],
              ],
            );
          },
        ),
        const SizedBox(height: AppSpacing.md),
        TextButton.icon(
          onPressed: busy ? null : _changeWorkspace,
          icon: const Icon(Icons.arrow_back, size: 18),
          label: const Text('Use a different address'),
        ),
      ],
    );
  }

  Widget _credentialsStep(bool busy, AsyncValue<void> state) {
    final company = _company;

    return Form(
      key: _credentialsKey,
      child: Column(
        key: const ValueKey(_Step.credentials),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (company != null && company.offersChoice) ...[
            _MethodPicker(
              company: company,
              selected: _mode ?? company.authModes.first,
              enabled: !busy,
              onChanged: (mode) => setState(() => _mode = mode),
            ),
            const SizedBox(height: AppSpacing.lg),
          ],

          TextFormField(
            controller: _loginController,
            enabled: !busy,
            autocorrect: false,
            textInputAction: TextInputAction.next,
            keyboardType: TextInputType.emailAddress,
            decoration: const InputDecoration(
              labelText: 'Work email or Employee ID',
              prefixIcon: Icon(Icons.badge_outlined),
              helperText: 'The number on your ID badge works here.',
              helperMaxLines: 2,
            ),
            validator: (v) => (v ?? '').trim().isEmpty
                ? 'Enter your work email or Employee ID'
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
                // A reveal toggle reduces failed sign-ins on phone keyboards
                // far more than it risks shoulder-surfing.
                tooltip: _obscured ? 'Show password' : 'Hide password',
                onPressed: () => setState(() => _obscured = !_obscured),
              ),
            ),
            validator: (v) => (v ?? '').isEmpty ? 'Enter your password' : null,
          ),

          if (state.hasError) ...[
            const SizedBox(height: AppSpacing.md),
            _ErrorNotice(error: state.error!),
          ],

          const SizedBox(height: AppSpacing.xl),
          FilledButton(
            onPressed: busy ? null : _submit,
            child: busy
                ? const _ButtonSpinner()
                : Text(_mode == 'basic' ? 'Sign in' : 'Continue'),
          ),

          // Offered here rather than after a failed sign-in. A phone that has
          // never been paired cannot complete the fingerprint step, and finding
          // that out only after typing a password makes the app look broken
          // rather than unconfigured.
          const SizedBox(height: AppSpacing.sm),
          _PairingHint(busy: busy),

          const SizedBox(height: AppSpacing.xs),
          _BackLink(
            label: _company != null
                ? 'Choose a different company'
                : 'Use a different address',
            onTap: busy
                ? null
                : () => _company != null
                    ? setState(() => _step = _Step.company)
                    : _changeWorkspace(),
          ),
        ],
      ),
    );
  }
}

/// The workspace and company chosen so far, above the current question.
///
/// Answers "where am I signing in?" without a back-and-forth, which matters
/// most on the credentials step: by then the two decisions that determine
/// where the password goes are two steps behind.
class _Masthead extends StatelessWidget {
  const _Masthead({required this.tenant, required this.step});

  final TenantConfig? tenant;
  final _Step step;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final subtitle = switch (step) {
      _Step.workspace => 'Enter your organisation\'s Perfect HR address.',
      _Step.company => 'Which company are you signing in to?',
      _Step.credentials => 'Sign in with your Perfect HR account.',
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          step == _Step.workspace
              ? 'Perfect HR'
              : (tenant?.tenantName ?? 'Perfect HR'),
          style: context.text.headlineMedium,
        ),
        const SizedBox(height: AppSpacing.xs),
        Text(
          subtitle,
          style: context.text.bodyMedium?.copyWith(color: palette.inkSecondary),
        ),
        if (step != _Step.workspace && tenant != null) ...[
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: [
              Icon(Icons.verified_outlined, size: 14, color: palette.success),
              const SizedBox(width: AppSpacing.xxs),
              Flexible(
                child: Text(
                  Uri.parse(tenant!.baseUrl).host,
                  overflow: TextOverflow.ellipsis,
                  style: context.text.bodySmall
                      ?.copyWith(color: palette.inkSecondary),
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }
}

/// One company, as a tappable card.
class _CompanyTile extends StatelessWidget {
  const _CompanyTile({
    required this.company,
    required this.tenant,
    required this.onTap,
  });

  final TenantCompany company;
  final TenantConfig? tenant;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final logo = company.logoUrl;

    return Material(
      color: palette.surfaceAlt,
      borderRadius: AppRadius.cardRadius,
      child: InkWell(
        onTap: onTap,
        borderRadius: AppRadius.cardRadius,
        child: Padding(
          padding: AppSpacing.card,
          child: Row(
            children: [
              if (logo != null && tenant != null)
                ClipRRect(
                  borderRadius: AppRadius.controlRadius,
                  child: Image.network(
                    tenant!.absolute(logo),
                    width: 36,
                    height: 36,
                    fit: BoxFit.contain,
                    // A missing logo must not leave a broken-image glyph on the
                    // sign-in screen, which reads as a broken app.
                    errorBuilder: (_, __, ___) =>
                        Icon(Icons.business_outlined, color: palette.brand),
                  ),
                )
              else
                Icon(Icons.business_outlined, color: palette.brand),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Text(company.name, style: context.text.titleMedium),
              ),
              Icon(Icons.chevron_right, color: palette.inkSecondary),
            ],
          ),
        ),
      ),
    );
  }
}

/// Basic or advanced, drawn only where both are genuinely available.
class _MethodPicker extends StatelessWidget {
  const _MethodPicker({
    required this.company,
    required this.selected,
    required this.enabled,
    required this.onChanged,
  });

  final TenantCompany company;
  final String selected;
  final bool enabled;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('How would you like to sign in?', style: context.text.titleSmall),
        const SizedBox(height: AppSpacing.sm),
        for (final mode in company.authModes) ...[
          _MethodOption(
            selected: selected == mode,
            enabled: enabled,
            onTap: () => onChanged(mode),
            icon: mode == 'advance'
                ? Icons.fingerprint
                : Icons.password_outlined,
            title: mode == 'advance' ? 'Advanced' : 'Basic',
            // Says what each one actually proves, rather than labelling one
            // "secure". Somebody choosing the weaker option is entitled to
            // know what they are giving up, in a sentence.
            subtitle: mode == 'advance'
                ? 'Password, then your fingerprint on this device.'
                : 'Password only. Faster, and a stolen password is enough to '
                    'sign in.',
          ),
          const SizedBox(height: AppSpacing.xs),
        ],
        if (selected == 'basic') ...[
          const SizedBox(height: AppSpacing.xxs),
          _Hint(
            icon: Icons.info_outline,
            text: 'Approving other people\'s requests still asks for your '
                'fingerprint, whichever method you pick here.',
            color: palette.inkSecondary,
          ),
        ],
      ],
    );
  }
}

class _MethodOption extends StatelessWidget {
  const _MethodOption({
    required this.selected,
    required this.enabled,
    required this.onTap,
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  final bool selected;
  final bool enabled;
  final VoidCallback onTap;
  final IconData icon;
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;

    return Material(
      color: selected ? palette.brandContainer : palette.surfaceAlt,
      borderRadius: AppRadius.cardRadius,
      child: InkWell(
        onTap: enabled ? onTap : null,
        borderRadius: AppRadius.cardRadius,
        child: Container(
          padding: AppSpacing.card,
          decoration: BoxDecoration(
            borderRadius: AppRadius.cardRadius,
            border: Border.all(
              color: selected ? palette.brand : palette.border,
              width: selected ? 2 : 1,
            ),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                icon,
                color: selected ? palette.brand : palette.inkSecondary,
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: context.text.titleSmall),
                    const SizedBox(height: AppSpacing.xxs),
                    Text(
                      subtitle,
                      style: context.text.bodySmall
                          ?.copyWith(color: palette.inkSecondary),
                    ),
                  ],
                ),
              ),
              if (selected)
                Icon(Icons.check_circle, size: 20, color: palette.brand),
            ],
          ),
        ),
      ),
    );
  }
}

/// Either "this phone is paired to X" or a way to pair it.
///
/// Renders nothing while the binding is still being read, so the button does
/// not appear and then vanish on a returning user's cold start.
class _PairingHint extends ConsumerWidget {
  const _PairingHint({required this.busy});

  final bool busy;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final binding = ref.watch(deviceBindingProvider);
    final palette = context.palette;

    return binding.maybeWhen(
      orElse: () => const SizedBox.shrink(),
      data: (paired) {
        if (paired == null) {
          return TextButton.icon(
            onPressed: busy ? null : () => context.push(AppRoutes.pairDevice),
            icon: const Icon(Icons.smartphone_outlined, size: 18),
            label: const Text('Pair this device'),
          );
        }
        return Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.verified_user_outlined,
                size: 16, color: palette.inkSecondary),
            const SizedBox(width: AppSpacing.xs),
            Flexible(
              child: Text(
                'Paired to ${paired.login}',
                style: context.text.bodySmall
                    ?.copyWith(color: palette.inkSecondary),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _BackLink extends StatelessWidget {
  const _BackLink({required this.label, required this.onTap});

  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    // Hidden entirely on a build that seeds its own workspace and publishes no
    // companies: there would be nothing behind the link to go back to.
    if (!AppConfig.current.allowsWorkspaceEntry) return const SizedBox.shrink();
    return TextButton(onPressed: onTap, child: Text(label));
  }
}

class _Hint extends StatelessWidget {
  const _Hint({required this.icon, required this.text, this.color});

  final IconData icon;
  final String text;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final tone = color ?? context.palette.inkSecondary;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 14, color: tone),
        const SizedBox(width: AppSpacing.xs),
        Expanded(
          child: Text(
            text,
            style: context.text.bodySmall?.copyWith(color: tone),
          ),
        ),
      ],
    );
  }
}

class _ButtonSpinner extends StatelessWidget {
  const _ButtonSpinner();

  @override
  Widget build(BuildContext context) => const SizedBox(
        height: 20,
        width: 20,
        child: CircularProgressIndicator(strokeWidth: 2),
      );
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
