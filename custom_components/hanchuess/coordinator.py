"""DataUpdateCoordinator for Hanchuess."""
import asyncio
import math
import logging
from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    TimestampDataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from .api import HanchuessApiClient, ReauthRequired, TokenExpired
from .settings_12k import PLATFORM_SETTING_KEYS
from .const import (
    DOMAIN,
    CONF_REALTIME_INTERVAL,
    CONF_STATISTICS_INTERVAL,
    CONF_BATTERY_INTERVAL,
    CONF_SCHEDULE_INTERVAL,
    DEFAULT_SCHEDULE_INTERVAL,
    MIN_SCHEDULE_INTERVAL,
    SCHEDULE_KEYS,
    DEFAULT_REALTIME_INTERVAL,
    DEFAULT_STATISTICS_INTERVAL,
    DEFAULT_BATTERY_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _raise_auth_failed(client: HanchuessApiClient, msg: str):
    """Raise ConfigEntryAuthFailed once, UpdateFailed for the rest."""
    if not client._reauth_triggered:
        client._reauth_triggered = True
        raise ConfigEntryAuthFailed(msg)
    raise UpdateFailed(msg)


async def _try_refresh(client, update_cb, force=False):
    """Try to refresh token. Returns True if refreshed, raises on reauth needed."""
    try:
        new_token = await client.async_refresh_token(force=force)
    except ReauthRequired:
        _raise_auth_failed(client, "Token refresh returned 90076, reauth required")
    if new_token:
        update_cb(new_token)
        return True
    return False


class HanchuessRealtimeCoordinator(DataUpdateCoordinator):
    """Realtime data coordinator (60s)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HanchuessApiClient):
        super().__init__(
            hass,
            _LOGGER,
            name="hanchuess_realtime",
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(
                    CONF_REALTIME_INTERVAL, DEFAULT_REALTIME_INTERVAL
                )
            ),
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict:
        inverter_serial_number = self.entry.data["sn"]
        language = self.hass.config.language or "en"

        # Proactive refresh at 25 days
        if self.client.should_refresh_token():
            await _try_refresh(self.client, self._update_entry_token)

        data = await self.client.async_get_device_status(
            inverter_serial_number, language
        )

        # Reactive refresh on 401
        if data and data.get("_token_expired"):
            refreshed = await _try_refresh(self.client, self._update_entry_token, force=True)
            if refreshed:
                data = await self.client.async_get_device_status(
                    inverter_serial_number, language
                )

        if data and data.get("_token_expired"):
            _raise_auth_failed(self.client, "Token expired and refresh failed")

        if not data:
            raise UpdateFailed("Failed to get device status")
        return data

    def _update_entry_token(self, token: str):
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, "token": token}
            )


class HanchuessStatisticsCoordinator(DataUpdateCoordinator):
    """Statistics data coordinator (5min)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HanchuessApiClient):
        super().__init__(
            hass,
            _LOGGER,
            name="hanchuess_statistics",
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(
                    CONF_STATISTICS_INTERVAL, DEFAULT_STATISTICS_INTERVAL
                )
            ),
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict:
        inverter_serial_number = self.entry.data["sn"]
        language = self.hass.config.language or "en"

        data = await self.client.async_get_device_statistics(
            inverter_serial_number, language
        )

        if data and data.get("_token_expired"):
            refreshed = await _try_refresh(self.client, self._update_entry_token, force=True)
            if refreshed:
                data = await self.client.async_get_device_statistics(
                    inverter_serial_number, language
                )

        if data and data.get("_token_expired"):
            _raise_auth_failed(self.client, "Token expired and refresh failed")

        if not data:
            raise UpdateFailed("Failed to get device statistics")
        return data

    def _update_entry_token(self, token: str):
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, "token": token}
            )


def _same(raw, sent) -> bool:
    """Compare a read-back value with what was sent (strings like '0300', '97')."""
    if raw is None:
        return False
    if isinstance(sent, str):
        return str(raw).strip() == sent
    try:
        number = float(raw)
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(number):
        return False
    if isinstance(sent, float):
        return abs(number - sent) < 1e-6
    # Integers and enums must match exactly: "97.9" never confirms 97.
    return number.is_integer() and int(number) == sent


