# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Refusing a mobile punch made a long way from where the person works.

WHAT THIS IS AND IS NOT
-----------------------
It is an **accountability** control, not a prevention one, and the difference
is deliberate rather than a weakness to be fixed later.

A punch outside the radius is refused. But somebody who really is working
off-site -- a site visit, a client meeting, a delivery round, a day when the
GPS simply will not settle indoors -- can send the same punch again with a
written reason, and it is accepted and **flagged** for HR rather than lost.

Making it absolute would be worse, and the reason is not squeamishness:
attendance is how people get paid. A hard lockout turns every GPS failure into
an unpaid hour and a support ticket, and the failures are not evenly
distributed -- they fall on whoever has the older handset, the basement office
or the metal roof. An employee who cannot check in has no recourse inside the
product; one whose off-site punch is flagged has a record and a conversation.

So the control's real output is not refusal, it is the flag: ``off_site`` with
a distance and a reason, on a row HR can filter for. That is reviewable, which
absolute refusal is not.

WHY ONLY THE PHONE
------------------
A browser has no reliable location, and a desktop in the office does not need
one. Geofencing the web dashboard would mean prompting every office worker for
location permission to establish a fact already established by the fact that
they are at their desk. This applies to mobile punches, and nothing else.

WHERE THE COORDINATES COME FROM
-------------------------------
``hr.work.location`` carries none in stock Odoo, so this adds them -- and falls
back to the location's address partner, where ``base_geolocalize`` puts
``partner_latitude`` / ``partner_longitude``. Falling back means a deployment
that has already geocoded its addresses needs no new data entry; setting the
fields explicitly means a deployment that has not is not blocked on it.

