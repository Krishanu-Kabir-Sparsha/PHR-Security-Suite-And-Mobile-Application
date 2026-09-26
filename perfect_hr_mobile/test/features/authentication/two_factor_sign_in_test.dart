import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/config/app_config.dart';
import 'package:perfect_hr_mobile/core/errors/app_failure.dart';
import 'package:perfect_hr_mobile/core/security/device_key_service.dart';
import 'package:perfect_hr_mobile/core/security/passkey_service.dart';
import 'package:perfect_hr_mobile/core/session/permissions.dart';
import 'package:perfect_hr_mobile/core/session/session_controller.dart';
import 'package:perfect_hr_mobile/core/session/session_state.dart';
import 'package:perfect_hr_mobile/core/session/user_role.dart';
import 'package:perfect_hr_mobile/features/authentication/application/auth_providers.dart';
import 'package:perfect_hr_mobile/features/authentication/application/pair_device_controller.dart';
import 'package:perfect_hr_mobile/features/authentication/data/auth_repository.dart';
import 'package:perfect_hr_mobile/features/authentication/data/secure_token_store.dart';
import 'package:perfect_hr_mobile/features/authentication/domain/auth_session.dart';
import 'package:perfect_hr_mobile/features/authentication/domain/sign_in_outcome.dart';

/// Two-factor sign-in.
///
/// The rule the whole thing rests on: **no session exists until both factors
/// pass.** A password proves knowledge of a secret; the device proves it is the
/// person who holds it. Most of what follows is about the ways that must not be
/// short-circuited — and about cancellation, which is a decision rather than a
/// failure and must not be shown as an error.

AuthSession _session({bool enrolmentRequired = false}) {
  return AuthSession(
    accessToken: 'access',
    refreshToken: 'refresh',
    expiresAt: DateTime.now().add(const Duration(hours: 1)),
    enrolmentRequired: enrolmentRequired,
    user: const SessionUser(
      employeeId: '1',
      displayName: 'Test Person',
      role: UserRole.employee,
      tenantId: '1',
      tenantName: 'Perfect HR',
      permissions: PermissionSet.empty,
    ),
  );
}

class _StubRepository implements AuthRepository {
  _StubRepository({required this.outcome, this.completed});

  final SignInOutcome outcome;
  final AuthSession? completed;

  int completeCount = 0;
  int completeWithDeviceCount = 0;
  int pairCount = 0;
  Map<String, dynamic>? sentAssertion;
  Map<String, dynamic>? sentSignature;
  String? sentMfaToken;
  String? sentPublicKey;
  String? sentCompanyId;
  String? sentAuthMode;
  String? switchedToCompanyId;

  @override
  Future<SignInOutcome> signIn({
    required String login,
    required String password,
    String? deviceLabel,
    String? companyId,
    String? authMode,
  }) async {
    sentCompanyId = companyId;
    sentAuthMode = authMode;
    return outcome;
  }

  @override
  Future<AuthSession> switchCompany({
    required String accessToken,
    required String companyId,
  }) async {
    switchedToCompanyId = companyId;
    return completed ?? _session();
  }

  @override
  Future<AuthSession> completeSignIn({
    required String mfaToken,
    required Map<String, dynamic> assertion,
  }) async {
    completeCount++;
    sentMfaToken = mfaToken;
    sentAssertion = assertion;
    return completed ?? _session();
  }

  @override
  Future<AuthSession> completeSignInWithDevice({
    required String mfaToken,
    required Map<String, dynamic> signaturePayload,
  }) async {
    completeWithDeviceCount++;
    sentMfaToken = mfaToken;
    sentSignature = signaturePayload;
    return completed ?? _session();
  }

  @override
  Future<DevicePairing> pairDevice({
    required String login,
    required String code,
    required String publicKey,
    required String deviceLabel,
    required String platform,
  }) async {
    pairCount++;
    sentPublicKey = publicKey;
    return DevicePairing(
      deviceHandle: 'handle-1',
      deviceLabel: deviceLabel,
      userLogin: login,
      userName: 'Test Person',
    );
  }

