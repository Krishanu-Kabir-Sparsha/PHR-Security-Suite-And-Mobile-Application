import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/config/app_config.dart';
import 'package:perfect_hr_mobile/core/errors/app_failure.dart';
import 'package:perfect_hr_mobile/core/security/device_key_service.dart';
import 'package:perfect_hr_mobile/core/security/passkey_service.dart';
import 'package:perfect_hr_mobile/core/security/second_factor.dart';
import 'package:perfect_hr_mobile/core/theme/app_theme.dart';
import 'package:perfect_hr_mobile/features/approvals/application/approvals_providers.dart';
import 'package:perfect_hr_mobile/features/approvals/data/approvals_repository.dart';
import 'package:perfect_hr_mobile/features/approvals/domain/override_approval.dart';
import 'package:perfect_hr_mobile/features/approvals/presentation/approvals_screen.dart';
import 'package:perfect_hr_mobile/features/authentication/application/auth_providers.dart';

/// Override approvals on the phone.
///
/// Approving changes a frozen record, so it is gated on a fingerprint bound to
/// one specific request. Rejecting is not gated at all — and that asymmetry is
/// the most important thing here: friction on the safe answer is how people end
/// up approving to make a dialog go away.

OverrideApproval _approval({String id = '41', bool highRisk = false}) {
  return OverrideApproval(
    id: id,
    reference: 'OVR-2026-00$id',
    target: 'Payslip PS-2026-0219',
    requestedBy: 'Nabila Islam',
    contextRef: 'override.request,$id',
    reason: 'Correction after payroll close',
    tierName: 'Tier 3 — CEO / Owner',
    highRisk: highRisk,
  );
}

class _StubRepository implements ApprovalsRepository {
  _StubRepository({
    ApprovalQueue? queue,
    this.approveError,
    this.rejectError,
    this.method = SecondFactorMethod.passkey,
  }) : queue = queue ??
            ApprovalQueue(available: true, requests: [_approval()]);

  final ApprovalQueue queue;
  final Object? approveError;
  final Object? rejectError;

  /// Which proof this stub's server asks for. The app must follow, never
  /// choose — see ApprovalActionController.approve.
  final SecondFactorMethod method;

  int challengeCalls = 0;
  int approveCalls = 0;
  int rejectCalls = 0;
  Map<String, dynamic>? sentAssertion;
  Map<String, dynamic>? sentSignature;
  String? sentContextId;

  @override
  Future<ApprovalQueue> loadQueue() async => queue;

  @override
  Future<ApprovalChallenge> challengeFor(String requestId) async {
    challengeCalls++;
    sentContextId = requestId;
    return ApprovalChallenge(
      method: method,
      options: const {'challenge': 'bound-to-41'},
      deviceChallenge: const {
        'challenge': 'bound-to-41',
        'context_ref': 'override.request,41',
      },
    );
  }

  @override
  Future<void> approve({
    required String requestId,
    Map<String, dynamic>? assertion,
    Map<String, dynamic>? signaturePayload,
  }) async {
    approveCalls++;
    sentAssertion = assertion;
    sentSignature = signaturePayload;
    final error = approveError;
    if (error != null) throw error;
  }

  @override
  Future<void> reject(String requestId) async {
    rejectCalls++;
    final error = rejectError;
    if (error != null) throw error;
  }
}

class _StubPasskeys implements PasskeyService {
  _StubPasskeys({this.available = true, this.failure});

  final bool available;
  final PasskeyFailure? failure;

  int getCalls = 0;
  Map<String, dynamic>? receivedChallenge;

  // Diagnostics are for the About screen, not for a ceremony. Empty here.
  @override
  Future<Map<String, String>> diagnostics() async => const {};

  @override
  Future<bool> get isAvailable async => available;

  @override
  Future<Map<String, dynamic>> get(Map<String, dynamic> optionsJson) async {
    getCalls++;
    receivedChallenge = optionsJson;
    final thrown = failure;
    if (thrown != null) throw thrown;
    return const {'id': 'signed'};
  }

