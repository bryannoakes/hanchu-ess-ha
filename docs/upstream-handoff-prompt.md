# Prompt to take back to the original discussion

Paste everything below the line into the conversation where this work was scoped.

---

I took the scoped work (get a HESS-HY-S-12K-S, cloud `devModel` 29, fully working in Home Assistant with the
`upton68/hanchu-ess-ha` integration, packaged so it can be proposed upstream) and implemented, tested and live-validated
it on my installation. Everything is on my fork `bryannoakes/hanchu-ess-ha`; **nothing has been opened against
upstream**. I'd like your independent review of the packaging and of the safety-relevant code before anything goes to
the maintainer. Details, decisions and open questions follow.

## 1. What model 29 is, and what is specific to it

`devModel` 29 is the HESS-HY-S-12K-S (12 kW, 48 V, single phase). It is already in upstream's `models.py`. Its cloud
settings interface differs from the generic one:

- `/gateway/app/ha/iotGet` answers code 100 / data 900001; the same HA-scoped token works on the encrypted
  `/gateway/platform/deviceNew/iotGet` (read) and `/gateway/platform/deviceNew/iotSet` (write).
- Different key names (`workMode`, `gridCharging`, `timePeriodN...`, `chgSocLmt`, ...); times are `"HHMM"` **strings**
  (integers are rejected by the device); some values are floats; writes are asynchronous, so a write response proves
  nothing and a read-back is mandatory.
- Everything model-specific is gated on `inverter_model.code == 29`. Other models keep their current code paths.
  I could not test any other model; that is explicitly out of scope and the PRs say so.

## 2. The split (stacked branches on the fork, all based on current upstream/main, all green on Tests/Hassfest/HACS)

| Branch | Content | Scope |
| --- | --- | --- |
| `pr/3-test-aiohttp-shim` | `tests/conftest.py` shim for `aioresponses` 0.7.9 vs aiohttp 3.14 (fixes 21 baseline failures) | generic, test-only |
| `pr/1-manual-serial-fallback` (on 3) | config-flow fallback asking for the serial when `getDeviceList` is empty | generic |
| `pr/2-load-power-eps-fallback` (on 3) | Load Power prefers `loadEpsPwr` + unit, falls back to `loadPwr` | generic |
| `pr/4-model29-readonly` (on 3) | platform read, settings coordinator, diagnostic sensors, Read Settings, guards that disable the generic write paths for 29 | model 29 |
| `pr/5-model29-writes` (on 4) | allow-listed, staged, read-back-confirmed writes; opt-in grid export | model 29 |

