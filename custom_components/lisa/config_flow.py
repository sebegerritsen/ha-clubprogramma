"""Config flow: pick the sport and club, then log in as a member."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import (
    Credentials,
    LisaAuthError,
    LisaClient,
    LisaError,
    WebAppConfig,
    fetch_web_app_config,
)
from .const import (
    CONF_API_URL,
    CONF_BASIC,
    CONF_CLUB_ID,
    CONF_CLUB_NAME,
    CONF_CLUB_SHORT,
    CONF_FEDERATION_ID,
    CONF_LOGIN_TYPE,
    CONF_MEMBER_ID,
    CONF_NUMBER,
    CONF_PASSWORD,
    CONF_SPORT,
    CONF_TOKEN,
    DOMAIN,
    LOGIN_CLUB_NUMBER,
    LOGIN_FEDERATION_NUMBER,
    SPORT_HOCKEY,
    SPORT_TENNIS,
    WEB_HOSTS,
)
from .models import Club

CONF_QUERY = "query"
LIST_MODE_MAX = 6


def club_label(club: Club) -> str:
    """Return a club's label, such as `HC Example · Utrecht`."""
    return " · ".join(
        part for part in (club.name, club.city.title() if club.city else None) if part
    )


class LisaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in to LISA as a member."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._sport = SPORT_HOCKEY
        self._config: WebAppConfig | None = None
        self._federation_id: str | None = None
        self._clubs: list[Club] = []
        self._club: Club | None = None

    def _client(self) -> LisaClient:
        assert self._config is not None
        return LisaClient(async_get_clientsession(self.hass), self._config)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the sport and (part of) the club's name or town."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._sport = user_input[CONF_SPORT]
            try:
                if self._config is None or self._federation_id is None:
                    session = async_get_clientsession(self.hass)
                    self._config = await fetch_web_app_config(
                        session, WEB_HOSTS[self._sport], self._sport
                    )
                    self._federation_id = await self._client().find_federation(
                        WEB_HOSTS[self._sport]
                    )
                self._clubs = await self._client().search_clubs(
                    self._federation_id, user_input[CONF_QUERY].strip()
                )
            except LisaError:
                errors["base"] = "cannot_connect"
            else:
                if not self._clubs:
                    errors[CONF_QUERY] = "no_clubs_found"
                elif len(self._clubs) == 1:
                    self._club = self._clubs[0]
                    return await self.async_step_login()
                else:
                    return await self.async_step_club()
        schema = vol.Schema(
            {
                vol.Required(CONF_SPORT, default=self._sport): SelectSelector(
                    SelectSelectorConfig(
                        options=[SPORT_HOCKEY, SPORT_TENNIS],
                        translation_key=CONF_SPORT,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(CONF_QUERY): TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_club(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick the club from the search results."""
        if user_input is not None:
            self._club = next(c for c in self._clubs if c.id == user_input[CONF_CLUB_ID])
            return await self.async_step_login()
        options = [SelectOptionDict(value=c.id, label=club_label(c)) for c in self._clubs]
        return self.async_show_form(
            step_id="club",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLUB_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST
                            if len(options) <= LIST_MODE_MAX
                            else SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_login(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Log in with the member number and password of the club app."""
        assert self._club is not None and self._federation_id is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            credentials = Credentials(
                club_id=self._club.id,
                number=user_input[CONF_NUMBER].strip(),
                password=user_input[CONF_PASSWORD],
                federation_number=user_input[CONF_LOGIN_TYPE] == LOGIN_FEDERATION_NUMBER,
            )
            client = self._client()
            try:
                member_id = await client.login(credentials)
                member = await client.get_member(self._club.id, member_id)
            except LisaAuthError:
                errors["base"] = "invalid_auth"
            except LisaError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{self._club.id}:{member_id}")
                self._abort_if_unique_id_configured()
                assert self._config is not None
                first_name = member.get("first_name") or user_input[CONF_NUMBER]
                return self.async_create_entry(
                    title=f"{first_name} ({self._club.short_name or self._club.name})",
                    data={
                        CONF_SPORT: self._sport,
                        CONF_API_URL: self._config.api_url,
                        CONF_BASIC: self._config.basic,
                        CONF_FEDERATION_ID: self._federation_id,
                        CONF_CLUB_ID: self._club.id,
                        CONF_CLUB_NAME: self._club.name,
                        CONF_CLUB_SHORT: self._club.short_name,
                        CONF_LOGIN_TYPE: user_input[CONF_LOGIN_TYPE],
                        CONF_NUMBER: credentials.number,
                        CONF_PASSWORD: credentials.password,
                        CONF_TOKEN: client.token,
                        CONF_MEMBER_ID: member_id,
                    },
                )
        return self.async_show_form(
            step_id="login",
            data_schema=self.add_suggested_values_to_schema(_login_schema(), user_input),
            errors=errors,
            description_placeholders={"club": self._club.name},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """LISA refused the stored login."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = entry.data
            config = WebAppConfig(api_url=data[CONF_API_URL], basic=data[CONF_BASIC])
            client = LisaClient(async_get_clientsession(self.hass), config)
            credentials = Credentials(
                club_id=data[CONF_CLUB_ID],
                number=data[CONF_NUMBER],
                password=user_input[CONF_PASSWORD],
                federation_number=data.get(CONF_LOGIN_TYPE) == LOGIN_FEDERATION_NUMBER,
            )
            try:
                try:
                    member_id = await client.login(credentials)
                except LisaAuthError:
                    # Perhaps the web app's public user changed rather than the password.
                    config = await fetch_web_app_config(
                        async_get_clientsession(self.hass),
                        WEB_HOSTS[data[CONF_SPORT]],
                        data[CONF_SPORT],
                    )
                    client = LisaClient(async_get_clientsession(self.hass), config)
                    member_id = await client.login(credentials)
            except LisaAuthError:
                errors["base"] = "invalid_auth"
            except LisaError:
                errors["base"] = "cannot_connect"
            else:
                if member_id != data[CONF_MEMBER_ID]:
                    return self.async_abort(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_TOKEN: client.token,
                        CONF_API_URL: config.api_url,
                        CONF_BASIC: config.basic,
                    },
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
            description_placeholders={"number": entry.data[CONF_NUMBER]},
        )


def _login_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_LOGIN_TYPE, default=LOGIN_CLUB_NUMBER): SelectSelector(
                SelectSelectorConfig(
                    options=[LOGIN_CLUB_NUMBER, LOGIN_FEDERATION_NUMBER],
                    translation_key=CONF_LOGIN_TYPE,
                    mode=SelectSelectorMode.LIST,
                )
            ),
            vol.Required(CONF_NUMBER): TextSelector(),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        }
    )
