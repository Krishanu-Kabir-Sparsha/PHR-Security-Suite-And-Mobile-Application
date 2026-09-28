# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The location check, and every case where it must get out of the way.

The control's real output is the ``off_site`` flag, not a refusal. Most of
what follows is therefore about the paths that return ``allow`` -- a missing
fix, an unplaced work location, a poor-accuracy reading -- because each of
those, refused, would be an unpaid hour charged to somebody for a
configuration gap or a bad signal.
"""

from odoo.tests import TransactionCase, tagged

from ..models.attendance_geofence import haversine_metres

# Daffodil Smart City, Ashulia -- a real pair of coordinates so the distances
# below are sanity-checkable on a map rather than arbitrary.
CAMPUS_LAT, CAMPUS_LON = 23.8759, 90.3200


@tagged("post_install", "-at_install")
class TestAttendanceGeofence(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Fence = self.env["perfecthr.attendance.geofence"]
        self.company = self.env["res.company"].create(
            {"name": "Fence Co", "attendance_geofence_mode": "enforce"}
        )
        self.partner = self.env["res.partner"].create({"name": "Fence HQ"})
        self.location = self.env["hr.work.location"].create(
            {
                "name": "Fence HQ",
                "company_id": self.company.id,
                "address_id": self.partner.id,
                "geofence_latitude": CAMPUS_LAT,
                "geofence_longitude": CAMPUS_LON,
                "geofence_radius_m": 250,
            }
        )
        self.employee = self.env["hr.employee"].create(
            {
                "name": "Fence Tester",
                "company_id": self.company.id,
                "work_location_id": self.location.id,
            }
        )

    # -- the maths -------------------------------------------------------
    def test_haversine_is_zero_for_the_same_point(self):
        self.assertAlmostEqual(
            haversine_metres(CAMPUS_LAT, CAMPUS_LON, CAMPUS_LAT, CAMPUS_LON),
            0.0,
            places=3,
        )

    def test_haversine_matches_a_known_separation(self):
        """0.01 degrees of latitude is about 1.11 km, anywhere on Earth."""
        metres = haversine_metres(
            CAMPUS_LAT, CAMPUS_LON, CAMPUS_LAT + 0.01, CAMPUS_LON
        )
        self.assertGreater(metres, 1050)
        self.assertLess(metres, 1170)

    # -- in range --------------------------------------------------------
    def test_standing_on_the_spot_is_allowed(self):
        result = self.Fence.evaluate(self.employee, CAMPUS_LAT, CAMPUS_LON)
        self.assertEqual(result["outcome"], "allow")

    def test_just_inside_the_radius_is_allowed(self):
        # ~110m north.
        result = self.Fence.evaluate(
            self.employee, CAMPUS_LAT + 0.001, CAMPUS_LON
        )
        self.assertEqual(result["outcome"], "allow")

    # -- out of range ----------------------------------------------------
    def test_a_long_way_away_is_refused_when_enforcing(self):
        # ~1.1km north, well beyond the 250m radius.
        result = self.Fence.evaluate(
            self.employee, CAMPUS_LAT + 0.01, CAMPUS_LON
        )
        self.assertEqual(result["outcome"], "refuse")
        self.assertGreater(result["distance_m"], 250)
        self.assertEqual(result["location_name"], self.location.display_name)

    def test_warn_mode_flags_rather_than_refusing(self):
        self.company.attendance_geofence_mode = "warn"
        result = self.Fence.evaluate(
            self.employee, CAMPUS_LAT + 0.01, CAMPUS_LON
        )
        self.assertEqual(result["outcome"], "flag")

    # -- every way it must get out of the way ----------------------------
    def test_off_mode_checks_nothing(self):
        """The default. Upgrading must not start refusing anybody."""
        self.company.attendance_geofence_mode = "off"
        result = self.Fence.evaluate(
            self.employee, CAMPUS_LAT + 0.5, CAMPUS_LON
        )
        self.assertEqual(result["outcome"], "allow")

    def test_no_fix_is_allowed(self):
        """Refusing here makes location permission a condition of being paid."""
        self.assertEqual(
            self.Fence.evaluate(self.employee, None, None)["outcome"], "allow"
        )

    def test_a_location_with_no_coordinates_checks_nothing(self):
        """A place nobody has put on a map cannot say who is near it."""
        self.location.geofence_latitude = 0.0
        self.location.geofence_longitude = 0.0
        result = self.Fence.evaluate(
            self.employee, CAMPUS_LAT + 0.5, CAMPUS_LON
        )
        self.assertEqual(result["outcome"], "allow")

    def test_an_employee_with_no_work_location_checks_nothing(self):
        self.employee.work_location_id = False
        result = self.Fence.evaluate(
            self.employee, CAMPUS_LAT + 0.5, CAMPUS_LON
        )
        self.assertEqual(result["outcome"], "allow")

    def test_a_vague_fix_is_not_evidence(self):
        """A reading accurate to kilometres says nothing about where anyone is."""
        result = self.Fence.evaluate(
            self.employee, CAMPUS_LAT + 0.01, CAMPUS_LON, accuracy_m=2000
        )
        self.assertEqual(result["outcome"], "allow")

    def test_accuracy_counts_in_the_employee_s_favour(self):
        """A fix 300m out with 200m of error is consistent with being inside.

        Treating uncertainty as guilt would refuse people standing at their
        own desks on a bad signal day.
        """
        # ~330m north, radius 250m, but the fix is only good to 200m.
        result = self.Fence.evaluate(
            self.employee, CAMPUS_LAT + 0.003, CAMPUS_LON, accuracy_m=200
        )
        self.assertEqual(result["outcome"], "allow")

    # -- the coordinates themselves --------------------------------------
    def test_the_address_is_used_when_the_location_sets_none(self):
        """So a tenant that has already geocoded its addresses needs no typing."""
        if "partner_latitude" not in self.partner._fields:
            self.skipTest("base_geolocalize is not installed")

        self.location.geofence_latitude = 0.0
        self.location.geofence_longitude = 0.0
        self.partner.partner_latitude = CAMPUS_LAT
        self.partner.partner_longitude = CAMPUS_LON

        self.assertTrue(self.location.geofence_ready)
        result = self.Fence.evaluate(self.employee, CAMPUS_LAT, CAMPUS_LON)
        self.assertEqual(result["outcome"], "allow")

    def test_explicit_coordinates_beat_the_address(self):
        """A site whose registered address is a head-office PO box."""
        if "partner_latitude" not in self.partner._fields:
            self.skipTest("base_geolocalize is not installed")

        self.partner.partner_latitude = CAMPUS_LAT + 1.0
        self.partner.partner_longitude = CAMPUS_LON + 1.0
        lat, lon = self.location._geofence_point()
        self.assertAlmostEqual(lat, CAMPUS_LAT, places=4)
        self.assertAlmostEqual(lon, CAMPUS_LON, places=4)