**With no coordinates at all, nothing is enforced.** A work location that has
not been placed on a map cannot say whether anybody is near it, and guessing
would refuse real people for a configuration gap.
"""

import logging
import math

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Earth's mean radius in metres. The haversine below is accurate to a few
# metres over the distances that matter here, which is far tighter than a
# consumer GPS fix and far tighter than any sensible radius.
EARTH_RADIUS_M = 6371008.8

# Big enough for a campus, a car park and a GPS fix drifting indoors; small
# enough that "at work" still means something.
DEFAULT_RADIUS_M = 250

# A fix worse than this is not evidence of anything. Refusing on the strength
# of it would punish somebody for their phone's uncertainty, so a low-accuracy
# fix is treated as no fix at all and the punch is allowed.
MAX_TRUSTED_ACCURACY_M = 500


def _distance_label(metres):
    """A distance a person can picture, rather than a bare number.

    Rounded to ten metres below a kilometre: a GPS fix is not accurate enough
    to justify "487 metres", and quoting it that precisely invites an argument
    about seven metres that the hardware cannot settle.

    Defined here rather than in the controller because the refusal message is
    now raised by the model, and two copies of this would eventually round
    differently in the app and in the backend.
    """
    if not metres:
        return _("some distance")
    if metres < 1000:
        return _("%s metres") % int(round(metres / 10.0) * 10)
    return _("%.1f km") % (metres / 1000.0)


def haversine_metres(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres between two decimal-degree points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


class HrWorkLocationGeofence(models.Model):
    _inherit = "hr.work.location"

    geofence_latitude = fields.Float(
        string="Latitude", digits=(10, 7), aggregator=None,
        help="Leave empty to use the coordinates of the work address.",
    )
    geofence_longitude = fields.Float(
        string="Longitude", digits=(10, 7), aggregator=None,
        help="Leave empty to use the coordinates of the work address.",
    )
    geofence_radius_m = fields.Integer(
        string="Allowed Radius (m)",
        default=DEFAULT_RADIUS_M,
        help="How far from this location a mobile check-in is accepted "
        "without a reason. Generous is correct: a GPS fix indoors drifts, and "
        "a tight radius refuses people who are genuinely at their desk.",
    )
    geofence_ready = fields.Boolean(
        string="Location Known",
        compute="_compute_geofence_ready",
        help="Whether this work location has coordinates to measure against. "
        "Nothing is enforced for a location without them.",
    )

    def _compute_geofence_ready(self):
        for location in self:
            lat, lon = location._geofence_point()
            location.geofence_ready = lat is not None and lon is not None

    def _geofence_point(self):
        """(latitude, longitude) for this location, or (None, None).

        Explicit coordinates win over the address partner's, so a site whose
        registered address is a head-office PO box can still be placed where
        people actually work.
        """
        self.ensure_one()
        if self.geofence_latitude and self.geofence_longitude:
            return self.geofence_latitude, self.geofence_longitude

        partner = self.address_id
        # base_geolocalize supplies these. Guarded because it is not a hard
        # dependency of this module and an absent field must read as "no
        # coordinates", not as a traceback on every check-in.
        if partner and "partner_latitude" in partner._fields:
            lat = partner.partner_latitude
            lon = partner.partner_longitude
            if lat and lon:
                return lat, lon
        return None, None


class HrEmployeeGeofence(models.Model):
    _inherit = "hr.employee"

    attendance_location_ids = fields.Many2many(
        "hr.work.location",
        "hr_employee_attendance_location_rel",
        "employee_id",
        "location_id",
        string="Other Places They May Check In",
        help="Sites besides their main work location where a check-in is "
        "accepted. A punch passes if it is within range of ANY of them.\n\n"
        "Somebody at head office Monday to Wednesday and at a branch Thursday "
        "to Friday needs the branch listed here. Without it they are refused "
        "two days a week for doing exactly what they were asked to do.",
    )

    def _geofence_locations(self):
        """Every place this employee may legitimately punch from.

        The main work location comes first, so that when several are in range
        it is the one on their record that gets named back to them -- which is
        the answer a person expects to read.

        Locations with no coordinates are dropped rather than treated as a
        failure: an unplaced site is a configuration gap, and gaps must not
        refuse anybody.
        """
        self.ensure_one()
        locations = self.work_location_id | self.attendance_location_ids
        return locations.filtered(lambda loc: loc.geofence_ready)
class ResCompanyGeofence(models.Model):
    _inherit = "res.company"

    attendance_geofence_mode = fields.Selection(
        selection=[
            ("off", "Off - location is recorded but never checked"),
            ("warn", "Warn - allow, and flag punches made away from work"),
            ("enforce", "Enforce - no check-in unless they are on site"),
        ],
        string="Location Check",
        default="off",
        required=True,
        help="What to do when a check-in comes from away from every one of "
        "the employee's work locations.\n\n"
        "WARN flags the punch and lets it through.\n\n"
        "ENFORCE refuses it, on every route into attendance - the app, the "
        "web dashboard and the backend widget alike. A device reporting no "
        "usable position is refused too, because otherwise declining the "
        "location permission would itself be the way around the rule. "
        "Somebody genuinely off-site asks their manager to approve the punch, "
        "and it is recorded at the time they asked rather than the time it "
        "was approved.\n\n"
        "Enforce is strict by design and WILL stop people working if the "
        "coordinates are wrong. Set each location from the site itself, and "
        "run on WARN for a week before switching it on.\n\n"
        "Off by default, so upgrading changes nobody's behaviour.",
    )
    attendance_geofence_radius_m = fields.Integer(
        string="Default Radius (m)",
        default=DEFAULT_RADIUS_M,
        help="Used for work locations that do not set their own.",
    )


class HrAttendanceGeofence(models.Model):
    _inherit = "hr.attendance"

    off_site = fields.Boolean(
        string="Away From Work Location",
        readonly=True,
        help="This punch was made outside the allowed radius of the "
        "employee's work location, and accepted on the strength of the "
        "reason recorded beside it.",
    )
    off_site_reason = fields.Text(
        string="Reason Given",
        readonly=True,
        help="What the employee said they were doing. Written by them at the "
        "moment of the punch, not reconstructed afterwards.",
    )
    off_site_distance_m = fields.Integer(
        string="Distance From Work (m)",
        readonly=True,
        aggregator=None,
    )

    # ------------------------------------------------------------------
    # The gate
    # ------------------------------------------------------------------
    # Enforcement lives HERE, on the model, and not in the controllers.
    #
    # It used to live in one controller -- the mobile toggle -- which left
    # three other ways into attendance wide open: the auto check-in that
    # happens when somebody signs in to the app, the web dashboard, and Odoo's
    # own backend widget. The rule was real on one route and absent on the
    # rest, which is the same as absent.
    #
    # A model-level gate cannot be forgotten by a route written next year.
    #
    # WHO IT APPLIES TO
    # -----------------
    # Only somebody punching THEMSELVES. The discriminator is
    # ``employee.user_id == self.env.user``, which is true for the app, the web
    # dashboard and the backend widget, and false for every other writer:
    #
    #   HR correcting an employee's day      -> allowed, they always could
    #   the biometric terminal gateway       -> allowed, the person was there
    #   the auto check-out cron              -> writes check_out, not create
    #   an approved off-site request         -> allowed, that IS the decision
    #
    # HR managers are exempt even for their own attendance. They can already
    # create and edit any attendance row for anybody, so refusing them their
    # own would stop nothing and would strand the person most likely to be
    # configuring this in the first place.

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._assert_location_permits_punch(vals)
        return super().create(vals_list)

    def _assert_location_permits_punch(self, vals):
        """Refuse a self-service check-in made away from work.

        Raises ``ValidationError`` with a sentence the employee can act on.
        Returns quietly in every other case.
        """
        context = self.env.context
        # An approved off-site request is the authorisation. It is written by
        # the approver, about a position that was already judged.
        if context.get("perfecthr_offsite_approved"):
            return
        if not vals.get("check_in") and not vals.get("employee_id"):
            return

        employee = self.env["hr.employee"].sudo().browse(vals.get("employee_id"))
        if not employee.exists():
            return

        # Not the employee themselves -- see the note above.
        if not employee.user_id or employee.user_id != self.env.user:
            return
        if self.env.user.has_group("hr.group_hr_manager"):
            return

        company = employee.company_id or self.env.company
        if (company.attendance_geofence_mode or "off") != "enforce":
            return

        position = context.get("perfecthr_punch_location") or {}
        fence = self.env["perfecthr.attendance.geofence"].sudo().evaluate(
            employee,
            position.get("latitude"),
            position.get("longitude"),
            accuracy_m=position.get("accuracy_m"),
        )
        if fence["outcome"] != "refuse":
            return

        _logger.info(
            "Check-in refused for %s: %s (%sm from %s)",
            employee.name, fence["reason"], fence.get("distance_m"),
            fence.get("location_name"),
        )
        raise ValidationError(self._geofence_refusal_message(fence))

    @api.model
    def _geofence_refusal_message(self, fence):
        """What the person reads. Three refusals, three different remedies.

        Collapsing them into one message would tell somebody whose GPS is off
        to walk to the office, and somebody two kilometres away to check their
        phone settings.
        """
        reason = fence.get("reason")
        if reason == "no_fix":
            return _(
                "Perfect HR could not tell where you are, so your check-in was "
                "not recorded. Turn on location for this app and try again. If "
                "you are away from work today, send a request to your manager "
                "instead."
            )
        if reason == "fix_too_vague":
            return _(
                "Your device could only place you to within about %(accuracy)s "
                "metres, which is not precise enough to confirm you are at "
                "work. Step outside or near a window and try again, or send a "
                "request to your manager.",
                accuracy=int(fence.get("accuracy_m") or 0),
            )
        where = fence.get("location_name") or _("your work location")
        return _(
            "You appear to be about %(distance)s from %(where)s, so your "
            "check-in was not recorded. If you are working away from there "
            "today, send a request to your manager and it will be recorded "
            "from the time you asked.",
            distance=_distance_label(fence.get("distance_m")),
            where=where,
        )


class AttendanceGeofenceCheck(models.AbstractModel):
    """The check itself, so the endpoint stays about HTTP."""

    _name = "perfecthr.attendance.geofence"
    _description = "Mobile Attendance Location Check"

    @api.model
    def evaluate(self, employee, latitude, longitude, accuracy_m=None):
        """Decide what to do with a punch from this position.

        Returns a dict::

            {'outcome': 'allow' | 'flag' | 'refuse',
             'reason': None | 'out_of_range' | 'no_fix' | 'fix_too_vague',
             'distance_m': int | None,
             'location_name': str | None,
             'radius_m': int,
             'latitude': float | None,
             'longitude': float | None,
             'accuracy_m': float | None,
             'mode': 'off' | 'warn' | 'enforce'}

        ``allow``   nothing to say -- in range, or nothing to measure against
        ``flag``    out of range; record it and mark the row for review
        ``refuse``  the punch does not happen; the employee may ask their
                    manager to approve it instead

        WHAT IS REFUSED, AND WHAT IS NOT
        --------------------------------
        Under ENFORCE, three things are refused: being out of range, offering
        no position at all, and offering one too vague to mean anything. The
        last two matter as much as the first -- if "no fix" were allowed, then
        declining the location permission would be the way around the rule and
        the radius would protect nothing.

        What is NOT refused is a **configuration gap**. An employee with no
        work location, or whose locations carry no coordinates, is allowed
        through and the gap is logged. Refusing there would punish people for
        something only HR can fix, and the first anybody would know of it is a
        workforce unable to start work.

        The position and accuracy are echoed back so the caller can record
        them on an approval request without parsing the payload a second time.
        """
        mode = (employee.company_id or self.env.company).attendance_geofence_mode or "off"
        strict = mode == "enforce"

        blank = {
            "outcome": "allow",
            "reason": None,
            "distance_m": None,
            "location_name": None,
            "radius_m": 0,
            "latitude": latitude,
            "longitude": longitude,
            "accuracy_m": accuracy_m,
            "mode": mode,
        }
        if mode == "off":
            return blank

        locations = employee._geofence_locations()
        if not locations:
            # A configuration gap, not evidence of anything. Logged at warning
            # level under enforce because somebody has switched on a rule that
            # cannot apply to this person, and they should find out from a log
            # rather than from the employee.
            (_logger.warning if strict else _logger.info)(
                "Geofence has nothing to measure against for %s: no work "
                "location with coordinates. The punch is allowed.",
                employee.name,
            )
            return blank

        if latitude is None or longitude is None:
            if not strict:
                return blank
            return {
                **blank,
                "outcome": "refuse",
                "reason": "no_fix",
                "location_name": locations[0].display_name,
            }

        if accuracy_m and accuracy_m > MAX_TRUSTED_ACCURACY_M:
            if not strict:
                return blank
            return {
                **blank,
                "outcome": "refuse",
                "reason": "fix_too_vague",
                "location_name": locations[0].display_name,
                "accuracy_m": accuracy_m,
            }

        # The nearest of every place this person may legitimately be. Nearest
        # rather than first, so the one reported back is the site they are
        # actually standing at -- telling somebody at the branch how far they
        # are from head office answers a question nobody asked.
        best = None
        for location in locations:
            lat, lon = location._geofence_point()
            distance = haversine_metres(latitude, longitude, lat, lon)
            radius = (
                location.geofence_radius_m
                or employee.company_id.attendance_geofence_radius_m
                or DEFAULT_RADIUS_M
            )
            # Compared on how far OUTSIDE each radius the punch falls, not on
            # raw distance: a tight 50m fence 200m away is a worse match than a
            # generous 500m one 300m away, even though the second is further.
            overshoot = distance - radius
            if best is None or overshoot < best[0]:
                best = (overshoot, distance, radius, location)

        overshoot, distance, radius, location = best

        result = {
            **blank,
            "distance_m": int(round(distance)),
            "location_name": location.display_name,
            "radius_m": int(radius),
        }

        # The phone's own margin of error counts in the employee's favour. A
        # fix 260m out with 80m of accuracy is consistent with standing 180m
        # away, and refusing it treats uncertainty as guilt.
        if (distance - (accuracy_m or 0)) <= radius:
            return result

        if strict:
            return {**result, "outcome": "refuse", "reason": "out_of_range"}
        return {**result, "outcome": "flag", "reason": "out_of_range"}
