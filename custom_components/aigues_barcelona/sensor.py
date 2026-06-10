"""Platform for sensor integration."""
import asyncio
import logging
from datetime import datetime
from datetime import timedelta

import homeassistant.components.recorder.util as recorder_util

try:
    from homeassistant.components.recorder.const import (
        DATA_INSTANCE as RECORDER_DATA_INSTANCE,
    )
except ImportError:  # NEW Home Assistant 2024.08
    from homeassistant.helpers.recorder import (
        DATA_INSTANCE as RECORDER_DATA_INSTANCE,
    )
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.components.recorder.statistics import clear_statistics
from homeassistant.components.recorder.statistics import list_statistic_ids
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_STATE
from homeassistant.const import CONF_TOKEN
from homeassistant.const import CONF_USERNAME
from homeassistant.const import EVENT_HOMEASSISTANT_START
from homeassistant.const import UnitOfVolume
from homeassistant.core import callback
from homeassistant.core import CoreState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.update_coordinator import TimestampDataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.components.recorder.db_schema import Statistics, StatisticsMeta
from homeassistant.components.recorder.util import session_scope

from .api import AiguesApiAuthError
from .api import AiguesApiClient
from .const import API_ERROR_TOKEN_REVOKED
from .const import ATTR_LAST_MEASURE
from .const import CONF_CONTRACT
from .const import CONF_VALUE
from .const import DEFAULT_SCAN_PERIOD
from .const import CONF_SCAN_PERIOD
from .const import DOMAIN
from .const import CONF_2CAPTCHA_APIKEY
from .const import CONF_HISTORY_DAYS
from .const import CONF_SHOULD_IMPORT_HISTORY
from .const import HISTORY_DAYS_DEFAULT

from typing import Optional

_LOGGER = logging.getLogger(__name__)


