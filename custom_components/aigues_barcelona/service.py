"""Services for Aigues de Barcelona."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType

from .const import CONF_CONTRACT, CONF_HISTORY_DAYS, DOMAIN, HISTORY_DAYS_DEFAULT

_LOGGER = logging.getLogger(__name__)

SERVICE_IMPORT_HISTORICAL_DATA = "import_historical_data"
SERVICE_RESET_AND_REFRESH_DATA = "reset_and_refresh_data"

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CONTRACT): str,
        vol.Optional(CONF_HISTORY_DAYS, default=365): vol.All(
            int, vol.Range(min=1, max=HISTORY_DAYS_DEFAULT)
        ),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up integration services."""

    async def handle_import_historical_data(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data.get(CONF_CONTRACT))
        if coordinator is None:
            return

        days = call.data.get(CONF_HISTORY_DAYS, 365)
        _LOGGER.warning(
            "Importing %s days of historical data for %s by service call",
            days,
            coordinator.contract,
        )
        await fetch_historic_data(hass, coordinator, days=days)

    async def handle_reset_and_refresh_data(call: ServiceCall) -> None:
        """Backward-compatible service name.

        This service does not clear statistics because clear_statistics is unsafe from
        this context in current Home Assistant versions. It only imports history.
        """
        coordinator = _get_coordinator(hass, call.data.get(CONF_CONTRACT))
        if coordinator is None:
            return

        days = call.data.get(CONF_HISTORY_DAYS, 365)
        _LOGGER.warning(
            "Legacy reset_and_refresh_data service called for %s. "
            "Statistics reset is not performed; importing %s historical days only.",
            coordinator.contract,
            days,
        )
        await fetch_historic_data(hass, coordinator, days=days)

    if not hass.services.has_service(DOMAIN, SERVICE_IMPORT_HISTORICAL_DATA):
        hass.services.async_register(
            DOMAIN,
            SERVICE_IMPORT_HISTORICAL_DATA,
            handle_import_historical_data,
            schema=SERVICE_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RESET_AND_REFRESH_DATA):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RESET_AND_REFRESH_DATA,
            handle_reset_and_refresh_data,
            schema=SERVICE_SCHEMA,
        )

    return True


def _get_coordinator(hass: HomeAssistant, contract: str | None):
    contracts = {
        key: value
        for key, value in hass.data.get(DOMAIN, {}).items()
        if isinstance(value, dict) and value.get("coordinator") is not None
    }

    if not contracts:
        _LOGGER.error("No contracts available")
        return None

    if contract:
        selected = contracts.get(contract.upper())
        if selected is None:
            _LOGGER.error("Contract coordinator for %s not found", contract)
            return None
    elif len(contracts) == 1:
        selected = next(iter(contracts.values()))
    else:
        _LOGGER.error(
            "Multiple contracts available. Provide a contract. Available: %s",
            ", ".join(sorted(contracts)),
        )
        return None

    coordinator = selected.get("coordinator")
    if coordinator is None:
        _LOGGER.error("Contract coordinator not found")
        return None

    return coordinator


async def clear_stored_data(hass: HomeAssistant, coordinator) -> None:
    """Clear stored statistics."""
    await coordinator._clear_statistics()


async def fetch_historic_data(
    hass: HomeAssistant, coordinator, days: int = 365
) -> None:
    """Fetch historical consumption data."""
    await coordinator.import_old_consumptions(days=days)
