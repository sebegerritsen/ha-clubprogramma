"""Async client for LISA's member API, the way LISA's own web app uses it (see docs/api.md)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http import HTTPStatus
import logging
import re
from typing import Any

import aiohttp

from .models import KIND_MATCH, KIND_TEAM_EVENT, KIND_TRAINING, Club, Tile

_LOGGER = logging.getLogger(__name__)

USER_AGENT = "ha-clubprogramma (+https://github.com/sebegerritsen/ha-clubprogramma)"
TIMEOUT = aiohttp.ClientTimeout(total=30)
# The program comes in pages; follow at most this many.
MAX_PROGRAM_PAGES = 4

_BUNDLE = re.compile(r'src="(/assets/index-[A-Za-z0-9_-]+\.js)"')
_BASIC = re.compile(r'VITE_API_AUTHORIZATION:"(Basic [A-Za-z0-9+/=]+)"')
_API_URLS = {
    "hockey": re.compile(r'VITE_API_HOCKEY_URL:"(https://[^"]+)"'),
    "tennis": re.compile(r'VITE_API_TENNIS_URL:"(https://[^"]+)"'),
}


class LisaError(Exception):
    """Base class for errors talking to LISA."""


class LisaConnectionError(LisaError):
    """LISA could not be reached, timed out or had a server error."""


class LisaAuthError(LisaError):
    """LISA refused the member's login (wrong number or password)."""


class LisaResponseError(LisaError):
    """LISA answered something unexpected."""


@dataclass(frozen=True, slots=True)
class WebAppConfig:
    """What the LISA web app's bundle says: the API address and its public web user."""

    api_url: str
    basic: str


@dataclass(frozen=True, slots=True)
class Credentials:
    """A member's login."""

    club_id: str
    number: str
    password: str
    federation_number: bool = False


async def fetch_web_app_config(
    session: aiohttp.ClientSession, web_host: str, sport: str
) -> WebAppConfig:
    """Read the API address and the public web user from the LISA web app's bundle."""
    try:
        async with session.get(
            f"https://{web_host}/", headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT
        ) as resp:
            page = await resp.text()
        if (match := _BUNDLE.search(page)) is None:
            raise LisaResponseError(f"No app bundle on {web_host}")
        async with session.get(
            f"https://{web_host}{match.group(1)}",
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        ) as resp:
            bundle = await resp.text()
    except (aiohttp.ClientError, TimeoutError) as err:
        raise LisaConnectionError(str(err) or type(err).__name__) from err
    basic = _BASIC.search(bundle)
    api_url = _API_URLS[sport].search(bundle)
    if basic is None or api_url is None:
        raise LisaResponseError(f"The {web_host} bundle no longer has the API settings")
    return WebAppConfig(api_url=api_url.group(1).rstrip("/"), basic=basic.group(1))


