# -*- coding: utf-8 -*-
from __future__ import unicode_literals

app_name = "airtook_video"
app_title = "AirTook Video"
app_publisher = "Etuken Idung"
app_description = "DailyCo video consultation infrastructure for AirTook"
app_email = "info@airtook.com"
app_license = "MIT"

# Rewrite pretty URL to the actual page with query param
website_route_rules = [
    {"from_route": "/video/<session_id>", "to_route": "video"},
]



# Export DB-only customizations into code so they survive DB resets
fixtures = [
    {"dt": "DocType", "filters": [["name", "=", "Video Consultation Session"]]},
    {"dt": "Custom Field", "filters": [["dt", "=", "Patient Appointment"], ["fieldname", "=", "airtook_video_session"]]},
]