  @override
  Future<Map<String, dynamic>> create(Map<String, dynamic> optionsJson) async =>
      throw UnimplementedError();
}

/// A paired device that signs whatever it is given.
class _StubDeviceKeys implements DeviceKeyService {
  _StubDeviceKeys({this.failure});

  final DeviceKeyFailure? failure;

  int signCalls = 0;
  String? signedChallenge;
  String? signedContext;
  String? shownReason;

  @override
  Future<bool> get isSupported async => true;

  @override
  Future<DeviceBinding?> get binding async => const DeviceBinding(
        handle: 'handle-1',
        login: 'nabila',
        label: 'Test phone',
        counter: 3,
      );

  @override
  Future<String> generateKeyPair() async => 'public-key';

  @override
  Future<void> rememberPairing({
    required String publicKey,
    required String handle,
    required String login,
    required String label,
  }) async {}

  @override
  Future<DeviceSignature> sign({
    required String challenge,
    required String contextRef,
    required String reason,
  }) async {
    signCalls++;
    signedChallenge = challenge;
    signedContext = contextRef;
    shownReason = reason;
    final thrown = failure;
    if (thrown != null) throw thrown;
    return DeviceSignature(
      deviceHandle: 'handle-1',
      challenge: challenge,
      counter: 4,
      signature: 'signed',
    );
  }

  @override
  Future<void> forget() async {}
}

ProviderContainer _container(
  _StubRepository repository, {
  _StubPasskeys? passkeys,
  _StubDeviceKeys? deviceKeys,
}) {
  return ProviderContainer(
    overrides: [
      approvalsRepositoryProvider.overrideWithValue(repository),
      passkeyServiceProvider.overrideWithValue(passkeys ?? _StubPasskeys()),
      deviceKeyServiceProvider
          .overrideWithValue(deviceKeys ?? _StubDeviceKeys()),
    ],
  );
}

