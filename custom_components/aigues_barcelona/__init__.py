"""Integration for Aigues de Barcelona."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .api import AiguesApiClient
from .const import CONF_2CAPTCHA_APIKEY, DOMAIN
from .service import async_setup as setup_service

PLATFORMS = [Platform.SENSOR]


async def async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Aigues de Barcelona from a config entry."""
    api = AiguesApiClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data.get(CONF_2CAPTCHA_APIKEY, ""),
    )

    if token := entry.data.get(CONF_TOKEN):
        api.set_token(token)

    if api.is_token_expired():
        try:
            hass.config_entries.async_update_entry(
                entry,
                data={k: v for k, v in entry.data.items() if k != CONF_TOKEN},
            )

            await hass.async_add_executor_job(api.login)
            new_token = api.get_token()

            if new_token:
                hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_TOKEN: new_token},
                )
        except Exception as err:
            raise ConfigEntryNotReady from err

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await setup_service(hass, entry)
    entry.async_on_unload(entry.add_update_listener(async_options_updated))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    domain_data = hass.data.get(DOMAIN)
    if not domain_data:
        return True

    contracts_to_remove = [
        key
        for key, value in domain_data.items()
        if isinstance(value, dict)
        and getattr(value.get("coordinator"), "entry_id", None) == entry.entry_id
    ]

    for key in contracts_to_remove:
        domain_data.pop(key, None)

    if not domain_data:
        hass.data.pop(DOMAIN, None)

    return True
