import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/config/app_config.dart';
import 'package:perfect_hr_mobile/core/errors/app_failure.dart';
import 'package:perfect_hr_mobile/core/security/passkey_service.dart';
import 'package:perfect_hr_mobile/features/authentication/application/auth_providers.dart';
import 'package:perfect_hr_mobile/features/settings/application/authenticator_providers.dart';
import 'package:perfect_hr_mobile/features/settings/application/enrolment_controller.dart';
import 'package:perfect_hr_mobile/features/settings/data/authenticator_repository.dart';
import 'package:perfect_hr_mobile/features/settings/domain/authenticator_status.dart';

/// Native enrolment: registering this phone without leaving the app.
///
/// The rule that matters most: when the user already holds a device, the proof
/// of the old one and the creation of the new one must travel in **one
/// request**. The server consumes that proof within the request that stores the
/// credential, so splitting them is precisely the bug that made second devices
/// impossible for months.

class _StubRepository implements AuthenticatorRepository {
  _StubRepository({this.stepUp, this.completeError});

  final Map<String, dynamic>? stepUp;
  final Object? completeError;

  int stepUpCalls = 0;
  int completeCalls = 0;
  Map<String, dynamic>? sentAssertion;
  Map<String, dynamic>? sentCredential;
  String? sentLabel;

  @override
  Future<AuthenticatorStatus> loadStatus() async =>
      MockAuthenticatorRepository.sample();

  @override
  Future<Map<String, dynamic>?> stepUpChallenge() async {
    stepUpCalls++;
    return stepUp;
  }

  @override
  Future<Map<String, dynamic>> enrolmentOptions() async =>
      const {'challenge': 'create-me'};

  @override
  Future<AuthenticatorStatus> completeEnrolment({
    required Map<String, dynamic> credential,
    required String deviceLabel,
    Map<String, dynamic>? assertion,
  }) async {
    completeCalls++;
    sentCredential = credential;
    sentLabel = deviceLabel;
    sentAssertion = assertion;
    final error = completeError;
    if (error != null) throw error;
    return MockAuthenticatorRepository.sample();
  }
}

class _StubPasskeys implements PasskeyService {
  _StubPasskeys({this.available = true, this.createFailure, this.getFailure});

  final bool available;
  final PasskeyFailure? createFailure;
  final PasskeyFailure? getFailure;

  int getCalls = 0;
  int createCalls = 0;

  // Diagnostics are for the About screen, not for a ceremony. Empty here.
  @override
  Future<Map<String, String>> diagnostics() async => const {};

  @override
  Future<bool> get isAvailable async => available;

  @override
  Future<Map<String, dynamic>> get(Map<String, dynamic> optionsJson) async {
    getCalls++;
    final failure = getFailure;
    if (failure != null) throw failure;
    return const {'id': 'assertion'};
  }

  @override
  Future<Map<String, dynamic>> create(Map<String, dynamic> optionsJson) async {
    createCalls++;
    final failure = createFailure;
    if (failure != null) throw failure;
    return const {'id': 'new-credential'};
  }
}