  @override
  Future<AuthSession> refresh(String refreshToken) async =>
      throw UnimplementedError();

  @override
  Future<void> signOut(String accessToken) async {}
}

/// A paired installation whose key signs on demand.
class _StubDeviceKeys implements DeviceKeyService {
  _StubDeviceKeys({
    this.failure,
    this.supported = true,
    this.paired = true,
  });

  final DeviceKeyFailure? failure;
  final bool supported;
  final bool paired;

  int signCalls = 0;
  int rememberCalls = 0;
  String? signedChallenge;
  String? signedContext;

  @override
  Future<bool> get isSupported async => supported;

  @override
  Future<DeviceBinding?> get binding async => paired
      ? const DeviceBinding(
          handle: 'handle-1',
          login: 'someone',
          label: 'Test phone',
          counter: 7,
        )
      : null;

  @override
  Future<String> generateKeyPair() async => 'generated-public-key';

  @override
  Future<void> rememberPairing({
    required String publicKey,
    required String handle,
    required String login,
    required String label,
  }) async {
    rememberCalls++;
  }

  @override
  Future<DeviceSignature> sign({
    required String challenge,
    required String contextRef,
    required String reason,
  }) async {
    signCalls++;
    signedChallenge = challenge;
    signedContext = contextRef;
    final thrown = failure;
    if (thrown != null) throw thrown;
    return DeviceSignature(
      deviceHandle: 'handle-1',
      challenge: challenge,
      counter: 8,
      signature: 'signed',
    );
  }

  @override
  Future<void> forget() async {}
}

class _StubPasskeys implements PasskeyService {
  _StubPasskeys({this.assertion, this.failure});

  final Map<String, dynamic>? assertion;
  final PasskeyFailure? failure;

  Map<String, dynamic>? receivedChallenge;

  // Diagnostics are for the About screen, not for a ceremony. Empty here.
  @override
  Future<Map<String, String>> diagnostics() async => const {};

  @override
  Future<bool> get isAvailable async => true;

  @override
  Future<Map<String, dynamic>> create(Map<String, dynamic> optionsJson) async =>
      throw UnimplementedError();

  @override
  Future<Map<String, dynamic>> get(Map<String, dynamic> optionsJson) async {
    receivedChallenge = optionsJson;
    final thrown = failure;
    if (thrown != null) throw thrown;
    return assertion ?? const {'id': 'assertion'};
  }
}

ProviderContainer _container(
  _StubRepository repository,
  PasskeyService passkeys, {
  DeviceKeyService? deviceKeys,
}) {
  return ProviderContainer(
    overrides: [
      authRepositoryProvider.overrideWithValue(repository),
      passkeyServiceProvider.overrideWithValue(passkeys),
      deviceKeyServiceProvider
          .overrideWithValue(deviceKeys ?? _StubDeviceKeys()),
      secureTokenStoreProvider.overrideWith(
        (ref) => SecureTokenStore(repository: repository),
      ),
    ],
  );
}

const _needsDevice = SignInNeedsDevice(
  mfaToken: 'handle-123',
  method: SecondFactorMethod.passkey,
  challenge: {'challenge': 'abc'},
);

