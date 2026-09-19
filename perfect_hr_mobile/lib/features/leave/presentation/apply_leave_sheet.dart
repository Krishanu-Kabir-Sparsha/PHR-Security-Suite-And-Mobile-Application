import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../core/theme/app_dimensions.dart';
import '../../../shared/extensions/theme_context.dart';
import '../application/leave_providers.dart';
import '../domain/leave_models.dart';

/// **E-06 — Apply for Leave.**
///
/// A sheet rather than a route. Applying is a decision taken while looking at a
/// balance, and pushing a full screen hides the number the person is deciding
/// against.
///
/// Client-side validation here is deliberately thin — required fields and
/// date order only. Whether the employee has enough days, whether the request
/// overlaps an existing one, and whether the dates fall on working days are all
/// decided by Odoo at create time. Re-implementing those rules would produce a
/// phone that refuses requests the web client accepts, or worse, accepts ones it
/// will not.
Future<void> showApplyLeaveSheet(
  BuildContext context, {
  required List<LeaveBalance> balances,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => _ApplyLeaveSheet(balances: balances),
  );
}

class _ApplyLeaveSheet extends ConsumerStatefulWidget {
  const _ApplyLeaveSheet({required this.balances});

  final List<LeaveBalance> balances;

  @override
  ConsumerState<_ApplyLeaveSheet> createState() => _ApplyLeaveSheetState();
}

class _ApplyLeaveSheetState extends ConsumerState<_ApplyLeaveSheet> {
  late LeaveBalance _type = widget.balances.first;
  DateTime? _from;
  DateTime? _to;
  final TextEditingController _reason = TextEditingController();
  String? _dateError;

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  Future<void> _pick({required bool isStart}) async {
    final now = DateTime.now();
    final initial = (isStart ? _from : _to) ?? _from ?? now;

    final picked = await showDatePicker(
      context: context,
      initialDate: initial.isBefore(now) ? now : initial,
      // A year back covers a correction to leave already taken; two years
      // forward covers planning. Unbounded ranges make the picker unusable on
      // a phone.
      firstDate: DateTime(now.year - 1),
      lastDate: DateTime(now.year + 2),
    );
    if (picked == null) return;

    setState(() {
      if (isStart) {
        _from = picked;
        // Keeping an end date that is now before the start would let someone
        // submit an inverted range and read the server's rejection as a bug.
        if (_to != null && _to!.isBefore(picked)) _to = picked;
      } else {
        _to = picked;
      }
      _dateError = null;
    });
  }

  Future<void> _submit() async {
    final from = _from;
    final to = _to;

    if (from == null || to == null) {
      setState(() => _dateError = 'Choose both a start and an end date.');
      return;
    }
    if (to.isBefore(from)) {
      setState(() => _dateError = 'The end date must be on or after the start.');
      return;
    }

    final ok = await ref.read(leaveActionProvider.notifier).apply(
          typeId: _type.id,
          from: from,
          to: to,
          reason: _reason.text.trim(),
        );

    if (!mounted) return;
    if (ok) {
      // Only closed on success. A rejected request — "you do not have enough
      // days" — must leave the form filled in so the dates can be adjusted
      // rather than retyped.
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context)
        ..clearSnackBars()
        ..showSnackBar(
          const SnackBar(content: Text('Leave request submitted.')),
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final busy = ref.watch(leaveActionProvider).isLoading;
    final format = DateFormat('EEE, d MMM yyyy');

    return Padding(
      padding: EdgeInsets.only(
        left: AppSpacing.md,
        right: AppSpacing.md,
        bottom: MediaQuery.of(context).viewInsets.bottom + AppSpacing.lg,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Apply for Leave', style: context.text.titleLarge),
            const SizedBox(height: AppSpacing.md),

            DropdownButtonFormField<LeaveBalance>(
              initialValue: _type,
              decoration: const InputDecoration(labelText: 'Leave type'),
              items: [
                for (final balance in widget.balances)
                  DropdownMenuItem(
                    value: balance,
                    child: Text(
                      '${balance.label} · '
                      '${balance.remainingDays.toStringAsFixed(
                        balance.remainingDays == balance.remainingDays
                                .roundToDouble()
                            ? 0
                            : 1,
                      )} left',
                    ),
                  ),
              ],
              onChanged: busy
                  ? null
                  : (value) => setState(() => _type = value ?? _type),
            ),
            const SizedBox(height: AppSpacing.sm),

            Row(
              children: [
                Expanded(
                  child: _DateField(
                    label: 'From',
                    value: _from == null ? null : format.format(_from!),
                    onTap: busy ? null : () => _pick(isStart: true),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: _DateField(
                    label: 'To',
                    value: _to == null ? null : format.format(_to!),
                    onTap: busy ? null : () => _pick(isStart: false),
                  ),
                ),
              ],
            ),
            if (_dateError != null) ...[
              const SizedBox(height: AppSpacing.xxs),
              Text(
                _dateError!,
                style: context.text.bodySmall
                    ?.copyWith(color: context.palette.danger),
              ),
            ],
            const SizedBox(height: AppSpacing.sm),

            TextField(
              controller: _reason,
              enabled: !busy,
              maxLines: 3,
              maxLength: 500,
              decoration: const InputDecoration(
                labelText: 'Reason (optional)',
                alignLabelWithHint: true,
              ),
            ),
            const SizedBox(height: AppSpacing.sm),

            SizedBox(
              height: AppSizes.buttonHeight,
              width: double.infinity,
              child: FilledButton(
                onPressed: busy ? null : _submit,
                child: busy
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Submit request'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DateField extends StatelessWidget {
  const _DateField({required this.label, required this.value, this.onTap});

  final String label;
  final String? value;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: InputDecorator(
        decoration: InputDecoration(labelText: label),
        child: Text(
          value ?? 'Choose',
          style: value == null
              ? context.text.bodyMedium
                  ?.copyWith(color: context.palette.inkTertiary)
              : context.text.bodyMedium,
        ),
      ),
    );
  }
}
