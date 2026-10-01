# The attendance location rule

Who may check in from where, and what happens when they cannot.

Modules: `perfecthr_mobile_api` **18.0.1.16.0**, `hrms_dashboard` **18.0.1.0.13**,
app **0.3.0+3**.

---

## 1. The rule

Under **ENFORCE**, an employee cannot check themselves in from outside the
radius of any of their work locations. Not from the app, not from the web
dashboard, not from Odoo's own backend widget.

Three modes:

| Mode | Out of range | No position reported |
|---|---|---|
| `off` | nothing is checked | nothing is checked |
| `warn` | allowed, flagged for review | allowed |
| `enforce` | **refused** | **refused** |

**Off by default.** Upgrading changes nobody's behaviour.

### Why "no position" is refused too

If an absent fix were allowed, declining the location permission would be the
way around the rule, and the radius would protect nothing. This is the single
most important consequence to understand before switching ENFORCE on, because
it is also the one that will generate support calls:

> **A desktop browser cannot usually produce a fix good enough to prove
> presence.** Desktop geolocation comes from WiFi and IP and is typically
> accurate to between one and fifty kilometres. Under ENFORCE those are
> refused. In practice people check in from their phone at the door.

That is the deliberate consequence of the rule as specified, not a defect.

### What is NOT refused

A **configuration gap**. An employee with no work location, or whose locations
have no coordinates, is allowed through and the gap is logged at warning level.
Refusing there would punish people for something only HR can fix, and the first
anybody would know of it is a workforce unable to start work.

---

## 2. Where it is enforced

On `hr.attendance.create`, not in a controller.

It used to be in exactly one controller — the mobile toggle. Three other routes
into attendance were untouched:

| Route | Before | Now |
|---|---|---|
| App, Check In button | checked | checked |
| **App, auto check-in on sign-in** | **not checked** | checked |
| **Web dashboard** | **not checked** | checked |
| **Odoo backend widget** | **not checked** | checked |

The second row mattered most: signing in to the app *is* a check-in, so the one
route nobody has to think about was the one with no rule on it.

### Who the gate applies to

Only somebody punching **themselves** — `employee.user_id == env.user`. Everything
else passes through untouched:

- HR correcting an employee's day
- the biometric terminal gateway, which writes as a different user
- the auto check-out cron, which writes `check_out` rather than creating
- an approved off-site request, which *is* the authorisation

**HR managers are exempt even for their own attendance.** They can already create
and edit any attendance row for anybody, so refusing them their own would stop
nothing and would strand the person most likely to be configuring this.

---

## 3. Several work locations

`hr.employee.attendance_location_ids` — sites besides the main one where a
check-in is accepted. A punch passes if it is near **any** of them.

Somebody at head office Monday to Wednesday and at a branch Thursday to Friday
needs the branch listed, or they are refused two days a week for doing exactly
what they were asked to do. And a flag raised on every one of those days buries
the genuine anomaly it exists to surface.

The **nearest** location is the one reported back, compared on how far outside
each radius the punch falls rather than on raw distance — a tight 50 m fence
200 m away is a worse match than a generous 500 m one 300 m away.

---

## 4. The way out: approval, not self-service

A refusal is not the end of the conversation, but nor is it something the
employee can wave themselves past.

```
refused  ->  employee writes where they are and why
         ->  POST /me/attendance/offsite-request   (records NOTHING)
         ->  manager or HR approves
         ->  attendance created at the time of the ATTEMPT
```

**This replaces the earlier design**, in which the app asked for a reason and
resent the same punch, which was then accepted. That made the employee the
authoriser of their own exception: the radius stopped nobody willing to type a
sentence, which is a prompt rather than a control.

Properties worth knowing:

- **The check-in is recorded at the time of the attempt**, never the time of
  approval. An approval at five in the afternoon must not record somebody as
  having started work at five.
- **Nobody decides their own request** — enforced in `_ensure_can_decide`.
- **One pending request at a time.** Tapping Check In four times does not create
  four things for a manager to read.
- Approving over existing attendance is refused with a sentence that says what
  is wrong, rather than Odoo's constraint message about overlapping records.

Decided in Odoo under **Attendances → Off-Site Check-Ins**.

---

## 5. Placing a location by standing in it

`POST /api/mobile/v1/admin/work-locations/<id>/here`, and in the app under
**More → Work locations** (HR managers and system administrators only).

A geofence is only as good as the point at its centre, and that point used to
have to be typed in as two decimal numbers. Nobody knows their office's
latitude. People find it by searching a map, which returns the coordinates of a
rooftop, a street entrance, or whatever the provider decided the address meant —
and a centre thirty metres out silently eats thirty metres of everybody's
allowance.

Standing at the entrance with the handset that will be doing the checking in
removes every translation step: same hardware, same place, same conditions.

**A vague fix is refused.** The capture threshold is 100 m, far tighter than the
500 m used to judge a punch, because a sloppy judgement costs one person one
punch while a sloppy centre costs everybody every punch.

---

## 6. Settings

**Settings → Companies → Mobile Sign-in tab → Location**

| Field | Meaning |
|---|---|
| `attendance_geofence_mode` | off / warn / enforce |
| `attendance_geofence_radius_m` | default for locations that set none |

**Employees → Configuration → Work Locations**

| Field | Meaning |
|---|---|
| `geofence_latitude` / `geofence_longitude` | the centre; falls back to the address partner's coordinates |
| `geofence_radius_m` | per-site radius, default 250 m |
| `geofence_ready` | whether this site has coordinates at all |

**Employee form**, under Work Location: `attendance_location_ids`.

---

## 7. Tests

| File | Covers |
|---|---|
| `tests/test_attendance_geofence.py` | 17 — the maths, accuracy, the mode matrix |
| `tests/test_geofence_enforcement.py` | 27 — the gate, multi-site, the approval path |

Two tests in the first file now assert the **opposite** of what they used to:
`no fix` and `vague fix` were allowed and are now refused under ENFORCE. Both
carry the reasoning inline, because the old assertions were protecting
something real — the principle that a GPS failure must not become an unpaid
hour — and that principle is now served by the approval path instead of by
letting the punch through.

---

## 8. Rollout advice

1. Set every work location from the site itself, on a phone.
2. List second sites on the employees who use them.
3. Run **WARN** for a week. Watch Attendances → *Away From Work Location*.
4. Only then switch to **ENFORCE**.

A radius that is wrong on day one of ENFORCE stops people working, and the
support call reaches you after they have already been standing outside.