/// The server asking for this installation's own paired key instead.
const _needsPairedDevice = SignInNeedsDevice(
  mfaToken: 'handle-123',
  method: SecondFactorMethod.device,
  deviceChallenge: {
    'challenge': 'nonce-abc',
    'context_ref': 'perfecthr.mobile.session,login',
  },
);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    AppConfig.initialise();
    FlutterSecureStorage.setMockInitialValues({});
  });

  group('when the account has a device', () {
    test('the password alone does not sign anybody in', () async {
      // The load-bearing assertion. If this ever passes on one factor, a
      // stolen password is a working session.
      final repository = _StubRepository(outcome: _needsDevice);
      final container = _container(
        repository,
        _StubPasskeys(
          failure: const PasskeyFailure(
            PasskeyFailureKind.cancelled,
            'Cancelled.',
          ),
        ),
      );
      addTearDown(container.dispose);

      final signedIn = await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right-password');

      expect(signedIn, isFalse);
      expect(
        container.read(sessionControllerProvider),
        isA<SessionUnauthenticated>(),
      );
      expect(await container.read(secureTokenStoreProvider).read(), isNull);
    });

    test('the challenge reaches the platform untouched', () async {
      // The server builds the WebAuthn request and parses the response. If the
      // app reshaped either, there would be two implementations to keep in
      // agreement instead of one.
      const challenge = {
        'challenge': 'abc',
        'rpId': 'dev.perfecthr.net',
        'allowCredentials': [
          {'type': 'public-key', 'id': 'cred-1'},
        ],
      };
      final passkeys = _StubPasskeys();
      final container = _container(
        _StubRepository(
          outcome: const SignInNeedsDevice(
            mfaToken: 'handle',
            method: SecondFactorMethod.passkey,
            challenge: challenge,
          ),
        ),
        passkeys,
      );
      addTearDown(container.dispose);

      await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      expect(passkeys.receivedChallenge, challenge);
    });

    test('a confirmed device completes the sign-in', () async {
      final repository = _StubRepository(outcome: _needsDevice);
      final container = _container(
        repository,
        _StubPasskeys(assertion: const {'id': 'signed'}),
      );
      addTearDown(container.dispose);

      final signedIn = await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      expect(signedIn, isTrue);
      expect(repository.completeCount, 1);
      expect(repository.sentMfaToken, 'handle-123');
      expect(repository.sentAssertion, const {'id': 'signed'});
      expect(
        container.read(sessionControllerProvider),
        isA<SessionAuthenticated>(),
      );
    });

    test('cancelling is not an error', () async {
      // Someone who dismisses the prompt made a choice. A red failure for it is
      // the app apologising for something they did on purpose.
      final repository = _StubRepository(outcome: _needsDevice);
      final container = _container(
        repository,
        _StubPasskeys(
          failure: const PasskeyFailure(
            PasskeyFailureKind.cancelled,
            'Cancelled.',
          ),
        ),
      );
      addTearDown(container.dispose);

      await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      expect(container.read(signInControllerProvider).hasError, isFalse);
      expect(repository.completeCount, 0);
    });

    test('no passkey on this phone explains what to do', () async {
      // The account has a device enrolled somewhere else. "Try again" would be
      // useless advice; the only remedy is to enrol this phone.
      final container = _container(
        _StubRepository(outcome: _needsDevice),
        _StubPasskeys(
          failure: const PasskeyFailure(
            PasskeyFailureKind.noCredential,
            'No credential.',
          ),
        ),
      );
      addTearDown(container.dispose);

      await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      final state = container.read(signInControllerProvider);
      expect(state.hasError, isTrue);
      expect(
        asAppFailure(state.error!, state.stackTrace).userMessage,
        contains('Enrol it on a device you already use'),
      );
    });
  });

  group('when the server asks for the paired device', () {
    // This path exists because the passkey one could not be made to work on a
    // handset: reaching a passkey from a native app needs the OS vendor to
    // validate an app-to-domain association, and when that fails it fails
    // closed with nothing to diagnose. A key this app issued itself has no
    // such dependency.

    test('signs the challenge and completes the sign-in', () async {
      final repository = _StubRepository(outcome: _needsPairedDevice);
      final keys = _StubDeviceKeys();
      final container = _container(repository, _StubPasskeys(), deviceKeys: keys);
      addTearDown(container.dispose);

      final signedIn = await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      expect(signedIn, isTrue);
      expect(keys.signCalls, 1);
      expect(repository.completeWithDeviceCount, 1);
      expect(repository.sentMfaToken, 'handle-123');
      expect(repository.sentSignature?['signature'], 'signed');
    });

    test('signs the sign-in context, not just the nonce', () async {
      // Without the context, a confirmation given to sign in could be replayed
      // as an override approval. Binding is the whole difference between a
      // signature and a bearer token.
      final keys = _StubDeviceKeys();
      final container = _container(
        _StubRepository(outcome: _needsPairedDevice),
        _StubPasskeys(),
        deviceKeys: keys,
      );
      addTearDown(container.dispose);

      await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      expect(keys.signedChallenge, 'nonce-abc');
      expect(keys.signedContext, 'perfecthr.mobile.session,login');
    });

    test('raises no passkey prompt', () async {
      // The server chooses the method; the app follows. Raising both prompts
      // would ask for a credential the account may not hold.
      final passkeys = _StubPasskeys();
      final container = _container(
        _StubRepository(outcome: _needsPairedDevice),
        passkeys,
      );
      addTearDown(container.dispose);

      await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      expect(passkeys.receivedChallenge, isNull);
    });

    test('no session exists when the fingerprint is refused', () async {
      final repository = _StubRepository(outcome: _needsPairedDevice);
      final container = _container(
        repository,
        _StubPasskeys(),
        deviceKeys: _StubDeviceKeys(
          failure: const DeviceKeyFailure(
            DeviceKeyFailureKind.failed,
            'Not recognised.',
          ),
        ),
      );
      addTearDown(container.dispose);

      final signedIn = await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      expect(signedIn, isFalse);
      expect(repository.completeWithDeviceCount, 0);
      expect(await container.read(secureTokenStoreProvider).read(), isNull);
    });

    test('cancelling is not an error', () async {
      final container = _container(
        _StubRepository(outcome: _needsPairedDevice),
        _StubPasskeys(),
        deviceKeys: _StubDeviceKeys(
          failure: const DeviceKeyFailure(
            DeviceKeyFailureKind.cancelled,
            'Cancelled.',
          ),
        ),
      );
      addTearDown(container.dispose);

      await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      expect(container.read(signInControllerProvider).hasError, isFalse);
    });

    test('an unpaired installation is told where the code comes from',
        () async {
      // The account has a paired device somewhere; this installation is not it
      // — usually a reinstall, which wipes the key. "Try again" would be advice
      // that can never work, so the message names the browser page instead.
      final container = _container(
        _StubRepository(outcome: _needsPairedDevice),
        _StubPasskeys(),
        deviceKeys: _StubDeviceKeys(
          failure: const DeviceKeyFailure(
            DeviceKeyFailureKind.notPaired,
            'Not paired.',
          ),
        ),
      );
      addTearDown(container.dispose);

      await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      final state = container.read(signInControllerProvider);
      final message = asAppFailure(state.error!, state.stackTrace).userMessage;
      // Names the menu an ordinary employee can actually reach. The old copy
      // sent them to Security Suite > Authenticators, whose root menu is gated
      // on group_plaza_viewer -- so the instruction was correct and the menu
      // was invisible to exactly the people being told to use it.
      expect(message, contains('Pair My Phone'));
      expect(message, contains('not paired'));
    });

    test('only a dismissal is silent; everything else is shown', () async {
      // The regression this guards. The presence check used to return false for
      // any unrecognised platform error, which upstream reads as "the user
      // changed their mind" -- so a build whose Activity could not raise a
      // biometric prompt made the Sign in button do nothing at all, with no
      // message anywhere. Silence must mean a decision, never a fault.
      final container = _container(
        _StubRepository(outcome: _needsPairedDevice),
        _StubPasskeys(),
        deviceKeys: _StubDeviceKeys(
          failure: const DeviceKeyFailure(
            DeviceKeyFailureKind.unavailableOnThisBuild,
            'This build of the app cannot show the fingerprint prompt.',
          ),
        ),
      );
      addTearDown(container.dispose);

      final signedIn = await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      expect(signedIn, isFalse);
      final state = container.read(signInControllerProvider);
      expect(state.hasError, isTrue, reason: 'a build fault must not be silent');
      expect(
        asAppFailure(state.error!, state.stackTrace).userMessage,
        contains('cannot show the fingerprint prompt'),
      );
    });

    test('a lockout is shown and is retryable', () async {
      // Distinct from a build fault: waiting actually does help here, so the
      // failure says so rather than sending the user to report a bug.
      final container = _container(
        _StubRepository(outcome: _needsPairedDevice),
        _StubPasskeys(),
        deviceKeys: _StubDeviceKeys(
          failure: const DeviceKeyFailure(
            DeviceKeyFailureKind.lockedOut,
            'Too many attempts. Wait a moment, then try again.',
          ),
        ),
      );
      addTearDown(container.dispose);

      await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      final state = container.read(signInControllerProvider);
      final failure = asAppFailure(state.error!, state.stackTrace);
      expect(failure.userMessage, contains('Too many attempts'));
      expect(failure.isRetryable, isTrue);
    });

    test('a handset with no screen lock is told to set one up', () async {
      final container = _container(
        _StubRepository(outcome: _needsPairedDevice),
        _StubPasskeys(),
        deviceKeys: _StubDeviceKeys(
          failure: const DeviceKeyFailure(
            DeviceKeyFailureKind.noScreenLock,
            'No lock.',
          ),
        ),
      );
      addTearDown(container.dispose);

      await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      final state = container.read(signInControllerProvider);
      expect(
        asAppFailure(state.error!, state.stackTrace).userMessage,
        contains('screen lock'),
      );
    });

    test('an older server that sends no method still gets a passkey', () async {
      // Forward compatibility in the direction that actually happens: the app
      // updates through the store before the server is upgraded.
      final outcome = SignInNeedsDevice.fromJson(const {
        'mfa_token': 'handle',
        'challenge': {'challenge': 'abc'},
      });
      expect(outcome.method, SecondFactorMethod.passkey);
    });
  });

  group('pairing this installation', () {
    test('stores the key only after the server accepts it', () async {
      // The order matters. Storing first would leave a private key on the
      // device with no counterpart on the server after any failed pairing, and
      // the next sign-in would raise a fingerprint prompt to produce a
      // signature nothing can verify.
      final repository = _StubRepository(outcome: _needsPairedDevice);
      final keys = _StubDeviceKeys(paired: false);
      final container = _container(repository, _StubPasskeys(), deviceKeys: keys);
      addTearDown(container.dispose);

      final name = await container
          .read(pairDeviceControllerProvider.notifier)
          .pair(login: 'someone', code: 'ABCD2345', deviceLabel: 'My phone');

      expect(name, 'Test Person');
      expect(repository.pairCount, 1);
      expect(repository.sentPublicKey, 'generated-public-key');
      expect(keys.rememberCalls, 1);
    });

    test('a handset with no screen lock is refused before any request',
        () async {
      // Pairing a device that cannot gate the key would produce a credential
      // that signs without anyone being present, which is the control switched
      // off while still appearing to be on.
      final repository = _StubRepository(outcome: _needsPairedDevice);
      final container = _container(
        repository,
        _StubPasskeys(),
        deviceKeys: _StubDeviceKeys(supported: false, paired: false),
      );
      addTearDown(container.dispose);

      final name = await container
          .read(pairDeviceControllerProvider.notifier)
          .pair(login: 'someone', code: 'ABCD2345', deviceLabel: 'My phone');

      expect(name, isNull);
      expect(repository.pairCount, 0, reason: 'nothing should be sent');
      final state = container.read(pairDeviceControllerProvider);
      expect(
        asAppFailure(state.error!, state.stackTrace).userMessage,
        contains('screen lock'),
      );
    });
  });

  group('when the account has no device yet', () {
    test('signs in, carrying the enrolment requirement', () async {
      // Nobody is locked out: a new joiner has never had a device to enrol
      // with. The server restricts what the token can reach instead.
      final repository = _StubRepository(
        outcome: SignInComplete(_session(enrolmentRequired: true)),
      );
      final container = _container(repository, _StubPasskeys());
      addTearDown(container.dispose);

      final signedIn = await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'newjoiner', password: 'right');

      expect(signedIn, isTrue);
      expect(repository.completeCount, 0, reason: 'no device to confirm with');

      final stored = await container.read(secureTokenStoreProvider).read();
      expect(stored?.enrolmentRequired, isTrue);
    });
  });

  group('the session model', () {
    test('keeps the enrolment requirement across a restart', () {
      // Lost here, a returning user is restored straight to Home holding a
      // token the server restricts to enrolment, and every screen answers 403
      // with nothing to explain it.
      final restored = AuthSession.fromStored(
        _session(enrolmentRequired: true).toJson(),
      );
      expect(restored.enrolmentRequired, isTrue);
    });

    test('keeps it across a token rotation', () {
      final rotated =
          _session(enrolmentRequired: true).copyWith(accessToken: 'new');
      expect(rotated.enrolmentRequired, isTrue);
    });

    test('defaults to not required when the server omits it', () {
      // An older server that predates the field must not put every user behind
      // an enrolment wall.
      final parsed = AuthSession.fromJson(const {
        'access_token': 'a',
        'refresh_token': 'r',
        'expires_in': 3600,
        'user': <String, Object?>{},
      });
      expect(parsed.enrolmentRequired, isFalse);
    });
  });

  group('the passkey bridge', () {
    test('maps each platform code to the right kind', () {
      // The three that are not failures must not be reported as one:
      // cancellation is a decision, no-credential means enrol, and
      // already-registered means use a different device. Collapsing them into
      // "something went wrong" is how a user retries the one thing that cannot
      // possibly work.
      expect(
        PasskeyService.kindForCode('cancelled'),
        PasskeyFailureKind.cancelled,
      );
      expect(
        PasskeyService.kindForCode('no_credential'),
        PasskeyFailureKind.noCredential,
      );
      expect(
        PasskeyService.kindForCode('already_registered'),
        PasskeyFailureKind.alreadyRegistered,
      );
      expect(
        PasskeyService.kindForCode('something_unmapped'),
        PasskeyFailureKind.failed,
      );
    });

    test('refuses rather than hangs on a platform without the bridge', () async {
      // These tests run on a desktop host, where there is no channel to answer.
      // Refusing is the correct behaviour: a caller awaiting a prompt that can
      // never appear would hang forever with nothing on screen.
      expect(await const PasskeyService().isAvailable, isFalse);
      await expectLater(
        const PasskeyService().get(const {'challenge': 'x'}),
        throwsA(
          isA<PasskeyFailure>().having(
            (f) => f.kind,
            'kind',
            PasskeyFailureKind.unsupported,
          ),
        ),
      );
    });
  });

  group('the enrolment gate', () {
    test('a session with no device is flagged on the session state', () async {
      // The router redirects on this. Without it the user lands on Home with a
      // token the server restricts to enrolment, and every screen answers 403
      // with nothing to explain it.
      final container = _container(
        _StubRepository(
          outcome: SignInComplete(_session(enrolmentRequired: true)),
        ),
        _StubPasskeys(),
      );
      addTearDown(container.dispose);

      await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'newjoiner', password: 'right');

      final state = container.read(sessionControllerProvider);
      expect(state, isA<SessionAuthenticated>());
      expect((state as SessionAuthenticated).enrolmentRequired, isTrue);
    });

    test('a normal sign-in is not flagged', () async {
      final container = _container(
        _StubRepository(outcome: SignInComplete(_session())),
        _StubPasskeys(),
      );
      addTearDown(container.dispose);

      await container
          .read(signInControllerProvider.notifier)
          .signIn(login: 'someone', password: 'right');

      final state =
          container.read(sessionControllerProvider) as SessionAuthenticated;
      expect(state.enrolmentRequired, isFalse);
    });

    test('finishing enrolment changes the navigation signature', () {
      // The router is rebuilt only when this string changes. If enrolment did
      // not appear in it, somebody who had just registered a device would stay
      // stuck on the screen they had satisfied.
      const enrolling = SessionAuthenticated(
        user: SessionUser(
          employeeId: '1',
          displayName: 'X',
          role: UserRole.employee,
          tenantId: '1',
          tenantName: 'T',
        ),
        enrolmentRequired: true,
      );
      const ready = SessionAuthenticated(
        user: SessionUser(
          employeeId: '1',
          displayName: 'X',
          role: UserRole.employee,
          tenantId: '1',
          tenantName: 'T',
        ),
      );
      expect(enrolling.navigationSignature,
          isNot(ready.navigationSignature));
    });
  });
}