def get_db_instance(hass):
    """Workaround for older HA versions."""
    try:
        return recorder_util.get_instance(hass)
    except AttributeError:
        return hass


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up entry."""
    hass.data.setdefault(DOMAIN, {})

    _LOGGER.info("calling async_setup_entry")

    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]
    twocaptcha_api_key = config_entry.data.get(CONF_2CAPTCHA_APIKEY, "")
    contracts = config_entry.data[CONF_CONTRACT]
    token = config_entry.data.get(CONF_TOKEN)

    history_days = config_entry.options.get(CONF_HISTORY_DAYS, HISTORY_DAYS_DEFAULT)
    history_should_import = config_entry.options.get(CONF_SHOULD_IMPORT_HISTORY, True)
    scan_period = config_entry.options.get(
        CONF_SCAN_PERIOD,
        config_entry.data.get(CONF_SCAN_PERIOD, DEFAULT_SCAN_PERIOD),
    )

    _LOGGER.debug(
        "History will import: %s, with days: %s; scan period: %s seconds",
        history_should_import,
        history_days,
        scan_period,
    )

    contadores = list()

    for contract in contracts:
        coordinator = ContratoAgua(
            hass,
            username,
            password,
            twocaptcha_api_key,
            contract,
            token=token,
            entry_id=config_entry.entry_id,
            history_days=history_days,
            should_import_history=history_should_import,
            scan_period=scan_period,
        )
        contadores.append(ContadorAgua(coordinator))

    # postpone first refresh to speed up startup
    @callback
    async def async_first_refresh(*args):
        for sensor in contadores:
            await sensor.coordinator.async_refresh()

    if hass.state == CoreState.running:
        await async_first_refresh()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, async_first_refresh)

    _LOGGER.info("about to add entities")
    async_add_entities(contadores)

    return True


class ContratoAgua(TimestampDataUpdateCoordinator):
    def __init__(
            self,
            hass: HomeAssistant,
            username: str,
            password: str,
            twocaptcha_api_key: str,
            contract: str,
            token: str,
            entry_id: str,
            history_days: int,
            should_import_history: bool,
            scan_period: int = DEFAULT_SCAN_PERIOD,
            prev_data=None,
    ) -> None:
        """Initialize the data handler."""
        self.reset = prev_data is None

        self._import_in_progress = False

        self.contract = contract.upper()
        self.id = contract.lower()
        self.internal_sensor_id = f"sensor.contador_{self.id}"
        self.entry_id = entry_id

        self._history_days = history_days
        self._should_import_history = should_import_history
        self.scan_period = scan_period

        if not hass.data[DOMAIN].get(self.contract):
            # init data shared store
            hass.data[DOMAIN][self.contract] = {}

        # create alias
        self._data = hass.data[DOMAIN][self.contract]

        # WARN define a pointer to this object
        hass.data[DOMAIN][self.contract]["coordinator"] = self

        # the api object
        self._api = AiguesApiClient(username, password, twocaptcha_api_key, contract)

        if token:
            self._api.set_token(token)

        super().__init__(
            hass,
            _LOGGER,
            name=self.id,
            update_interval=timedelta(seconds=self.scan_period),
        )

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.contract}>"

    async def _ensure_token(self) -> None:
        """Ensure API token is valid; refresh and persist it if expired."""
        if not self._api.is_token_expired():
            return

        entry = self.hass.config_entries.async_get_entry(self.entry_id)

        if entry is None:
            raise ConfigEntryAuthFailed("Config entry not found for token refresh")

        # Drop old token to force login.
        self.hass.config_entries.async_update_entry(
            entry, data={k: v for k, v in entry.data.items() if k != CONF_TOKEN}
        )

        await self.hass.async_add_executor_job(self._api.login)
        new_token = self._api.get_token()

        if new_token:
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_TOKEN: new_token}
            )

    async def _async_update_data(self):
        _LOGGER.info(f"Updating coordinator data for {self.contract}")
        TODAY = datetime.now()
        LAST_WEEK = TODAY - timedelta(days=7)

        # last_measurement = await self.get_last_measurement_stored()
        # _LOGGER.info("Last stored measurement: %s", last_measurement)

        try:
            previous = datetime.fromisoformat(self._data.get(CONF_STATE, ""))
            previous = previous.replace(tzinfo=None)
        except (TypeError, ValueError):
            previous = None

        if previous and (TODAY - previous) <= timedelta(minutes=10):
            _LOGGER.debug("Skipping request update data - last measure is too recent")
            return self._data

        consumptions = None
        try:
            await self._ensure_token()

            consumptions = await self.hass.async_add_executor_job(
                self._api.consumptions, LAST_WEEK, TODAY + timedelta(days=1), self.contract
            )
        except ConfigEntryAuthFailed:
            _LOGGER.error("Token has expired, cannot check consumptions.")
            raise
        except AiguesApiAuthError as exp:
            raise ConfigEntryAuthFailed from exp
        except Exception as exp:
            self.async_set_update_error(exp)
            if API_ERROR_TOKEN_REVOKED in str(exp):
                raise ConfigEntryAuthFailed from exp

        if not consumptions:
            _LOGGER.error("No consumptions available")
            return self._data

        self._data["consumptions"] = consumptions

        # get last entry - most updated
        metric = consumptions[-1]
        self._data[CONF_VALUE] = metric["accumulatedConsumption"]
        self._data[CONF_STATE] = metric["datetime"]

        # await self._clear_statistics()
        try:
            await self._async_import_statistics(consumptions, frequency="HOURLY")
        except Exception:
            _LOGGER.exception("Failed to import statistics")

        if self._history_days > 0 and self._should_import_history:
            self._should_import_history = False

            _LOGGER.warning(
                "Importing %s days of historical data for %s",
                self._history_days,
                self.contract,
            )

            try:
                await self.import_old_consumptions(days=self._history_days)
            except Exception:
                _LOGGER.exception("Failed to import historical data for %s", self.contract)

            entry = self.hass.config_entries.async_get_entry(self.entry_id)
            if entry is not None:
                new_options = {
                    **entry.options,
                    CONF_SHOULD_IMPORT_HISTORY: False,
                    CONF_HISTORY_DAYS: self._history_days,
                }

                self.hass.config_entries.async_update_entry(entry, options=new_options)

        return self._data

    async def _clear_statistics(self) -> None:
        all_ids = await get_db_instance(self.hass).async_add_executor_job(
            list_statistic_ids, self.hass
        )
        to_clear = [
            x["statistic_id"]
            for x in all_ids
            if x["statistic_id"].startswith(self.internal_sensor_id)
        ]

        if to_clear:
            _LOGGER.warning(
                f"About to delete {len(to_clear)} entries from {self.contract}"
            )
            # NOTE: This does not seem to work?
            await get_db_instance(self.hass).async_add_executor_job(
                clear_statistics, self.hass.data[RECORDER_DATA_INSTANCE], to_clear
            )

    async def get_last_measurement_stored(self) -> Optional[datetime]:
        """Placeholder — not used. Implement DB query later if needed."""
        return None

        # last_stored = None
        #
        # all_ids = await get_db_instance(self.hass).async_add_executor_job(
        #     list_statistic_ids, self.hass
        # )
        #
        # for stat_id in all_ids:
        #     if stat_id["statistic_id"] == self.internal_sensor_id:
        #         if stat_id.get("sum") and stat_id["sum"] > last_stored["sum"]:
        #             last_stored = stat_id
        #
        # if last_stored:
        #     _LOGGER.debug(f"Found last stored value: {last_stored}")
        #     return datetime.fromtimestamp(last_stored.get("start_ts"))
        #
        # return None

    async def _async_import_statistics(self, consumptions, frequency=None) -> None:
        if self._import_in_progress:
            _LOGGER.debug("Import already in progress — skipping")
            return

        self._import_in_progress = True
        try:
            if frequency == "HOURLY":
                consumptions = sorted(
                    consumptions,
                    key=lambda x: (
                        dt_util.as_utc(dt_util.parse_datetime(x["datetime"]))
                        if dt_util.parse_datetime(x["datetime"]) is not None
                        else datetime.min
                    ),
                )

                normalized = {}
                for metric in consumptions:
                    dt = dt_util.parse_datetime(metric["datetime"])
                    if dt is None:
                        continue
                    start_ts = dt_util.as_utc(dt).replace(minute=0, second=0, microsecond=0)
                    val = round(metric["accumulatedConsumption"], 4)
                    current = normalized.get(start_ts)
                    if current is None or val > current:
                        normalized[start_ts] = val

                items = sorted(normalized.items())

            else:
                def _key(m):
                    dt = dt_util.parse_datetime(m["datetime"])
                    if dt is None:
                        return datetime.min.replace(tzinfo=dt_util.UTC)

                    local_dt = dt.replace(tzinfo=None).replace(
                        tzinfo=dt_util.DEFAULT_TIME_ZONE
                    )
                    return dt_util.as_utc(local_dt)

                consumptions = sorted(consumptions, key=_key)

                normalized = {}
                for metric in consumptions:
                    dt = dt_util.parse_datetime(metric["datetime"])
                    if dt is None:
                        continue

                    label_local = (
                        dt.replace(tzinfo=None).replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                        - timedelta(seconds=1)
                    )
                    start_local = dt_util.start_of_local_day(label_local)
                    start_ts = dt_util.as_utc(start_local)

                    val = round(metric["accumulatedConsumption"], 4)
                    current = normalized.get(start_ts)
                    if current is None or val > current:
                        normalized[start_ts] = val

                items = sorted(normalized.items())

                if not items:
                    return

                min_start = items[0][0]
                max_start = items[-1][0] + timedelta(days=1)

                existing = await self._async_db_get_start_ts_in_range(min_start, max_start)

                existing_days = set()
                for ts in existing:
                    dt_utc = dt_util.utc_from_timestamp(ts)
                    existing_days.add(dt_util.as_local(dt_utc).date())

                filtered_items = []
                for start_ts, state in items:
                    day = dt_util.as_local(start_ts).date()
                    if day in existing_days:
                        continue
                    filtered_items.append((start_ts, state))

                items = filtered_items

            stats = []

            for start_ts, state in items:
                stats.append(
                    {
                        "start": start_ts,
                        "state": state,
                        "sum": state,
                    }
                )

            if stats:
                metadata = {
                    "mean_type": 0,
                    "unit_class": None,
                    "has_sum": True,
                    "name": f"Contador {self.id}",
                    "source": "recorder",
                    "statistic_id": self.internal_sensor_id,
                    "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
                }
                _LOGGER.debug(f"Adding metric: {metadata} {stats}")
                async_import_statistics(self.hass, metadata, stats)

                _LOGGER.info("Imported %d points for %s", len(stats), self.contract)
        finally:
            self._import_in_progress = False

    async def _async_db_get_start_ts_in_range(
        self, start: datetime, end: datetime
    ) -> list[float]:
        def _query():
            with session_scope(hass=self.hass) as session:
                meta_id = (
                    session.query(StatisticsMeta.id)
                    .filter(StatisticsMeta.statistic_id == self.internal_sensor_id)
                    .scalar()
                )
                if meta_id is None:
                    return []

                start_ts = dt_util.as_timestamp(dt_util.as_utc(start))
                end_ts = dt_util.as_timestamp(dt_util.as_utc(end))

                rows = (
                    session.query(Statistics.start_ts)
                    .filter(
                        Statistics.metadata_id == meta_id,
                        Statistics.start_ts >= start_ts,
                        Statistics.start_ts < end_ts,
                    )
                    .all()
                )
                return [r[0] for r in rows]

        return await get_db_instance(self.hass).async_add_executor_job(_query)

    async def clear_all_stored_data(self) -> None:
        await self._clear_statistics()

    async def import_old_consumptions(self, days: int = 365) -> None:
        await self._ensure_token()

        today = datetime.now()
        start_date = today - timedelta(days=days)

        current_date = start_date
        while current_date < today:
            _LOGGER.warning(
                "Importing historical weekly data for %s starting %s",
                self.contract,
                current_date,
            )

            consumptions = None
            last_exc = None

            for attempt in range(1, 6):  # 5 retries
                try:
                    consumptions = await self.hass.async_add_executor_job(
                        self._api.consumptions_week,
                        current_date,
                        self.contract,
                    )
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    _LOGGER.warning(
                        "Fetch failed for %s at %s (attempt %d/5): %s",
                        self.contract,
                        current_date,
                        attempt,
                        exc,
                    )
                    # simple backoff (1s, 2s, 4s, 8s, 16s)
                    await asyncio.sleep(2 ** (attempt - 1))

            if last_exc is not None and consumptions is None:
                _LOGGER.warning(
                    "Failed to fetch historical weekly consumptions for %s at %s after 5 attempts: %s",
                    self.contract,
                    current_date,
                    last_exc,
                )
                current_date += timedelta(weeks=1)
                continue

            if consumptions:
                await self._async_import_statistics(consumptions, frequency="DAILY")
            else:
                _LOGGER.warning(
                    "No historical weekly data for %s at %s",
                    self.contract,
                    current_date,
                )

            current_date += timedelta(weeks=1)

class ContadorAgua(CoordinatorEntity, SensorEntity):
    """Representation of a sensor."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = f"Contador {coordinator.id}"
        self._attr_unique_id = f"{DOMAIN}_{coordinator.id}"
        self._attr_suggested_object_id = f"contador_{coordinator.id}"
        self._attr_icon = "mdi:water-pump"
        # Keep the entity id short: sensor.contador_<contract>.
        # With has_entity_name=True, Home Assistant prefixes the device name and
        # produces names like sensor.aigues_de_barcelona_<id>_contador_<id>.
        self._attr_has_entity_name = False
        self._attr_should_poll = False
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.contract)},
            "name": f"Aigües de Barcelona {coordinator.contract}",
            "manufacturer": "Aigües de Barcelona",
        }

    @property
    def native_value(self):
        return self.coordinator._data.get(CONF_VALUE, None)

    @property
    def last_measurement(self):
        try:
            last_measure = datetime.fromisoformat(
                self.coordinator._data.get(CONF_STATE, "")
            )
        except ValueError:
            last_measure = None
        return last_measure

    @property
    def extra_state_attributes(self):
        attrs = {ATTR_LAST_MEASURE: self.last_measurement}
        return attrs
