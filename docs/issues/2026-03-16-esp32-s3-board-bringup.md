# Issue Draft: ESP32-S3 board bring-up for Waveshare 7.5" V2 panel

## Title
Enable SANXIXING ESP32-S3 development board as the next hardware target for the e-paper device

## Summary
Start the board bring-up required to move this project from the current Raspberry Pi / Jetson Linux prototype toward an ESP32-S3-based device while preserving the existing e-paper UI behavior and input model.

## Context
Current repo status:

- Runtime is Python-based and Linux-only.
- Display integration depends on `waveshare_epd` Python modules.
- Rotary/button input depends on `RPi.GPIO`.
- User has prepared an ESP32-S3 development board and connected the e-paper panel.

This issue establishes the first migration checkpoint rather than claiming full parity with the current Linux prototype.

## Scope
1. Define hardware target metadata in repo config.
2. Document ESP32-S3 bring-up constraints and recommended migration sequence.
3. Freeze the exact board wiring for panel and input devices.
4. Introduce an ESP32 firmware skeleton in a follow-up change.
5. Validate panel init, clear, full draw, and input smoke test on the new board.

## Acceptance Criteria
- Repo config can distinguish `linux-rpi` from `esp32-s3`.
- ESP32-S3 target board is documented in the repo.
- Wiring requirements and first-slice bring-up steps are captured in a source-controlled doc.
- Follow-up implementation can proceed without re-deciding runtime target and migration order.

## Out Of Scope
- Full feature parity with the Raspberry Pi Python runtime
- Voice workflow migration
- Backend sync migration
- Production-grade deep sleep and power tuning
- Partial refresh optimization on day one

## Suggested Labels
- `hardware`
- `esp32`
- `e-ink`
- `enhancement`

## Proposed Branch
- `codex/esp32-s3-board-bringup`
