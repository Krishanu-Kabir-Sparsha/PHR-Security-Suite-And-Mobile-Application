# Check-in, check-out, breaks and location

**Last updated:** 2026-09-26
**Audience:** whoever configures attendance for a customer, and whoever
changes this code next.

Covers `perfecthr_mobile_api` 18.0.1.14.0 and `hrms_dashboard` 18.0.1.0.12.

---

## 1. One definition of "checked in"

**The open row is the answer.** `perfecthr.mobile.checkin.open_session()` finds
the `hr.attendance` with no `check_out`, whenever it started, and everything
else asks that.

This matters because there used to be three answers. `_today_state` derived one
from today's rows, `toggle` read `employee.attendance_state`, and
`hrms_dashboard` kept its own copy in browser state. Across midnight they
disagreed, so the app drew a Check In button for somebody Odoo considered
already checked in, and the press came back as a database constraint error
naming a date from two days earlier.

States reported to the app:

| state | meaning |
|---|---|
| `not_checked_in` | nothing today, nothing open |
| `checked_in` | an open row that started today |
| `on_break` | open row, and a break is running |
| `checked_in_stale` | open row from before yesterday — they forgot |
| `checked_out` | today has rows, none open |
| `on_leave` | approved absence covers today |

A night shift crossing midnight is **not** stale; the cutoff is the start of
yesterday for exactly that reason.

## 2. Timestamps

Everything leaves the API as **ISO-8601 UTC with a `Z`**. It used to leave as
`"2026-09-26 05:53:00"` — naive, no offset — which every JSON parser reads as
*local*. In Dhaka that showed every attendance six hours early, silently, with
plausible-looking times. The app parses through one helper
(`core/utilities/server_time.dart`) that assumes UTC for a naive string,
because the on-device cache is still full of the old format.

**Writing a `DateTime` to the cache uses `serialiseInstant()`**, never
`toIso8601String()`. The latter emits no offset for a local value, which the
parser then reads as UTC — shifting it on every round trip.

## 3. Breaks

`hr.attendance.break` records a break **inside** a session rather than faking
one with a check-out and a check-back-in. Two rows would say "left and came
back" and lose the difference between a tea break and going home early.

**The trap, stated once so nobody re-introduces it:** Odoo's own
`_compute_worked_hours` already subtracts the *scheduled* lunch from the
resource calendar for any non-flexible employee. Recorded breaks therefore
**replace** that deduction rather than adding to it:

```
no breaks recorded  ->  Odoo's computation, scheduled lunch deducted
breaks recorded     ->  gross span minus ACTUAL breaks, no lunch deduction
```

Doing both would charge a one-hour break as two hours, and nothing on any
screen would say so.

Other rules: a running break deducts nothing (otherwise worked hours fall while
you watch, and a forgotten break eats the day); breaks cannot overlap or escape
their session; checking out with a break running is refused, because an
unfinished break cannot be deducted.

## 4. Location

Set per company under **Mobile Sign-in > Location**:

| mode | behaviour |
|---|---|
| `off` (default) | location recorded, never checked |
| `warn` | allowed, flagged `off_site` for review |
| `enforce` | refused, then accepted with a written reason and flagged |

**Nothing is ever refused outright.** A refusal is answered by the app with
"What are you doing today?", and the second attempt carries `off_site_reason`,
is accepted, and lands on the row for HR with the distance.

That is deliberate. Attendance is how people get paid, and location failures
are not evenly distributed — they fall on whoever has the older handset, the
basement office or the metal roof. A hard lockout turns each of those into an
unpaid hour. **The flag is the control, not the refusal**, because a flag is
reviewable and a lockout is not.

Every path that cannot measure returns *allow*: no fix, no coordinates on the
work location, no work location on the employee, or a fix accurate only to
worse than 500m. The phone's own accuracy is subtracted before judging
distance, so uncertainty counts in the employee's favour.

Coordinates come from the work location's own fields, falling back to
`address_id.partner_latitude/longitude` (`base_geolocalize`). **A location with
no coordinates is never checked.**

Find flagged punches under Attendances -> filter **Away From Work Location**.

## 5. Forgotten check-outs

Two mechanisms, and you want both.

**Odoo's `auto_check_out`** closes an open session at the end of the scheduled
working day plus a tolerance (default 2h), stamped `out_mode='auto_check_out'`.
It ships with Odoo 18 and is **off by default**; the migration at
`migrations/18.0.1.14.0/post-migrate.py` turns it on for companies using mobile
attendance, and only where the setting is still on its shipped default.

Leaving it off is not cosmetic: an unclosed row makes the overlap constraint
refuse **every** later check-in for that employee, so one forgotten Friday
blocks the following week.

**`POST /me/attendance/resolve-stale`** is the manual remedy for rows that
predate the cron. It closes at the end of the working day the session belongs
to — **never at `now`**, which would record the intervening days as hours
worked — and posts a note naming who triggered it.

## 6. Cross-client consistency

Both clients now punch through `employee._attendance_action_change()`, the same
method the kiosk, the systray and `hr_attendance_gateway` use. The dashboard
previously wrote `hr.attendance` by hand with `sudo()`, which skipped the
overtime recompute, the state machine, every extension, and the Record Freeze
guard.

Staying in sync:

* **Web** re-reads attendance on tab focus (`visibilitychange` + `focus`), and
  seeds its timer from the real `check_in` rather than counting from zero.
* **App** refetches on foreground (`core/data/foreground_refresh.dart`), with a
  20-second floor so a biometric prompt does not trigger a refresh storm.

Neither polls. A poll runs while nobody is looking; focus is the moment
somebody wants to know.

## 7. Errors are surfaced

`attendance_manual` returns `{ok, state, check_in, worked_seconds, message}`
or `{ok: False, error: "..."}`. It used to swallow every exception and return a
bare `False`, and the dashboard's `if (result !== false)` then skipped both the
success branch *and* the refresh — leaving an optimistic "checked in" on screen
for a check-in the server had refused, with no toast at all.

The app keys on the server's `code` (`off_site`, `stale_session`,
`break_running`), which `AppFailure.code` now carries. The failure mapper used
to discard every code.
