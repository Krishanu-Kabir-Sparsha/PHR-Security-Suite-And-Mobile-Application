/// Parsing timestamps the server sent.
///
/// ## The bug this exists to prevent
///
/// Odoo stores datetimes as **naive UTC** and, before 18.0.1.13.0, serialised
/// them as `"2026-09-26 05:53:00"` — no `T`, no `Z`, nothing saying which zone
/// that is. `DateTime.parse` follows ISO-8601 and reads a timestamp with no
/// offset as **local**, so `.toLocal()` on the result is a no-op and the value
/// is simply wrong by the device's UTC offset.
///
/// In Dhaka (UTC+6) that showed a check-in made at 11:53 as "5:53 AM". Nothing
/// threw, nothing logged, and the times looked entirely plausible — which is
/// why it survived. It was caught by noticing an attendance row timed 5:53 AM
/// on a phone whose own clock read 11:56 AM.
///
/// The server now sends `2026-09-26T05:53:00Z`. This function still assumes
/// UTC for a string without an offset, and that is deliberate belt-and-braces:
///
/// * the Drift cache still holds payloads written in the old format, and a
///   returning user would otherwise see six hours of wrong history until it
///   expired;
/// * a tenant may be running an older server than the app;
/// * every Odoo datetime is UTC, so the assumption is true by construction.
///
/// Anything that parses a timestamp from the server goes through here. There
/// were six independent copies of `DateTime.tryParse(...)?.toLocal()` and every
/// one of them carried the same defect.
library;

/// Parse a server timestamp into a **local** [DateTime], or null.
///
/// Accepts what Odoo actually emits, in either format:
///
///     2026-09-26T05:53:00Z       current
///     2026-09-26 05:53:00        legacy, and any cached payload
///     2026-09-26T05:53:00+06:00  an explicit offset is honoured as given
DateTime? parseServerTime(Object? value) {
  if (value == null) return null;
  final raw = '$value'.trim();
  if (raw.isEmpty || raw == 'null' || raw == 'false') return null;

  // Odoo's legacy form uses a space; ISO-8601 wants a T.
  final normalised = raw.contains('T') ? raw : raw.replaceFirst(' ', 'T');

  final parsed = DateTime.tryParse(normalised);
  if (parsed == null) return null;

  // `isUtc` is true only when the string carried a Z. An explicit numeric
  // offset is already resolved correctly by parse(), and its result is not
  // flagged UTC — so the test below must not catch that case, and does not:
  // such a string contains a '+', or a '-' after the time separator.
  if (parsed.isUtc) return parsed.toLocal();
  if (_hasExplicitOffset(normalised)) return parsed.toLocal();

  // No zone information at all. Odoo means UTC, so say so, then convert.
  return DateTime.utc(
    parsed.year,
    parsed.month,
    parsed.day,
    parsed.hour,
    parsed.minute,
    parsed.second,
    parsed.millisecond,
    parsed.microsecond,
  ).toLocal();
}

/// True when the string carries a numeric UTC offset such as `+06:00`.
///
/// Only the part after the date is examined, because the date itself contains
/// hyphens that would otherwise read as a negative offset.
bool _hasExplicitOffset(String value) {
  final t = value.indexOf('T');
  if (t < 0) return false;
  final time = value.substring(t);
  return time.contains('+') || time.contains('-');
}

/// Write an instant for the on-device cache, as UTC with a `Z`.
///
/// The counterpart to [parseServerTime], and it has to exist for the same
/// reason. `DateTime.toIso8601String()` on a **local** value emits
/// `2026-09-08T15:04:00.000` — no offset — which [parseServerTime] then reads
/// as UTC, shifting it again on every cache round trip. Two reads and a phone
/// in Dhaka is twelve hours out.
///
/// Caught by a round-trip test rather than by eye, which is the argument for
/// having had one.
String? serialiseInstant(DateTime? value) =>
    value?.toUtc().toIso8601String();

/// Parse a calendar date (`YYYY-MM-DD`) with no timezone conversion.
///
/// A calendar day has no zone. Running it through [parseServerTime] would place
/// it at midnight UTC and then shift it, which west of Greenwich moves it to
/// the previous day — so a day's attendance would file itself under yesterday.
DateTime? parseServerDate(Object? value) {
  if (value == null) return null;
  final raw = '$value'.trim();
  if (raw.isEmpty || raw == 'null' || raw == 'false') return null;
  final parts = raw.split(RegExp(r'[T ]')).first.split('-');
  if (parts.length != 3) return null;
  final year = int.tryParse(parts[0]);
  final month = int.tryParse(parts[1]);
  final day = int.tryParse(parts[2]);
  if (year == null || month == null || day == null) return null;
  return DateTime(year, month, day);
}