def _is_on(value) -> bool:
    """True for a device on/off value that means "on" (1, "1", "1.0", True)."""
    try:
        return float(value) == 1
    except (TypeError, ValueError, OverflowError):
        return False


class WriteAuthError(HomeAssistantError):
    """A settings write could not authenticate; the flush must stop."""


class HanchuessSettingsCoordinator(TimestampDataUpdateCoordinator):
    """On-demand model-29 settings coordinator.

    Settings are intentionally not polled periodically. They refresh at startup
    and whenever the Read Settings button is pressed.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HanchuessApiClient):
        super().__init__(
            hass,
            _LOGGER,
            name="hanchuess_settings",
            config_entry=entry,
            update_interval=None,
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict:
        inverter_serial_number = self.entry.data["sn"]
        language = self.hass.config.language or "en"

        data = await self._platform_get(
            inverter_serial_number, PLATFORM_SETTING_KEYS, language=language
        )
        if not data:
            raise UpdateFailed("Failed to get model-29 settings")
        _LOGGER.debug("[HANCHUESS] Model-29 settings refresh returned %d keys", len(data))
        return data


    def _update_entry_token(self, token: str):
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, "token": token}
            )

    async def _refresh_or_fail(self) -> None:
        """Force a token refresh after a 401, or raise the usual auth errors."""
        if not await _try_refresh(self.client, self._update_entry_token, force=True):
            _raise_auth_failed(self.client, "Token expired and refresh failed")

    async def _platform_get(self, sn: str, keys: list, language: str = "en") -> dict:
        """Read platform settings, refreshing the token once on a 401."""
        try:
            return await self.client.async_platform_iot_get(
                sn, "2", keys, language=language, raise_on_expired=True
            )
        except TokenExpired:
            await self._refresh_or_fail()
            try:
                return await self.client.async_platform_iot_get(
                    sn, "2", keys, language=language, raise_on_expired=True
                )
            except TokenExpired:
                # Refreshed once already: report it, do not refresh again.
                _raise_auth_failed(self.client, "Token still rejected after refresh")

    async def _platform_set(self, sn: str, value: dict) -> dict:
        """Write platform settings, refreshing the token once on a 401."""
        result = await self.client.async_platform_iot_set(sn, "2", value)
        if result.get("msg") == "token_expired":
            await self._refresh_or_fail()
            result = await self.client.async_platform_iot_set(sn, "2", value)
            if result.get("msg") == "token_expired":
                # Refreshed once already: do not refresh again, ask for reauth.
                self._start_reauth()
                raise WriteAuthError(
                    "Token still rejected after refresh; re-authentication required"
                )
        return result

    def _start_reauth(self) -> None:
        start = getattr(self.entry, "async_start_reauth", None)
        if start is not None:
            start(getattr(self, "hass", None))

    @property
    def _write_lock(self) -> asyncio.Lock:
        lock = getattr(self, "_write_lock_obj", None)
        if lock is None:
            lock = self._write_lock_obj = asyncio.Lock()
        return lock

    @staticmethod
    def _superseded(staging, snapshot: dict, key: str, value) -> bool:
        """True if ``key`` is no longer staged with ``value`` (edited or discarded since the snapshot)."""
        pending = staging.pending
        if key in snapshot:
            return pending.get(key) != value
        # A re-enable added by the flush: only an explicit newer edit overrides it.
        return key in pending and pending[key] != value

    async def async_write_staged(self, staging) -> dict[str, str]:
        """Write every staged key through the guarded writer, one key at a time.

        Under the write lock: the whole snapshot is validated first and nothing
        is sent if any staged value is invalid.  A schedule that is currently
        enabled is disabled before its parameters change and re-enabled only
        after every staged parameter is confirmed (otherwise it is left
        disabled and the re-enable is staged).  Order: schedule disables, then
        ordinary keys and schedule parameters, then schedule enables.  Each
        key is confirmed by read-back.  Confirmed keys leave the staging buffer
        unless the user staged a newer value meanwhile; failed keys stay
        staged.  An authentication failure stops the flush.  Returns
        {key: error}.
        """
        from .settings_12k import (
            SCHEDULE_ENABLE,
            SettingWriteError,
            plan_write_order,
            validate_setting_write,
        )

        async with self._write_lock:
            snapshot = staging.snapshot()
            errors: dict[str, str] = {}
            for key, value in snapshot.items():
                try:
                    validate_setting_write(key, value)
                except SettingWriteError as err:
                    errors[key] = str(err)
            if errors:
                # All or nothing at preflight: send nothing.
                for key in snapshot:
                    errors.setdefault(key, "not written: another staged change is invalid")
                self.async_update_listeners()
                return errors

            sn = self.entry.data["sn"]
            effective = dict(snapshot)
            reenabled: set[str] = set()
            for enable, pattern in SCHEDULE_ENABLE.items():
                params = [k for k in snapshot if k != enable and pattern.match(k)]
                if not params:
                    continue
                if enable in snapshot and not _is_on(snapshot[enable]):
                    continue  # being turned off: the planner disables it first
                try:
                    live = (await self._platform_get(sn, [enable])).get(enable)
                    read_error = "no value returned"
                except (UpdateFailed, ConfigEntryAuthFailed) as err:
                    self._start_reauth()
                    live, read_error = None, str(err)
                if live is None:
                    for key in params:
                        errors[key] = f"not written: could not read current {enable} ({read_error})"
                    continue
                if not _is_on(live):
                    continue  # currently off: a staged enable is written last
                try:
                    await self.async_write_setting(enable, 0)
                except WriteAuthError as err:
                    for key in snapshot:
                        errors[key] = f"not written: {err}"
                    self.async_update_listeners()
                    return errors
                except HomeAssistantError as err:
                    for key in params:
                        errors[key] = f"not written: {enable} could not be disabled first ({err})"
                    continue
                effective[enable] = 1  # re-enable last
                reenabled.add(enable)

            aborted = False
            for key, group_keys in plan_write_order(effective):
                value = effective[key]
                if key in errors:
                    continue
                if aborted:
                    errors[key] = "not written: authentication failed"
                    continue
                blocked = [k for k in group_keys if k in errors]
                if blocked:
                    errors[key] = f"not written: {', '.join(blocked)} did not apply"
                    continue
                if self._superseded(staging, snapshot, key, value):
                    # The user changed (or discarded) this edit while earlier keys
                    # were being written: never send the outdated value.
                    errors[key] = (
                        "not written: changed while writing; "
                        "press Write Settings again to apply the new value"
                    )
                    continue
                try:
                    await self.async_write_setting(key, value)
                except WriteAuthError as err:
                    errors[key] = str(err)
                    aborted = True
                except HomeAssistantError as err:
                    errors[key] = str(err)
                else:
                    staging.discard_if_value(key, value)

            for enable in reenabled:
                if enable in errors:
                    errors[enable] = f"schedule left DISABLED ({errors[enable]})"
                    if enable not in snapshot:
                        staging.stage(enable, 1)  # shown as pending; next flush re-enables
            self.async_update_listeners()  # entities drop their pending marker
            return errors

    async def async_refresh_settings(self, staging) -> bool:
        """Read settings from the device (Read Settings), waiting for any flush.

        Pending edits are dropped only for keys that were actually re-read, and
        only if they were not changed while the read ran.  Returns False (and
        keeps every edit) when the read failed.
        """
        async with self._write_lock:
            before = staging.snapshot()
            await self.async_refresh()
            if not self.last_update_success:
                return False
            fetched = self.data or {}
            for key, value in before.items():
                if key in fetched:
                    staging.discard_if_value(key, value)
            self.async_update_listeners()
            return True

    async def async_clear_staged(self, staging) -> None:
        """Discard all pending edits, waiting for any flush in progress."""
        async with self._write_lock:
            staging.clear()
            self.async_update_listeners()

    async def async_write_setting(
        self, key: str, value, *, attempts: int = 6, delay: float = 3.0
    ):
        """Write one allow-listed setting and confirm it by reading it back.

        Raises HomeAssistantError if the write is refused, rejected, or the
        cloud never reports the new value.  Never trusts the write response.
        """
        from homeassistant.exceptions import HomeAssistantError

        from .settings_12k import SettingWriteError, validate_setting_write

        try:
            number = validate_setting_write(key, value)
        except SettingWriteError as err:
            raise HomeAssistantError(str(err)) from err
        sn = self.entry.data["sn"]
        try:
            result = await self._platform_set(sn, {key: number})
        except (UpdateFailed, ConfigEntryAuthFailed) as err:  # repeat auth failure
            self._start_reauth()
            raise WriteAuthError(str(err)) from err
        uncertain = bool(result.get("uncertain"))
        if not result.get("success") and not uncertain:
            raise HomeAssistantError(
                f"Hanchu rejected {key} write: {result.get('msg', 'unknown error')}"
            )
        # When the outcome is uncertain the read-back below decides: the write may
        # have been queued even though no answer arrived.
        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(delay)
            try:
                read = await self._platform_get(sn, [key])
            except (UpdateFailed, ConfigEntryAuthFailed) as err:
                self._start_reauth()
                raise WriteAuthError(str(err)) from err
            if _same(read.get(key), number):
                self.async_set_updated_data({**(self.data or {}), key: str(number)})
                return number
        if uncertain:
            raise HomeAssistantError(
                f"{key}: no answer to the write and read-back did not confirm {number}; "
                "the outcome is unknown, check the value before writing again"
            )
        raise HomeAssistantError(
            f"{key} write was accepted but read-back did not confirm {number}"
        )


class HanchuessBatteryCoordinator(DataUpdateCoordinator):
    """Battery data coordinator."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HanchuessApiClient):
        super().__init__(
            hass,
            _LOGGER,
            name="hanchuess_battery",
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(
                    CONF_BATTERY_INTERVAL, DEFAULT_BATTERY_INTERVAL
                )
            ),
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict:
        battery_serials = self.entry.data.get("battery_serials", [])
        if not battery_serials:
            return {}
        language = self.hass.config.language or "en"

        async def _fetch(serial: str):
            return serial, await self.client.async_get_battery_data(serial, language)

        results = await asyncio.gather(*(_fetch(serial) for serial in battery_serials))
        data = {}
        token_expired = False
        for serial, result in results:
            if result and result.get("_token_expired"):
                token_expired = True
                continue
            if result:
                data[serial] = result.get("data", {})

        if token_expired:
            refreshed = await _try_refresh(self.client, self._update_entry_token, force=True)
            if refreshed:
                return await self._async_update_data()
            _raise_auth_failed(self.client, "Token expired and refresh failed")

        if not data:
            raise UpdateFailed("Failed to get battery data")
        return data

    def _update_entry_token(self, token: str):
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, "token": token}
            )


