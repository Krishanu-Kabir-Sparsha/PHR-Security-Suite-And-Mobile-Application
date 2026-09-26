import 'package:flutter_test/flutter_test.dart';
import 'package:perfect_hr_mobile/core/utilities/server_time.dart';

/// Reading a timestamp the server sent.
///
/// The regression these guard produced no error and no log — it simply showed
/// every attendance six hours early in Dhaka, with times that looked entirely
/// plausible. It was found by eye, not by a test, which is the argument for
/// these being here.
void main() {
  group('parseServerTime', () {
    test('a naive timestamp is read as UTC, not as local', () {
      // THE regression. Odoo stores naive UTC; Dart's own parse reads a string
      // with no offset as local, so `.toLocal()` was a no-op and the value was
      // wrong by the device's offset.
      final parsed = parseServerTime('2026-09-26 05:53:00');
      expect(parsed, isNotNull);
      expect(parsed!.toUtc().hour, 5);
      expect(parsed.toUtc().minute, 53);
    });

    test('the current format with Z gives the same instant', () {
      // The server was fixed to send this; the legacy form above still has to
      // work, because the on-device cache is full of it.
      final legacy = parseServerTime('2026-09-26 05:53:00');
      final current = parseServerTime('2026-09-26T05:53:00Z');
      expect(current, isNotNull);
      expect(current!.isAtSameMomentAs(legacy!), isTrue);
    });

    test('an explicit offset is honoured rather than overridden', () {
      // 05:53+06:00 is 23:53 UTC the previous day. Treating it as UTC would
      // move it six hours and across a date boundary.
      final parsed = parseServerTime('2026-09-26T05:53:00+06:00');
      expect(parsed, isNotNull);
      expect(parsed!.toUtc().day, 25);
      expect(parsed.toUtc().hour, 23);
      expect(parsed.toUtc().minute, 53);
    });

    test('the result is local, so the UI needs no further conversion', () {
      expect(parseServerTime('2026-09-26T05:53:00Z')!.isUtc, isFalse);
    });

    test('Odoo falsey values are null, not epoch', () {
      // Odoo sends `false` for an empty datetime. Parsed naively that becomes
      // null anyway, but "false" as a string reaching a date formatter would
      // throw on a screen that was merely missing a check-out.
      for (final empty in [null, '', '  ', 'false', 'null']) {
        expect(parseServerTime(empty), isNull, reason: 'for $empty');
      }
    });

    test('garbage is null rather than an exception', () {
      expect(parseServerTime('not a date'), isNull);
    });
  });

  group('serialiseInstant', () {
    test('a cache round trip preserves the instant exactly', () {
      // The regression this guards was introduced *by* the fix above, and
      // caught only by an existing round-trip test. toIso8601String() on a
      // local DateTime emits no offset, which parseServerTime then reads as
      // UTC -- so every write-then-read shifted the value by the device's
      // offset, and two of them put a phone in Dhaka twelve hours out.
      final original = parseServerTime('2026-09-08T09:04:00Z')!;
      final round = parseServerTime(serialiseInstant(original));
      expect(round, isNotNull);
      expect(round!.isAtSameMomentAs(original), isTrue);
    });

    test('what is written always carries a zone', () {
      final written = serialiseInstant(DateTime.now());
      expect(written, isNotNull);
      expect(written!.endsWith('Z'), isTrue);
    });

    test('null in, null out', () {
      expect(serialiseInstant(null), isNull);
    });
  });

  group('parseServerDate', () {
    test('a calendar day is not shifted by a timezone', () {
      // The trap: running a date through the timestamp parser places it at
      // midnight UTC and then converts, which west of Greenwich moves it to
      // the previous day — so a day's attendance files itself under yesterday.
      final parsed = parseServerDate('2026-09-26');
      expect(parsed, isNotNull);
      expect(parsed!.year, 2026);
      expect(parsed.month, 9);
      expect(parsed.day, 26);
    });

    test('a datetime is truncated to its date', () {
      expect(parseServerDate('2026-09-26T05:53:00Z')!.day, 26);
      expect(parseServerDate('2026-09-26 05:53:00')!.day, 26);
    });

    test('empty and malformed are null', () {
      for (final bad in [null, '', 'false', '2026-09', 'nope']) {
        expect(parseServerDate(bad), isNull, reason: 'for $bad');
      }
    });
  });
}