`fix/manual-serial-fallback` (draft PR #1 on the fork) is the full integration branch; I verified that merging the five
pieces reproduces its code. Fork-only, deliberately not in the PR branches: `tools/probe.py`, the `.secrets/` ignore
entry, `docs/hess-hy-s-12k-s-manual.md` (extraction of the vendor manual), this file.

## 3. Decisions and the reasons for them

1. **Why settings looked "stale" (root cause).** Not a Hanchu cache: a fresh login under `appPlat: ha` and `iess`
   returns identical, current values. HA silently rejected 40 sensors because I had given them `EntityCategory.CONFIG`
   (not allowed for sensors); they sat unavailable. Fixed with `DIAGNOSTIC`. Worth checking that no other platform in
   the integration has the same latent problem.
2. **Load power is deliberately NOT model-gated.** Upstream's own captured samples (devModel 2 and 4, PRs 11/16/17)
   show `loadPwr` (W) = `loadEpsPwr` (kW) x 1000, so `loadEpsPwr` is the same aggregate with an explicit unit; on 29
   `loadPwr` is 0 while `loadEpsPwr` carries the load and PV + grid = load + battery closes. I cannot tell whether
   `loadPwr` = 0 is 29-specific or a later Hanchu change (all other-model samples are June 2026). Hence prefer
   `loadEpsPwr`, fall back to `loadPwr`. A current sample from another model would settle it.
3. **No aiohttp pin.** HA pins aiohttp itself; pinning in test requirements conflicts. A conftest shim is smaller and
   scoped to tests.
4. **Writes are an explicit allow-list, generated into entities.** `WRITABLE_SETTINGS` holds ranges/options taken from
   the cloud's own menu metadata (`/app/ha/menu`); entities, validation and tests all derive from it. Anything not on
   it (power on/off, restart, password, date/time, N-PE, P-PF curve, ...) is refused. Slot 2/3 entities are disabled
   by default in the registry.
5. **Write semantics: validate at stage time, write per key, confirm by read-back.** Writes go through the same
   `SettingsStagingBuffer` as other models (entities stage; Write Settings / `hanchuess.write_settings` flushes).
   Flush writes one key at a time (a mixed batch can partially succeed on this device) and polls `iotGet` until the value
   matches; unconfirmed keys stay staged and a notification lists them. Entities show the pending value and a
   `pending_write` attribute.
6. **Grid export is an opt-in, default off.** My installation may not export (local regulation). Option values that
   allow export (`workMode` 1 On Grid, `batDischgManagement` 3 Battery to grid sell, `pvChargingPriority` 2 First to
   grid) are hidden from selects and refused by validation unless the model-29-only integration option **Allow grid
   export settings** is on (then labelled "(grid export)"). The gate is enforced in the validator, not only the UI.
   **No export value was ever written to hardware**; that path is unit-tested only.
7. **Hybrid grid mode (`workMode`) is writable for options 2 and 3 only.** Live-tested 3 -> 2 -> 3.
8. **Generic write paths stay blocked for 29** (device_control service, WebSocket `iot_set`, fast charge, generic
   entities). Consequence: the bundled Lovelace "Remote Settings" card, which speaks the generic keys, does not work for
   model 29. I did not extend it.
9. **Gate on model code, not on capability detection.** Simple and testable; the 6K-S (code 28) is probably the same
   family but untested, so it is not included.

## 4. What was tested

- Automated: 303 passed / 2 skipped locally on Windows (config-flow tests need Linux); on the fork's Actions every
  branch passes Tests (Linux), Hassfest and HACS validation.
- Live on my HESS-HY-S-12K-S via Home Assistant, each change one concept at a time with the original captured and
  restored afterwards: grid charging on/off, timed charge/discharge enables, generator charging and max current, Battery
  Energy Manage (2 <-> 1), PV Energy Manage (0 <-> 1), Hybrid grid mode (3 -> 2 -> 3), `chgSocLmt`, all slot-1 numbers
  and times, charge energy source; slots 2/3 (22 keys) via the API; and the staged flow itself (stage -> cloud
  unchanged, pending count 1 -> Write Settings -> confirmed -> restored). Opt-in option toggled on/off to confirm the
  select contents.
- **Not tested:** any export value (intentionally), Battery Energy Manage "Standby" (0), charge energy source 2/3,
  any other inverter model, long-running behaviour of the staging buffer across restarts.

## 5. Known weak points I would like challenged

- `async_platform_iot_set` returns `token_expired` on 401 but the write path does not refresh the token and retry;
  the generic path's behaviour here should be compared.
- The settings coordinator is on-demand; a poll or Read Settings while edits are staged clears staging (Read Settings)
  or may overwrite displayed state. Is that the right semantics for "uniform with other models"?
- Per-key sequential writes with up to 6 x 3 s read-back each can make Write Settings slow for many staged keys.
- Voltage fields are sent as floats rounded to 1 decimal; device behaviour for finer values is unknown.
- Whether the opt-in option and its translations belong in the model-29 PR or a separate one.
- The `docs/model29-write-plan.md` file in PR 5 reads like an investigation log; should it ship or be trimmed?

## 6. Request

Please give an **independent review** (a different model or a human reviewer than the one that wrote this) of, in
priority order: (a) `pr/5` safety logic: `settings_12k.validate_setting_write`, the export gate, the staged flush and
read-back in `coordinator.py`; (b) whether the split above is the right shape for the maintainer, or whether 4+5 should
be one PR; (c) the load-power decision; (d) anything in `pr/4` that could affect non-29 models (it touches `__init__.py`,
`button.py`, `sensor.py`). Findings as a ranked list with file:line and a concrete failing scenario, please. If the
Claude Code `/code-review ultra` cloud review is available to you, running it against `pr/5-model29-writes` is welcome;
it is user-triggered and billed, so I have not run it.
