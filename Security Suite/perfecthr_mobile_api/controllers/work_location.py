# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Placing a work location by standing in it.

WHY
---
A geofence is only as good as the point at its centre, and until now that
point had to be typed in as two decimal numbers. Nobody knows their office's
latitude. People find it by searching a map, which gives the coordinates of a
rooftop, a street entrance or whatever the map provider decided the address
means -- and a centre thirty metres out silently eats thirty metres of every
employee's allowance.

Standing at the door with the phone that will be doing the checking in removes
every one of those translation steps. The coordinates come from the same
hardware, in the same place, in the same conditions.

WHO
---
HR managers and system administrators. This writes the rule that decides
whether everybody else can start work, so it is not a self-service action.

WHY A VAGUE FIX IS REFUSED
--------------------------
Capturing a centre from a fix accurate to two kilometres would put the geofence
somewhere nobody chose, and the damage is invisible until a workforce cannot
check in. A fix good enough to be worth saving is a much tighter bar than one
good enough to check against, so the threshold here is deliberately strict.
"""

import logging

from odoo import _, http
from odoo.http import request

from .common import authenticated, fail, ok, _payload

_logger = logging.getLogger(__name__)

# A captured centre must be at least this good. Far tighter than
# MAX_TRUSTED_ACCURACY_M, which governs judging a punch: a sloppy judgement
# costs one person one punch, a sloppy centre costs everybody every punch.
MAX_CAPTURE_ACCURACY_M = 100


class MobileWorkLocation(http.Controller):
    @staticmethod
    def _may_configure():
        user = request.env.user
        for xmlid in ("base.group_system", "hr.group_hr_manager"):
            try:
                if user.has_group(xmlid):
                    return True
            except ValueError:
                continue
        return False

    @http.route(
        "/api/mobile/v1/admin/work-locations",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def work_locations(self, **kwargs):
        """The sites this administrator could place, and whether they are set."""
        if not self._may_configure():
            return fail(
                403,
                "Only an HR manager can set up work locations.",
                code="configure_forbidden",
                log="work location list refused for %s" % request.env.user.login,
            )

        locations = (
            request.env["hr.work.location"]
            .sudo()
            .search([("company_id", "in", request.env.user.company_ids.ids)])
        )
        return ok(
            {
                "locations": [
                    {
                        "id": str(location.id),
                        "name": location.display_name,
                        "placed": bool(location.geofence_ready),
                        "latitude": location.geofence_latitude or None,
                        "longitude": location.geofence_longitude or None,
                        "radius_m": location.geofence_radius_m or 0,
                    }
                    for location in locations
                ],
                "max_accuracy_m": MAX_CAPTURE_ACCURACY_M,
            }
        )

    @http.route(
        "/api/mobile/v1/admin/work-locations/<int:location_id>/here",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def capture_here(self, location_id, **kwargs):
        """Write this handset's current position as the centre of a location."""
        if not self._may_configure():
            return fail(
                403,
                "Only an HR manager can set up work locations.",
                code="configure_forbidden",
                log="work location capture refused for %s"
                % request.env.user.login,
            )

        location = request.env["hr.work.location"].sudo().browse(location_id)
        if not location.exists():
            return fail(404, "That work location no longer exists.",
                        code="location_not_found")

        data = _payload() or kwargs

        def number(key):
            try:
                return float(data.get(key))
            except (TypeError, ValueError):
                return None

        latitude, longitude = number("latitude"), number("longitude")
        accuracy = number("accuracy_m")

        if latitude is None or longitude is None:
            return fail(
                422,
                "Your phone did not report a position. Turn on location and "
                "try again from inside the building's grounds.",
                code="no_fix",
                errors={"requires": "latitude,longitude"},
            )
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            return fail(422, "That position is not a real place.",
                        code="bad_position")

        if accuracy is not None and accuracy > MAX_CAPTURE_ACCURACY_M:
            return fail(
                422,
                _(
                    "Your phone can only place you to within about %(got)s "
                    "metres, and a work location needs %(want)s or better. "
                    "Step outside, wait a few seconds for the signal to "
                    "settle, and try again."
                ) % {"got": int(accuracy), "want": MAX_CAPTURE_ACCURACY_M},
                code="fix_too_vague",
                errors={
                    "accuracy_m": int(accuracy),
                    "max_accuracy_m": MAX_CAPTURE_ACCURACY_M,
                },
            )

        values = {"geofence_latitude": latitude, "geofence_longitude": longitude}
        radius = number("radius_m")
        if radius and radius > 0:
            values["geofence_radius_m"] = int(radius)

        previous = (location.geofence_latitude, location.geofence_longitude)
        location.write(values)

        # Logged with the old value because this silently changes who can start
        # work tomorrow, and "it used to work" needs something to point at.
        _logger.info(
            "Work location %s placed at %s,%s (was %s,%s) by %s, accuracy %sm",
            location.display_name, latitude, longitude,
            previous[0], previous[1], request.env.user.login,
            int(accuracy) if accuracy is not None else "unknown",
        )

        return ok(
            {
                "location": {
                    "id": str(location.id),
                    "name": location.display_name,
                    "placed": True,
                    "latitude": location.geofence_latitude,
                    "longitude": location.geofence_longitude,
                    "radius_m": location.geofence_radius_m,
                },
                "message": _(
                    "%(name)s is now set to where you are standing, with a "
                    "%(radius)s metre radius."
                ) % {
                    "name": location.display_name,
                    "radius": location.geofence_radius_m,
                },
            }
        )
