"""Constants for the LISA integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "clubprogramma"
LOGGER = logging.getLogger(__package__)

# Sports and the LISA web app that serves them. The web app's bundle holds the API
# address and the public web user (HTTP Basic) its visitors use.
SPORT_HOCKEY: Final = "hockey"
SPORT_TENNIS: Final = "tennis"
WEB_HOSTS: Final = {SPORT_HOCKEY: "mijn.lisahockey.nl", SPORT_TENNIS: "leden.knltb.club"}

# Config entry data
CONF_SPORT: Final = "sport"
CONF_API_URL: Final = "api_url"
CONF_BASIC: Final = "basic"
CONF_FEDERATION_ID: Final = "federation_id"
CONF_CLUB_ID: Final = "club_id"
CONF_CLUB_NAME: Final = "club_name"
CONF_CLUB_SHORT: Final = "club_short"
CONF_LOGIN_TYPE: Final = "login_type"
CONF_NUMBER: Final = "number"
CONF_PASSWORD: Final = "password"  # noqa: S105 - a config key
CONF_TOKEN: Final = "token"  # noqa: S105 - a config key
CONF_MEMBER_ID: Final = "member_id"

LOGIN_CLUB_NUMBER: Final = "club"
LOGIN_FEDERATION_NUMBER: Final = "federation"

UPDATE_INTERVAL: Final = timedelta(minutes=15)
# The program is fetched from a day back to this far ahead.
PROGRAM_AHEAD: Final = timedelta(days=35)
PROGRAM_BEHIND: Final = timedelta(days=1)
# Attendance still to give: activities this far ahead.
PRESENCE_AHEAD: Final = timedelta(days=14)
# Matches have no end time in LISA.
MATCH_DURATION: Final = timedelta(minutes=90)
DEFAULT_DURATION: Final = timedelta(minutes=60)

STORAGE_VERSION: Final = 1