class HanchuessScheduleCoordinator(DataUpdateCoordinator):
    """Polls the inverter's work mode, slots and SOC limits (default 5 min).

    Feeds the Inverter Status sensor only. The values are kept in this
    coordinator rather than written to the control entities, so a poll never
    overwrites settings the user has staged but not yet written. Auth problems
    are left to the realtime coordinator; a failed poll keeps the last values.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HanchuessApiClient):
        interval = max(
            int(entry.options.get(CONF_SCHEDULE_INTERVAL, DEFAULT_SCHEDULE_INTERVAL)),
            MIN_SCHEDULE_INTERVAL,
        )
        super().__init__(
            hass,
            _LOGGER,
            name="hanchuess_schedule",
            config_entry=entry,
            update_interval=timedelta(seconds=interval),
        )
        self.entry = entry
        self.client = client
        self.last_read = None  # when values were last read from the inverter

    def seed(self, values: dict) -> None:
        """Use values already read from the inverter (e.g. at startup)."""
        seeded = {k: v for k, v in values.items() if k in SCHEDULE_KEYS}
        if seeded:
            self.last_read = dt_util.utcnow()
            self.async_set_updated_data(seeded)

    async def _async_update_data(self) -> dict:
        values = await self.client.async_iot_get(
            self.entry.data["sn"], "2", SCHEDULE_KEYS
        )
        if values:
            self.last_read = dt_util.utcnow()
            return {**(self.data or {}), **values}
        if self.data:
            _LOGGER.debug("[HANCHUESS] Schedule poll returned nothing, keeping last values")
            return self.data
        raise UpdateFailed("Failed to read inverter schedule")

    def note_written(self, values: dict) -> None:
        """Merge settings this integration has just written successfully."""
        written = {k: v for k, v in values.items() if k in SCHEDULE_KEYS}
        if written:
            self.async_set_updated_data({**(self.data or {}), **written})