class LisaClient:
    """Client for LISA's member API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        config: WebAppConfig,
        *,
        token: str | None = None,
        credentials: Credentials | None = None,
        on_token_change: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the client; with credentials it logs in again when the token expires."""
        self._session = session
        self.config = config
        self.token = token
        self._credentials = credentials
        self._on_token_change = on_token_change
        self._login_lock = asyncio.Lock()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        member: bool = True,
    ) -> tuple[int, Any]:
        headers = {
            "Authorization": self.config.basic,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if member and self.token:
            headers["x-lisa-auth-token"] = self.token
        try:
            async with self._session.request(
                method,
                f"{self.config.api_url}{path}",
                params=params,
                json=json,
                headers=headers,
                timeout=TIMEOUT,
            ) as resp:
                if resp.status >= HTTPStatus.INTERNAL_SERVER_ERROR:
                    raise LisaConnectionError(f"Server error {resp.status} on {path}")
                text = await resp.text()
                if not text:
                    return resp.status, None
                try:
                    return resp.status, await resp.json(content_type=None)
                except ValueError:
                    return resp.status, text
        except (aiohttp.ClientError, TimeoutError) as err:
            raise LisaConnectionError(str(err) or type(err).__name__) from err

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET as the member; logs in again once if the token was refused."""
        used = self.token
        status, data = await self._request("GET", path, params=params)
        refused = (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN)
        if status in refused and self._credentials:
            async with self._login_lock:
                if self.token == used:
                    await self.login(self._credentials)  # LisaAuthError if the login is refused
            status, data = await self._request("GET", path, params=params)
            if status in refused:
                # Logged in fine, still refused: not something this member may see.
                raise LisaResponseError(f"Not allowed: {path}")
        if status in refused:
            raise LisaAuthError(f"Refused: {path}")
        if status >= HTTPStatus.BAD_REQUEST:
            raise LisaResponseError(f"Status {status} on {path}")
        return data

    async def post(self, path: str, body: Any) -> Any:
        """POST as the member; logs in again once if the token was refused."""
        used = self.token
        status, data = await self._request("POST", path, json=body)
        refused = (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN)
        if status in refused and self._credentials:
            async with self._login_lock:
                if self.token == used:
                    await self.login(self._credentials)
            status, data = await self._request("POST", path, json=body)
            if status in refused:
                raise LisaResponseError(f"Not allowed: {path}")
        if status in refused:
            raise LisaAuthError(f"Refused: {path}")
        if status >= HTTPStatus.BAD_REQUEST:
            raise LisaResponseError(f"Status {status} on {path}")
        return data

    async def set_presence(self, club_id: str, tile: Tile, status: str) -> None:
        """Say whether a member comes to a training, match or team event."""
        if not tile.team_id or not tile.member_id:
            raise LisaResponseError("This activity has no team or member")
        member = tile.member_id
        team_member = f"teams/{tile.team_id}/members/{member}"
        if tile.kind == KIND_TRAINING:
            path = f"/clubs/{club_id}/trainings/{tile.id}/{team_member}/presences"
            body: dict[str, Any] = {"status": status}
        elif tile.kind == KIND_MATCH:
            path = f"/clubs/{club_id}/matches/{tile.id}/{team_member}/presence"
            body = {"status": status}
        elif tile.kind == KIND_TEAM_EVENT and tile.team_event_id:
            path = (
                f"/clubs/{club_id}/team_events/{tile.team_event_id}/event_date/{tile.id}"
                f"/presence/{member}"
            )
            body = {"status": status, "comment": None}
        else:
            raise LisaResponseError(f"Attendance cannot be given for a {tile.kind}")
        await self.post(path, body)

    async def find_federation(self, web_host: str) -> str:
        """Return the id of the federation (sport) a LISA web app serves."""
        status, data = await self._request(
            "GET", "/federations", params={"domain": web_host}, member=False
        )
        if status != HTTPStatus.OK or not isinstance(data, dict) or not data.get("id"):
            raise LisaResponseError(f"No federation for {web_host} ({status})")
        return str(data["id"])

    async def search_clubs(self, federation_id: str, query: str) -> list[Club]:
        """Find clubs by (part of) their name or town."""
        status, data = await self._request(
            "GET",
            f"/federations/{federation_id}/clubs",
            params={"name_pattern": query, "city_pattern": query},
            member=False,
        )
        if status != HTTPStatus.OK or not isinstance(data, dict):
            raise LisaResponseError(f"Club search failed ({status})")
        return [club for item in data.get("clubs") or [] if (club := Club.from_api(item))]

    async def login(self, credentials: Credentials) -> str:
        """Log in as a member; returns the member id and keeps the token."""
        number_key = (
            "federation_membership_number"
            if credentials.federation_number
            else "club_membership_number"
        )
        other_key = (
            "club_membership_number"
            if credentials.federation_number
            else "federation_membership_number"
        )
        status, data = await self._request(
            "POST",
            f"/clubs/{credentials.club_id}/auth_tokens",
            json={
                number_key: credentials.number,
                other_key: None,
                "password": credentials.password,
            },
            member=False,
        )
        if status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.BAD_REQUEST):
            raise LisaAuthError("LISA refused the login")
        if status not in (HTTPStatus.OK, HTTPStatus.CREATED) or not isinstance(data, dict):
            raise LisaResponseError(f"Unexpected login answer ({status})")
        token = data.get("token")
        member = data.get("club_member") if isinstance(data.get("club_member"), dict) else {}
        if not isinstance(token, str) or not token or not member.get("id"):
            raise LisaResponseError("No token or member in the login answer")
        self.token = token
        self._credentials = credentials
        if self._on_token_change is not None:
            self._on_token_change(token)
        return str(member["id"])

    async def get_member(self, club_id: str, member_id: str) -> dict[str, Any]:
        """Return a member's own record (names, …)."""
        data = await self.get(f"/clubs/{club_id}/members/{member_id}")
        member = data.get("club_member") if isinstance(data, dict) else None
        if not isinstance(member, dict):
            raise LisaResponseError("No member in the answer")
        return member

    async def get_program(self, federation_id: str, start: date, end: date) -> list[dict[str, Any]]:
        """Return the program tiles (member and family) between two dates, following pages."""
        tiles: list[dict[str, Any]] = []
        seen: set[str] = set()
        page_start = start
        for _ in range(MAX_PROGRAM_PAGES):
            data = await self.get(
                f"/federations/{federation_id}/program",
                {"from_date": page_start.isoformat(), "to_date": end.isoformat()},
            )
            if not isinstance(data, dict) or not isinstance(data.get("tiles"), list):
                raise LisaResponseError("No tiles in the program answer")
            new = 0
            for tile in data["tiles"]:
                if not isinstance(tile, dict):
                    continue
                key = _tile_key(tile)
                if key not in seen:
                    seen.add(key)
                    tiles.append(tile)
                    new += 1
            page_end = _date(data.get("page_end_date"))
            if new == 0 or page_end is None or page_end >= end or page_end < page_start:
                break
            page_start = page_end if page_end > page_start else page_start + timedelta(days=1)
        return tiles


def _tile_key(tile: dict[str, Any]) -> str:
    kind = str(tile.get("type"))
    body = tile.get(kind) if isinstance(tile.get(kind), dict) else {}
    return f"{kind}:{body.get('id')}:{tile.get('club_member_id')}:{tile.get('date')}"


def _date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None
