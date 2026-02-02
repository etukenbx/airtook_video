# -*- coding: utf-8 -*-
from __future__ import unicode_literals

app_name = "airtook_video"
app_title = "AirTook Video"
app_publisher = "Etuken Idung"
app_description = "DailyCo video consultation infrastructure for AirTook"
app_email = "NoSex@airtook.com"
app_license = "MIT"

# Rewrite pretty URL to the actual page with query param
website_route_rules = [
    {"from_route": "/video/<session_id>", "to_route": "video?session_id=<session_id>"},
]