ProviderContainer _container(
  _StubRepository repository,
  _StubPasskeys passkeys,
) {
  return ProviderContainer(
    overrides: [
      authenticatorRepositoryProvider.overrideWithValue(repository),
      passkeyServiceProvider.overrideWithValue(passkeys),
    ],
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(AppConfig.initialise);

  group('a first device', () {
    test('raises one prompt, and sends no assertion', () async {
      // There is nothing yet to prove control of, so asking the user to confirm
      // on a device they do not have would be an unanswerable prompt.
      final repository = _StubRepository(stepUp: null);
      final passkeys = _StubPasskeys();
      final container = _container(repository, passkeys);
      addTearDown(container.dispose);

      final enrolled = await container
          .read(enrolmentControllerProvider.notifier)
          .enrol(deviceLabel: 'My phone');

      expect(enrolled, isTrue);
      expect(passkeys.getCalls, 0, reason: 'no existing device to confirm on');
      expect(passkeys.createCalls, 1);
      expect(repository.sentAssertion, isNull);
      expect(repository.sentLabel, 'My phone');
      expect(repository.sentCredential, const {'id': 'new-credential'});
    });
  });

  group('a second device', () {
    test('confirms on the old one, then creates the new one', () async {
      final repository = _StubRepository(stepUp: const {'challenge': 'confirm'});
      final passkeys = _StubPasskeys();
      final container = _container(repository, passkeys);
      addTearDown(container.dispose);

      final enrolled = await container
          .read(enrolmentControllerProvider.notifier)
          .enrol(deviceLabel: 'Second phone');

      expect(enrolled, isTrue);
      expect(passkeys.getCalls, 1);
      expect(passkeys.createCalls, 1);
    });

    test('sends both in the same request', () async {
      // The load-bearing assertion. The server consumes the proof of the old
      // device inside the request that stores the new one; a separate call
      // would arrive with the marker already gone, and the enrolment would be
      // refused with a message about confirming on a device you just confirmed
      // on.
      final repository = _StubRepository(stepUp: const {'challenge': 'confirm'});
      final container = _container(repository, _StubPasskeys());
      addTearDown(container.dispose);

      await container
          .read(enrolmentControllerProvider.notifier)
          .enrol(deviceLabel: 'Second phone');

      expect(repository.completeCalls, 1);
      expect(repository.sentAssertion, const {'id': 'assertion'});
      expect(repository.sentCredential, const {'id': 'new-credential'});
    });

    test('does not create anything if the old device is not confirmed',
        () async {
      // Otherwise the user answers a fingerprint prompt to register a device
      // the server is certain to reject.
      final repository = _StubRepository(stepUp: const {'challenge': 'confirm'});
      final passkeys = _StubPasskeys(
        getFailure: const PasskeyFailure(
          PasskeyFailureKind.failed,
          'Wrong device.',
        ),
      );
      final container = _container(repository, passkeys);
      addTearDown(container.dispose);

      final enrolled = await container
          .read(enrolmentControllerProvider.notifier)
          .enrol(deviceLabel: 'Second phone');

      expect(enrolled, isFalse);
      expect(passkeys.createCalls, 0);
      expect(repository.completeCalls, 0);
    });
  });

  group('when it does not work', () {
    test('cancelling is not an error', () async {
      // Dismissing the prompt is a decision. A red failure for it is the app
      // apologising for something the user did on purpose.
      final container = _container(
        _StubRepository(stepUp: null),
        _StubPasskeys(
          createFailure: const PasskeyFailure(
            PasskeyFailureKind.cancelled,
            'Cancelled.',
          ),
        ),
      );
      addTearDown(container.dispose);

      final enrolled = await container
          .read(enrolmentControllerProvider.notifier)
          .enrol(deviceLabel: 'My phone');

      expect(enrolled, isFalse);
      expect(container.read(enrolmentControllerProvider).hasError, isFalse);
    });

    test('an already-registered device says what to do instead', () async {
      // This is the server's excludeCredentials working as intended: one device
      // must not satisfy a two-device rule on its own. The message has to name
      // the remedy, because "try again" would be advice that cannot ever work.
      final container = _container(
        _StubRepository(stepUp: const {'challenge': 'confirm'}),
        _StubPasskeys(
          createFailure: const PasskeyFailure(
            PasskeyFailureKind.alreadyRegistered,
            'InvalidStateError',
          ),
        ),
      );
      addTearDown(container.dispose);

      await container
          .read(enrolmentControllerProvider.notifier)
          .enrol(deviceLabel: 'Second phone');

      final state = container.read(enrolmentControllerProvider);
      expect(state.hasError, isTrue);
      final message = asAppFailure(state.error!, state.stackTrace).userMessage;
      expect(message, contains('already has a Perfect HR security device'));
      expect(message, contains('security key'));
      expect(message, isNot(contains('InvalidStateError')));
    });

    test('a phone without the API is sent to the browser', () async {
      // An older Android, or no screen lock. The browser route still works, and
      // saying so is more useful than reporting a failure.
      final repository = _StubRepository(stepUp: null);
      final container = _container(
        repository,
        _StubPasskeys(available: false),
      );
      addTearDown(container.dispose);

      final enrolled = await container
          .read(enrolmentControllerProvider.notifier)
          .enrol(deviceLabel: 'My phone');

      expect(enrolled, isFalse);
      expect(repository.stepUpCalls, 0, reason: 'nothing should be started');
      final state = container.read(enrolmentControllerProvider);
      expect(
        asAppFailure(state.error!, state.stackTrace).userMessage,
        contains('Use the browser instead'),
      );
    });

    test('a server refusal reaches the user in the server\'s own words',
        () async {
      // The enrolment-route refusals explain exactly why an enrolment was not
      // permitted — break-glass recovery, for instance. Replacing them with a
      // generic message would throw away the only useful part.
      final container = _container(
        _StubRepository(
          stepUp: null,
          completeError: const ValidationFailure(
            userMessage: 'You previously had an authenticator and none is '
                'currently usable.',
          ),
        ),
        _StubPasskeys(),
      );
      addTearDown(container.dispose);

      await container
          .read(enrolmentControllerProvider.notifier)
          .enrol(deviceLabel: 'My phone');

      final state = container.read(enrolmentControllerProvider);
      expect(
        asAppFailure(state.error!, state.stackTrace).userMessage,
        contains('none is currently usable'),
      );
    });
  });
}