Future<void> _pump(WidgetTester tester, ProviderContainer container) async {
  tester.view.physicalSize = const Size(1200, 3000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(theme: AppTheme.light(), home: const ApprovalsScreen()),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(AppConfig.initialise);

  group('approving', () {
    test('asks the device, then sends the assertion with the decision',
        () async {
      // The assertion is consumed by the request that records the approval. A
      // separate call would arrive with the proof already spent.
      final repository = _StubRepository();
      final passkeys = _StubPasskeys();
      final container = _container(repository, passkeys: passkeys);
      addTearDown(container.dispose);

      final approved = await container
          .read(approvalActionProvider.notifier)
          .approve(_approval());

      expect(approved, isTrue);
      expect(repository.challengeCalls, 1);
      expect(passkeys.getCalls, 1);
      expect(repository.approveCalls, 1);
      expect(repository.sentAssertion, const {'id': 'signed'});
    });

    test('the challenge is fetched for that one request', () async {
      // Binding is the difference between a signature and a bearer token: a
      // confirmation given for one override must not approve another.
      final repository = _StubRepository();
      final container = _container(repository);
      addTearDown(container.dispose);

      await container
          .read(approvalActionProvider.notifier)
          .approve(_approval(id: '77'));

      expect(repository.sentContextId, '77');
    });

    test('nothing is approved if the device is not confirmed', () async {
      final repository = _StubRepository();
      final container = _container(
        repository,
        passkeys: _StubPasskeys(
          failure: const PasskeyFailure(
            PasskeyFailureKind.failed,
            'Wrong finger.',
          ),
        ),
      );
      addTearDown(container.dispose);

      final approved = await container
          .read(approvalActionProvider.notifier)
          .approve(_approval());

      expect(approved, isFalse);
      expect(repository.approveCalls, 0);
    });

    test('cancelling is not an error', () async {
      // Thinking better of an approval is exactly the behaviour to encourage.
      final container = _container(
        _StubRepository(),
        passkeys: _StubPasskeys(
          failure: const PasskeyFailure(
            PasskeyFailureKind.cancelled,
            'Cancelled.',
          ),
        ),
      );
      addTearDown(container.dispose);

      await container
          .read(approvalActionProvider.notifier)
          .approve(_approval());

      expect(container.read(approvalActionProvider).hasError, isFalse);
    });

    test('a phone with no device says where to register one', () async {
      final container = _container(
        _StubRepository(),
        passkeys: _StubPasskeys(
          failure: const PasskeyFailure(
            PasskeyFailureKind.noCredential,
            'None.',
          ),
        ),
      );
      addTearDown(container.dispose);

      await container
          .read(approvalActionProvider.notifier)
          .approve(_approval());

      final state = container.read(approvalActionProvider);
      expect(
        asAppFailure(state.error!, state.stackTrace).userMessage,
        contains('Security & devices'),
      );
    });

    test("a server refusal reaches the user in the server's own words",
        () async {
      // "Not your tier yet" and "you are not a reviewer" are the useful
      // messages here; a generic failure would throw away the only part that
      // tells the approver what is going on.
      final container = _container(
        _StubRepository(
          approveError: const ValidationFailure(
            userMessage: 'There is no approval step awaiting you on this '
                'request.',
          ),
        ),
      );
      addTearDown(container.dispose);

      await container
          .read(approvalActionProvider.notifier)
          .approve(_approval());

      final state = container.read(approvalActionProvider);
      expect(
        asAppFailure(state.error!, state.stackTrace).userMessage,
        contains('no approval step awaiting you'),
      );
    });
  });

  group('approving with a paired device', () {
    test('signs the challenge and sends it with the decision', () async {
      final repository =
          _StubRepository(method: SecondFactorMethod.device);
      final keys = _StubDeviceKeys();
      final container = _container(repository, deviceKeys: keys);
      addTearDown(container.dispose);

      final approved = await container
          .read(approvalActionProvider.notifier)
          .approve(_approval());

      expect(approved, isTrue);
      expect(keys.signCalls, 1);
      expect(repository.sentSignature, isNotNull);
      expect(repository.sentSignature!['signature'], 'signed');
      // The assertion field must stay absent, not empty: sending both would
      // let the server verify whichever it happened to check first.
      expect(repository.sentAssertion, isNull);
    });

    test('the signature is bound to this override, not just the nonce',
        () async {
      // Signing the nonce alone would make a confirmation given for one
      // override replayable against another that happened to be in flight.
      final repository =
          _StubRepository(method: SecondFactorMethod.device);
      final keys = _StubDeviceKeys();
      final container = _container(repository, deviceKeys: keys);
      addTearDown(container.dispose);

      await container
          .read(approvalActionProvider.notifier)
          .approve(_approval());

      expect(keys.signedChallenge, 'bound-to-41');
      expect(keys.signedContext, 'override.request,41');
    });

    test('the prompt names what is being approved', () async {
      // A biometric prompt that says only "confirm" is one people answer
      // without reading, and this is the last thing between a request and a
      // frozen record changing.
      final keys = _StubDeviceKeys();
      final container = _container(
        _StubRepository(method: SecondFactorMethod.device),
        deviceKeys: keys,
      );
      addTearDown(container.dispose);

      await container
          .read(approvalActionProvider.notifier)
          .approve(_approval());

      expect(keys.shownReason, contains('OVR-2026-0041'));
    });

    test('no passkey prompt is raised when the server asked for a device',
        () async {
      // The app follows the server's choice. Raising both would ask the user
      // to answer a prompt for a credential they may not have.
      final passkeys = _StubPasskeys();
      final container = _container(
        _StubRepository(method: SecondFactorMethod.device),
        passkeys: passkeys,
        deviceKeys: _StubDeviceKeys(),
      );
      addTearDown(container.dispose);

      await container
          .read(approvalActionProvider.notifier)
          .approve(_approval());

      expect(passkeys.getCalls, 0);
    });

    test('nothing is approved when the fingerprint is not given', () async {
      final repository =
          _StubRepository(method: SecondFactorMethod.device);
      final container = _container(
        repository,
        deviceKeys: _StubDeviceKeys(
          failure: const DeviceKeyFailure(
            DeviceKeyFailureKind.failed,
            'Wrong finger.',
          ),
        ),
      );
      addTearDown(container.dispose);

      final approved = await container
          .read(approvalActionProvider.notifier)
          .approve(_approval());

      expect(approved, isFalse);
      expect(repository.approveCalls, 0);
    });

    test('cancelling is not an error', () async {
      final container = _container(
        _StubRepository(method: SecondFactorMethod.device),
        deviceKeys: _StubDeviceKeys(
          failure: const DeviceKeyFailure(
            DeviceKeyFailureKind.cancelled,
            'Cancelled.',
          ),
        ),
      );
      addTearDown(container.dispose);

      await container
          .read(approvalActionProvider.notifier)
          .approve(_approval());

      expect(container.read(approvalActionProvider).hasError, isFalse);
    });

    test('an unpaired installation says how to pair it', () async {
      // Most often a reinstall, which wipes the key. "Try again" would be
      // advice that can never work.
      final container = _container(
        _StubRepository(method: SecondFactorMethod.device),
        deviceKeys: _StubDeviceKeys(
          failure: const DeviceKeyFailure(
            DeviceKeyFailureKind.notPaired,
            'Not paired.',
          ),
        ),
      );
      addTearDown(container.dispose);

      await container
          .read(approvalActionProvider.notifier)
          .approve(_approval());

      final state = container.read(approvalActionProvider);
      expect(
        asAppFailure(state.error!, state.stackTrace).userMessage,
        contains('not paired'),
      );
    });
  });

  group('rejecting', () {
    test('needs no device confirmation', () async {
      // The asymmetry is deliberate. An approval can change a frozen record; a
      // rejection cannot, and a fingerprint prompt between a reviewer and "no"
      // puts friction on the safe answer.
      final repository = _StubRepository();
      final passkeys = _StubPasskeys();
      final container = _container(repository, passkeys: passkeys);
      addTearDown(container.dispose);

      final rejected = await container
          .read(approvalActionProvider.notifier)
          .reject(_approval());

      expect(rejected, isTrue);
      expect(repository.rejectCalls, 1);
      expect(passkeys.getCalls, 0, reason: 'saying no must not need a device');
    });
  });

  group('the queue', () {
    testWidgets('an empty queue says so rather than showing nothing',
        (tester) async {
      final container = _container(
        _StubRepository(
          queue: const ApprovalQueue(available: true, requests: []),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(
        find.textContaining('Nothing is waiting for your approval'),
        findsOneWidget,
      );
    });

    testWidgets('a waiting override shows what would change and why',
        (tester) async {
      // An approver deciding from a phone has only what is on this card.
      final container = _container(_StubRepository());
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('OVR-2026-0041'), findsOneWidget);
      expect(find.text('Payslip PS-2026-0219'), findsOneWidget);
      expect(find.text('Nabila Islam'), findsOneWidget);
      expect(find.text('Tier 3 — CEO / Owner'), findsOneWidget);
    });

    testWidgets('warns before the fingerprint prompt appears', (tester) async {
      // An unannounced biometric request is one people dismiss.
      final container = _container(_StubRepository());
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(
        find.textContaining('signs this request only'),
        findsOneWidget,
      );
    });

    testWidgets('a high-risk override is marked as one', (tester) async {
      final container = _container(
        _StubRepository(
          queue: ApprovalQueue(
            available: true,
            requests: [_approval(highRisk: true)],
          ),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('High risk'), findsOneWidget);
    });

    test('an unavailable workflow is not an empty queue', () {
      // One means "nothing is waiting on you"; the other means this deployment
      // has no override workflow at all, and the app hides the entry entirely
      // rather than offering a queue that can never fill.
      expect(ApprovalQueue.unavailable.available, isFalse);
      const empty = ApprovalQueue(available: true, requests: []);
      expect(empty.available, isTrue);
      expect(empty.isEmpty, isTrue);
    });
  });
}
