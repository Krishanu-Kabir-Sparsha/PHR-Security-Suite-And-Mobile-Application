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


class ResCompanyGeofence(models.Model):
    _inherit = "res.company"

    attendance_geofence_mode = fields.Selection(
        selection=[
            ("off", "Off - location is recorded but never checked"),
            ("warn", "Warn - allow, and flag punches made away from work"),
            ("enforce", "Enforce - refuse unless a reason is given"),
        ],
        string="Mobile Location Check",
        default="off",
        required=True,
        help="What to do when a mobile check-in comes from away from the "
        "employee's work location.\n\n"
        "Nothing is ever refused outright: an employee who really is off-site "
        "can send the punch again with a reason, and it is accepted and "
        "flagged for review. Attendance is how people get paid, so a GPS "
        "failure must not become an unpaid hour.\n\n"
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


class AttendanceGeofenceCheck(models.AbstractModel):
    """The check itself, so the endpoint stays about HTTP."""

    _name = "perfecthr.attendance.geofence"
    _description = "Mobile Attendance Location Check"

    @api.model
    def evaluate(self, employee, latitude, longitude, accuracy_m=None):
        """Decide what to do with a punch from this position.

        Returns a dict::

            {'outcome': 'allow' | 'flag' | 'refuse',
             'distance_m': int | None,
             'location_name': str | None,
             'radius_m': int}

        ``allow``   nothing to say -- in range, or nothing to measure against
        ``flag``    out of range, record it and mark the row for review
        ``refuse``  out of range and the company enforces; the caller asks for
                    a reason and tries again

        Every path that cannot measure returns ``allow``. A missing fix, a
        work location with no coordinates, an unplaced employee -- none of
        those are evidence that somebody is in the wrong place, and refusing on
        them would be refusing a configuration gap.
        """
        blank = {
            "outcome": "allow",
            "distance_m": None,
            "location_name": None,
            "radius_m": 0,
        }

        company = employee.company_id or self.env.company
        mode = company.attendance_geofence_mode or "off"
        if mode == "off":
            return blank

        location = employee.work_location_id
        if not location:
            # Nobody has said where this person works, so nothing can be said
            # about whether they are there.
            return blank

        lat, lon = location._geofence_point()
        if lat is None or lon is None:
            _logger.info(
                "Geofence skipped: work location %s has no coordinates",
                location.display_name,
            )
            return blank

        if latitude is None or longitude is None:
            # The phone offered no fix. Refusing here would make location
            # permission a condition of being paid.
            return blank

        if accuracy_m and accuracy_m > MAX_TRUSTED_ACCURACY_M:
            _logger.info(
                "Geofence skipped for %s: fix accurate only to %sm",
                employee.name, int(accuracy_m),
            )
            return blank

        radius = (
            location.geofence_radius_m
            or company.attendance_geofence_radius_m
            or DEFAULT_RADIUS_M
        )
        distance = haversine_metres(latitude, longitude, lat, lon)

        # The phone's own margin of error counts in the employee's favour. A
        # fix 260m out with 80m of accuracy is consistent with standing 180m
        # away, and refusing it treats uncertainty as guilt.
        effective = distance - (accuracy_m or 0)

        result = {
            "distance_m": int(round(distance)),
            "location_name": location.display_name,
            "radius_m": int(radius),
        }
        if effective <= radius:
            return {**result, "outcome": "allow"}
        return {**result, "outcome": "flag" if mode == "warn" else "refuse"}
