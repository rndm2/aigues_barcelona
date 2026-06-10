"""Config flow for integration."""

from __future__ import annotations

import logging
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .api import AiguesApiClient
from .const import (
    API_ERROR_TOKEN_REVOKED,
    CONF_2CAPTCHA_APIKEY,
    CONF_CONTRACT,
    CONF_HISTORY_DAYS,
    CONF_SCAN_PERIOD,
    CONF_SHOULD_IMPORT_HISTORY,
    DEFAULT_SCAN_PERIOD,
    DOMAIN,
    HISTORY_DAYS_DEFAULT,
    MAX_SCAN_PERIOD,
    MIN_SCAN_PERIOD,
)

_LOGGER = logging.getLogger(__name__)

ACCOUNT_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_2CAPTCHA_APIKEY): cv.string,
    }
)


def check_valid_nif(username: str) -> bool:
    """Quick check for NIF/DNI/NIE and return if valid."""
    if len(username) != 9:
        return False

    # DNI 12341234D
    if username[0:8].isnumeric() and not username[-1].isnumeric():
        return True

    # NIF X2341234H
    if (
        username[0].upper() in ["X", "Y", "Z"]
        and username[1:8].isnumeric()
        and not username[-1].isnumeric()
    ):
        return True

    return False


async def validate_credentials(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any] | bool:
    """Validate credentials and return available contracts plus token."""
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]
    twocaptcha_api_key = data[CONF_2CAPTCHA_APIKEY]

    if not check_valid_nif(username):
        raise InvalidUsername

    api: AiguesApiClient | None = None
    try:
        api = AiguesApiClient(username, password, twocaptcha_api_key)
        _LOGGER.info("Attempting to login")
        login = await hass.async_add_executor_job(api.login)
        if not login:
            raise InvalidAuth
        _LOGGER.info("Login succeeded")
        contracts = await hass.async_add_executor_job(api.contracts, username)
        token = api.get_token()

        available_contracts = [x["contractDetail"]["contractNumber"] for x in contracts]
        return {CONF_CONTRACT: available_contracts, CONF_TOKEN: token}

    except (InvalidAuth, InvalidUsername):
        raise
    except Exception:
        last_response = api.last_response if api is not None else None
        if last_response:
            if isinstance(last_response, dict):
                _LOGGER.debug(
                    "Credential validation failed; last response keys: %s",
                    sorted(last_response.keys()),
                )
            else:
                _LOGGER.debug(
                    "Credential validation failed; last response type: %s",
                    type(last_response).__name__,
                )

        if not last_response:
            return False

        if (
            isinstance(last_response, dict)
            and last_response.get("path") == "recaptchaClientResponse"
        ):
            raise RecaptchaAppeared

        if isinstance(last_response, str) and last_response == API_ERROR_TOKEN_REVOKED:
            raise TokenExpired

        return False


class AiguesBarcelonaOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current_should_import = self.config_entry.options.get(
            CONF_SHOULD_IMPORT_HISTORY,
            self.config_entry.data.get(CONF_SHOULD_IMPORT_HISTORY, False),
        )

        current_history_days = self.config_entry.options.get(
            CONF_HISTORY_DAYS,
            self.config_entry.data.get(CONF_HISTORY_DAYS, HISTORY_DAYS_DEFAULT),
        )

        current_scan_period = self.config_entry.options.get(
            CONF_SCAN_PERIOD,
            self.config_entry.data.get(CONF_SCAN_PERIOD, DEFAULT_SCAN_PERIOD),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SHOULD_IMPORT_HISTORY,
                        default=current_should_import,
                    ): bool,
                    vol.Required(CONF_HISTORY_DAYS, default=current_history_days): vol.All(
                        int, vol.Range(min=1, max=365 * 5)
                    ),
                    vol.Required(CONF_SCAN_PERIOD, default=current_scan_period): vol.All(
                        int, vol.Range(min=MIN_SCAN_PERIOD, max=MAX_SCAN_PERIOD)
                    ),
                }
            ),
        )


class AiguesBarcelonaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow."""

    VERSION = 2

    def __init__(self) -> None:
        self.stored_input: dict[str, Any] = {}
        self.entry: config_entries.ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AiguesBarcelonaOptionsFlow:
        return AiguesBarcelonaOptionsFlow()

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Return to user step with stored input and provided token."""
        return await self.async_step_user({**self.stored_input, **(user_input or {})})

    async def async_step_reauth(self, entry) -> FlowResult:
        """Request OAuth Token again when expired."""
        self.entry = entry
        if hasattr(entry, "data"):
            self.stored_input = dict(entry.data)
        else:
            self.stored_input = dict(entry)

            # WHAT: for DataUpdateCoordinator, entry is not valid,
            # as it contains only sensor data. Missing entry_id.
            if entry := self.hass.config_entries.async_get_entry(
                self.context["entry_id"]
            ):
                self.entry = entry
        return await self.async_step_reauth_confirm(None)

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors = {}
        _LOGGER.debug(
            "Reauth confirmation submitted for entry %s",
            self.entry.entry_id if self.entry else None,
        )
        user_input = {**self.stored_input, **(user_input or {})}
        try:
            info = await validate_credentials(self.hass, user_input)
            _LOGGER.debug("Credential validation succeeded during reauth")
            if not info:
                raise InvalidAuth

            contracts = info[CONF_CONTRACT]
            if contracts != self.stored_input.get(CONF_CONTRACT):
                _LOGGER.error("Reauth failed, contract does not match stored one")
                raise InvalidAuth

            self.hass.config_entries.async_update_entry(
                self.entry, data={**user_input, **info}
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.entry.entry_id)
            )

            return self.async_abort(reason="reauth_successful")

        except InvalidUsername:
            errors["base"] = "invalid_auth"
        except InvalidAuth:
            errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=ACCOUNT_CONFIG_SCHEMA,
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle configuration step from UI."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=ACCOUNT_CONFIG_SCHEMA
            )

        errors = {}

        try:
            self.stored_input = dict(user_input)
            info = await validate_credentials(self.hass, user_input)
            _LOGGER.debug("Credential validation succeeded during reauth")
            if not info:
                raise InvalidAuth
            contracts = info[CONF_CONTRACT]

            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()
        except NotImplementedError:
            errors["base"] = "not_implemented"
        except TokenExpired:
            errors["base"] = "token_expired"
        except RecaptchaAppeared:
            errors["base"] = "token_requested"
        except InvalidUsername:
            errors["base"] = "invalid_auth"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except AlreadyConfigured:
            errors["base"] = "already_configured"
        else:
            _LOGGER.debug("Creating entity for contracts: %s", contracts)
            nif_oculto = user_input[CONF_USERNAME][-3:][0:2]

            return self.async_create_entry(
                title=f"Aigua ****{nif_oculto}", data={**user_input, **info}
            )

        return self.async_show_form(
            step_id="user", data_schema=ACCOUNT_CONFIG_SCHEMA, errors=errors
        )


class AlreadyConfigured(HomeAssistantError):
    """Error to indicate integration is already configured."""


class RecaptchaAppeared(HomeAssistantError):
    """Error to indicate a Recaptcha appeared and requires an OAuth token issued."""


class TokenExpired(HomeAssistantError):
    """Error to indicate the OAuth token has expired."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate credentials are invalid."""


class InvalidUsername(HomeAssistantError):
    """Error to indicate username is invalid."""
