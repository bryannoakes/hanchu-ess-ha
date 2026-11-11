# Independent review prompt

Paste everything below the line into a fresh session (ideally a different model from the one that wrote the code, or a
human reviewer). Fork-only file; not part of any upstream PR.

---

You are reviewing, read-only, a change set for the Home Assistant custom integration `upton68/hanchu-ess-ha`. The work lives
on the fork `https://github.com/bryannoakes/hanchu-ess-ha`. **Do not push, comment on, open or merge anything, do not
create tags or touch workflows, and do not try to run anything against a real inverter or cloud account.** Review the code
and run the unit tests only. Do not print or ask for credentials; none are needed.

## Context

Goal: make the HESS-HY-S-12K-S (cloud `devModel` 29: 12 kW, 48 V, single phase hybrid) work fully in Home Assistant,
packaged so it can be proposed upstream. Other models could not be tested; all model-specific code is gated on
`inverter_model.code == 29`. The inverter supplies a whole house where grid export is prohibited, so **anything that can
cause export, or weaken inverter/BMS protection, is a safety defect**. Read `docs/model29-write-plan.md` (the write protocol)
and `docs/upstream-handoff-prompt.md` (decisions and known weak points) first.

Branches (stacked, all based on `upstream/main` c173a0f; none opened as upstream PRs):

| Branch | Content |
| --- | --- |
| `pr/3-test-aiohttp-shim` | `tests/conftest.py` shim for aioresponses vs aiohttp 3.14 |
| `pr/1-manual-serial-fallback` (on 3) | config-flow manual serial fallback |
| `pr/2-load-power-eps-fallback` (on 3) | Load Power prefers `loadEpsPwr`, falls back to `loadPwr` |
| `pr/4-model29-readonly` (on 3) | model-29 platform read, settings coordinator, diagnostic sensors, Read Settings, guards |
| `pr/5-model29-writes` (on 4) | allow-listed staged writes with read-back; opt-in grid export; token refresh on 401 |

`fix/manual-serial-fallback` is the full integration branch (superset). Review mainly `pr/5-model29-writes`; use
`git diff upstream/main...pr/5-model29-writes` (add the upstream remote `https://github.com/upton68/hanchu-ess-ha`).

## Review priorities (in order)

1. **Safety of the write path** (`settings_12k.py` `validate_setting_write`, `GRID_EXPORT_REFUSED`, `allowed_options`;
   `coordinator.py` `async_write_setting`, `async_write_staged`, `_platform_get/_set`; `settings_12k_entities.py`;
   `__init__.py` flush). Look for any route that lets an export value (`workMode` 1, `batDischgManagement` 3,
   `pvChargingPriority` 2) or a non-allow-listed key reach `iotSet` with the option off: type coercion (bool/str/float/NaN),
   key aliasing, the WebSocket and service paths, staged values surviving an option change, restore-state, and the generic
   `device_control` / `iot_set` / fast-charge paths that must stay blocked for model 29.
2. **Correctness of confirm/read-back and token refresh**: false confirmation, timing, partial failure, the 401 retry
   (infinite loop, double write, reauth handling), concurrency between a poll, Read Settings and a flush.
3. **Impact on non-29 models** from `pr/4`/`pr/5` (`__init__.py`, `button.py`, `sensor.py`, `api.py`, `config_flow.py`): any
   behaviour change when the model is not 29, including the Load Power change and the Write Settings / pending sensor now
   created for all models.
4. **Packaging**: is the five-way split the right shape for the maintainer, or should 4+5 be one PR? Is the opt-in option
   in the right PR? Should `docs/model29-write-plan.md` ship?
5. **Tests**: gaps against the safety properties above; anything asserting the wrong thing.
6. **Privacy**: anything that could log or expose serials, station ids, account names or tokens (logs, diagnostics,
   notifications, test fixtures, docs).

## Run

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-test.txt
pytest -q
```

(Config-flow tests skip on Windows and run on Linux.)

## Output

A ranked list of findings, most severe first. For each: `file:line`, one-sentence defect, a **concrete failing scenario**
(inputs/state -> wrong outcome), and a suggested fix. Mark each CONFIRMED (you reproduced it or traced it fully) or
PLAUSIBLE. Say explicitly what you did **not** check. If you find nothing in a priority area, say so and say how you looked.
