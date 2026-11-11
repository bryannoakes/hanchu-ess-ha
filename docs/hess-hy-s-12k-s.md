# HESS-HY-S-12K-S (model 29)

This page explains what the integration does differently for the Hanchu HESS-HY-S-12K-S (cloud `devModel` 29), why,
and what was and was not verified. Every model-specific behaviour is gated on `inverter_model.code == 29`, so other
models take exactly the code paths they took before.

**Tested on one installation only**: a single HESS-HY-S-12K-S (single phase, 12 kW, 48 V battery with BMS) on the
Hanchu cloud in November 2026. No other model was tested, so nothing here is claimed for them.

## Why this model needs its own path

The integration reads and writes settings through the generic HA endpoints (`/app/ha/iotGet`, `/app/ha/iotSet`) using
generic keys such as `WORK_MODE_CMB` and `CHG_PWR_LMT`. For model 29:

- `/app/ha/iotGet` answers `code 100 / data 900001` instead of values, so the generic startup read and Read Settings
  returned nothing usable.
- The model's real settings use a different key set (`workMode`, `chgSocLmt`, `timedChargeEnable`,
  `startChgTime1`, `timePeriod1MaxChgPwr`, ...), with different meanings from the generic keys. The generic
  Work Mode, number and time controls would send values the device does not interpret the same way.

The same HA-scoped token does work against the encrypted platform endpoint `POST /gateway/platform/deviceNew/iotGet`
(AES body as in `crypto.py`, `Content-Type: text/plain`, `version: 1.0`). That is what the model-29 path uses.

## What changes for model 29

| Change | Why |
|---|---|
| Settings are read from `/platform/deviceNew/iotGet` by a dedicated on-demand coordinator (startup and **Read Settings** only, no polling) | The generic read does not work on this model; settings change rarely and polling would add cloud load. |
| The 40 settings are exposed as read-only **diagnostic** sensors, plus a "Settings Last Refresh" sensor | Visibility without any write risk. `EntityCategory.CONFIG` is rejected by Home Assistant for sensors (this left all of them unavailable), so the diagnostic category is used. |
| The generic Work Mode, number, time, Write Settings and Fast Charge/Discharge entities are not created | Their keys and semantics do not match this model; a write through them would be unverified. |
| `hanchuess.device_control`, the websocket `iot_set` and `fast_charge`, and the fast-charge service are refused for a model-29 target | Defence in depth: hiding the entities is not enough while the services are still callable. The check uses the target entry's model, never the caller-supplied `dev_type`. |
| The pending-settings counter sensor is not created | Nothing is staged in the read-only version. |
| A 12K-S that was identified once is remembered in the config entry | The guards above depend on knowing the model. If a later status response omits `devModel`, the model would look unknown and the generic write paths would reopen, so this PR must not rely on a later one for that protection. |
| No schedule poll for the Inverter Status sensor (added in 2.4.0) | That poll reads generic keys through `/app/ha/iotGet`, which does not answer for this model. The sensor still works from the realtime data (charging, discharging, idle); its fast/scheduled states need the generic schedule keys and are not available on model 29. |
| A model-29 settings block appears in diagnostics | Support. It is passed through the existing redaction. |
| API debug logging no longer prints response bodies, and the "unexpected status" error no longer prints the payload (**applies to every model**, not only model 29) | Platform responses can contain account or station data and users paste debug logs into issues. Only the status and the response code are logged. |

## Settings read

`PLATFORM_SETTING_KEYS` in `settings_12k.py` lists the keys (the work mode and battery/PV/grid-charging management
options, the timed charge/discharge enables, `chgSocLmt`, and for each of the three charge and three discharge periods:
start/end time, stop SOC, stop voltage, maximum power and, for charging, the energy source). The key names and the
option lists were taken from the cloud menu metadata (`/app/ha/menu`) and verified against live responses. Values
without an established meaning are shown raw rather than guessed.

Times are `"HHMM"` strings. Numbers arrive as strings and are decoded for display.

## Not covered

- Any other model.
- Writing settings (a separate change).
- The bundled Lovelace settings card: it speaks the generic keys and does not work on model 29.
- The vendor manual is the authority on inverter behaviour:
  <https://oss-cdn.hanchuess.com/backend/document/pcs/HESS-HY-S-12K-S.pdf>. This integration only mirrors what the
  cloud reports.
