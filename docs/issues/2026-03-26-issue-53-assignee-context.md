# Issue 53 Assignee Context (2026-03-26)

## What `#53` Depends On

Issue `#53` is not the next thing to start immediately from the current firmware baseline.

It depends on two earlier tracks:

- paused `#51` for display-quality recovery when needed
- active `#52` for major product behavior migration

The practical rule is:

- `#52` should define the app behavior model
- `#53` should integrate the runtime host responsibilities around that model

## What `#53` Owns

`#53` is the device-runtime integration issue.

It should own:

- refresh-policy integration on ESP32
- minimal persistence/settings storage
- hosted-service client integration
- normal boot -> runtime -> update loop without Python dependency

It should not own:

- major product behavior migration that belongs in `#52`
- LUT research that belongs in paused `#51`

## Current Firmware Reality

Current firmware already has:

- runtime boot loop
- reducer dispatch
- basic on-device rendering
- built-in defaults

Current firmware does not yet have:

- full C++ product behavior model
- C++ refresh-policy parity with Python
- persistence layer for product settings/state
- hosted backend clients
- full device-side runtime independence from Python

## Python / Doc References For `#53`

Primary code references:

- `app/render/refresh_policy.py`
- `app/ui/app.py`
- `app/voice/client.py`
- `app/voice/actions.py`
- `app/data/device_config.py`
- `tools/run_epaper_console.py`

Important product docs:

- `docs/EPD_REFRESH_STRATEGY_PLAYBOOK.md`
- `docs/SETTINGS_V1.md`
- `docs/VOICE_INTERACTION_CONTRACT.md`
- `docs/VOICE_PIPELINE_MVP.md`
- `docs/VOICE_LATENCY_BUDGET.md`
- `docs/VOICE_BACKEND_DEPLOYMENT_RENDER.md`

## Recommended Work Decomposition

### Track 1: Refresh policy integration

Goal:

- move from ad-hoc display calls toward a policy-driven refresh path on ESP32

Expected outputs:

- runtime refresh state
- partial/full decision logic
- safe fallback rules

### Track 2: Persistence and settings

Goal:

- replace pure built-in-default boot with a minimal persisted device configuration path

Expected outputs:

- stored settings/default overlay
- boot-time load path
- runtime save/update path

### Track 3: Hosted service clients

Goal:

- let the device runtime talk to required backend services without Python acting as the runtime host

Expected outputs:

- client interfaces
- request/response integration points
- failure and offline handling boundaries

### Track 4: End-to-end runtime hosting

Goal:

- make ESP32 the actual device-side runtime host

Expected outputs:

- boot -> state load -> render -> interaction -> update loop all owned by firmware

## When `#53` Should Start

`#53` is best started when `#52` has at least:

1. the major `Screen` set defined in C++
2. reducer-driven navigation for the major screens
3. enough stable app-state structure that refresh and persistence can target it

Without that, `#53` risks building integration around an unstable state model.

## Guardrails For Assignees

During `#53`, do not silently absorb paused `#51` LUT work.

Treat display quality this way:

- consume the current `display.cpp` path as the hardware interface
- integrate runtime refresh policy around it
- keep LUT/waveform experiments on the separate `#51` track unless explicitly reassigned

This avoids mixing:

- product integration work
- hardware waveform research

## Recommended GitHub Issue Notes

If you assign `#53`, add clarifications that:

- it follows `#52`, not the current paused `#51` branch head
- it owns runtime integration, not behavior migration
- it does not automatically include LUT recovery work

## Related Docs

- `docs/issues/2026-03-26-issue-51-freeze-and-issue-52-kickoff.md`
- `docs/issues/2026-03-26-issue-52-assignee-context.md`
- `firmware/docs/display_experiments.md`
