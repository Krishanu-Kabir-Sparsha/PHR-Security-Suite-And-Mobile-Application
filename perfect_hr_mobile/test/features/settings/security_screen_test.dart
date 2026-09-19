import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/theme/app_theme.dart';
import 'package:perfect_hr_mobile/features/settings/application/authenticator_providers.dart';
import 'package:perfect_hr_mobile/features/settings/data/authenticator_repository.dart';
import 'package:perfect_hr_mobile/features/settings/domain/authenticator_status.dart';
import 'package:perfect_hr_mobile/features/settings/presentation/security_screen.dart';

/// SET-02 Security. Covers the enrolment status the screen reports, which is
/// the part a user acts on: an approver who believes they are covered when they
/// are not will discover it at the moment they try to approve something.

class _StubRepository implements AuthenticatorRepository {
  _StubRepository(this.status, {this.failure});

  final AuthenticatorStatus status;
  final Object? failure;
  int loadCount = 0;

  @override
  Future<AuthenticatorStatus> loadStatus() async {
    loadCount++;
    final f = failure;
    if (f != null) throw f;
    return status;
  }
}

AuthenticatorStatus _status({
  int enrolled = 1,
  int required_ = 2,
  bool sufficient = false,
  bool configured = true,
  String? relyingParty = 'dev.perfecthr.net',
  String? enrolUrl = 'https://dev.perfecthr.net/webauthn/enroll',
  List<EnrolledAuthenticator> devices = const [],
}) {
  return AuthenticatorStatus(
    enrolled: enrolled,
    required_: required_,
    sufficient: sufficient,
    configured: configured,
    relyingParty: relyingParty,
    enrolUrl: enrolUrl,
    devices: devices,
  );
}

Widget _app(ProviderContainer container) {
  return UncontrolledProviderScope(
    container: container,
    child: MaterialApp(theme: AppTheme.light(), home: const SecurityScreen()),
  );
}

ProviderContainer _container(AuthenticatorRepository repository) {
  final container = ProviderContainer(
    overrides: [
      authenticatorRepositoryProvider.overrideWithValue(repository),
    ],
  );
  return container;
}

Future<void> _pump(WidgetTester tester, ProviderContainer container) async {
  tester.view.physicalSize = const Size(1200, 3000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(_app(container));
  await tester.pumpAndSettle();
}

void main() {
  group('SET-02 enrolment status', () {
    testWidgets('an under-enrolled approver is told action is needed',
        (tester) async {
      final container = _container(_StubRepository(_status()));
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Action needed'), findsOneWidget);
      expect(find.text('1 of 2'), findsOneWidget);
    });

    testWidgets('a fully enrolled approver reads as protected', (tester) async {
      final container = _container(
        _StubRepository(_status(enrolled: 2, sufficient: true)),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Protected'), findsOneWidget);
      expect(find.text('2 of 2'), findsOneWidget);
    });

    testWidgets(
        'a role needing no key reads as not required, never as protected',
        (tester) async {
      // The distinction matters. Telling someone with no key that they are
      // "Protected" is a lie they would only discover at an approval screen.
      final container = _container(
        _StubRepository(_status(enrolled: 0, required_: 0, sufficient: true)),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Not required'), findsOneWidget);
      expect(find.text('Protected'), findsNothing);
    });

    testWidgets('the outstanding count never goes negative', (tester) async {
      // Three devices against a requirement of two is not "-1 more to enrol".
      final container = _container(
        _StubRepository(_status(enrolled: 3, sufficient: true)),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.textContaining('-1'), findsNothing);
      expect(find.text('Protected'), findsOneWidget);
    });
  });

  group('enrolment affordance', () {
    testWidgets('offers to enrol the first device when none exist',
        (tester) async {
      final container = _container(
        _StubRepository(_status(enrolled: 0, required_: 1)),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Enrol this device'), findsOneWidget);
      expect(find.text('Add another device'), findsNothing);
    });

    testWidgets('offers to add another once one is enrolled', (tester) async {
      final container = _container(_StubRepository(_status()));
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Add another device'), findsOneWidget);
    });

    testWidgets(
        'an unconfigured server explains itself instead of offering enrolment',
        (tester) async {
      // Opening the enrolment page against a server with no relying party set
      // shows only a red error block, so the button must not be offered.
      final container = _container(
        _StubRepository(
          _status(configured: false, enrolUrl: null, relyingParty: null),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Enrolment is not available yet'), findsOneWidget);
      expect(find.text('Enrol this device'), findsNothing);
      expect(find.text('Add another device'), findsNothing);
    });

    testWidgets('states that the fingerprint never leaves the device',
        (tester) async {
      // The promise on the enrolment page, repeated where the user decides.
      final container = _container(_StubRepository(_status()));
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.textContaining('never leaves it'), findsOneWidget);
    });
  });

  group('device list', () {
    testWidgets('lists an enrolled device with its label', (tester) async {
      final container = _container(
        _StubRepository(
          _status(
            devices: [
              EnrolledAuthenticator(
                id: '1',
                label: 'Work PC',
                enrolledAt: DateTime(2026, 9, 9),
              ),
            ],
          ),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.text('Work PC'), findsOneWidget);
    });

    testWidgets('says plainly when a credential is cloud-synced',
        (tester) async {
      // A synced passkey is not bound to one handset, which changes what
      // holding it proves for a final-approval role. Not hidden.
      final container = _container(
        _StubRepository(
          _status(
            devices: const [
              EnrolledAuthenticator(
                id: '1',
                label: 'Phone passkey',
                backedUp: true,
              ),
            ],
          ),
        ),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.textContaining('cloud keychain'), findsOneWidget);
    });

    testWidgets('an empty list reads as a statement, not a blank', (tester) async {
      final container = _container(
        _StubRepository(_status(enrolled: 0, required_: 1)),
      );
      addTearDown(container.dispose);
      await _pump(tester, container);

      expect(find.textContaining('No security key is enrolled'), findsOneWidget);
    });
  });

  group('parsing', () {
    test('reads the documented payload', () {
      final status = AuthenticatorStatus.fromJson(const {
        'enrolled': 1,
        'required': 2,
        'sufficient': false,
        'configured': true,
        'relying_party': 'dev.perfecthr.net',
        'enrol_url': 'https://dev.perfecthr.net/webauthn/enroll',
        'requires_web_session': true,
        'devices': [
          {
            'id': '3',
            'label': 'Work PC',
            'enrolled_at': '2026-09-09 05:29:30',
            'backed_up': false,
          }
        ],
      });

      expect(status.enrolled, 1);
      expect(status.required_, 2);
      expect(status.sufficient, isFalse);
      expect(status.canEnrol, isTrue);
      expect(status.outstanding, 1);
      expect(status.devices.single.label, 'Work PC');
      expect(status.devices.single.enrolledAt?.year, 2026);
    });

    test('an empty payload degrades instead of throwing', () {
      // A server that predates this endpoint must not crash the screen.
      final status = AuthenticatorStatus.fromJson(const {});
      expect(status.enrolled, 0);
      expect(status.configured, isFalse);
      expect(status.canEnrol, isFalse);
      expect(status.devices, isEmpty);
    });

    test('canEnrol is false without a URL even when configured', () {
      final status = AuthenticatorStatus.fromJson(const {
        'configured': true,
        'enrol_url': '',
      });
      expect(status.canEnrol, isFalse);
    });
  });
}
