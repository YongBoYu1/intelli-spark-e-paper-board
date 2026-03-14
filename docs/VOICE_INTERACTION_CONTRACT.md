# Voice Interaction Contract

This document defines the product contract for voice interactions on the board.

## Core Rule

Voice is not a second UI system.

Voice only does two things:

1. Interpret speech into a canonical action, or return `no_action`.
2. Apply that action through the same state/UI semantics used by physical input.

If the interpreter returns `no_action`, nothing on the board changes.

## One Interaction Model

Physical input and voice input must share the same post-action behavior.

Examples:

- `remove`, `check`, `tick off`, `finish` all map to the same completion semantics.
- After an item is marked complete, the board must behave as if the user completed that item manually.
- Do not add voice-only UI behavior such as separate reorder, hide, or refresh rules.

## Screen-Owned Display Semantics

What happens after a valid action is applied is owned by the current screen, not by voice.

### Home (kitchen variants)

Completing an inventory/reminder item should:

- cross the item in its current visible position first
- keep the current Home completed-item behavior
- use `home_pending_hide_rids` / `home_hidden_rids`
- not trigger list-style `pending_reorder`

This preserves the current Home UX where completed rows remain briefly visible, then disappear later using the existing Home hide policy.

### Inventory / Reminders list screens

Completing an item should:

- cross the item first
- keep the existing list-page delayed reorder behavior
- use `pending_reorder` / `reorder_due_at`

### Other screens

If a screen already has an existing completion behavior, voice must reuse it.
If a screen does not expose item-completion UI semantics, voice must not invent a new one.

## Position Semantics

For positional commands such as `first`, `last`, or ordinal references:

- use the current visible order when the user is on the corresponding list screen
- otherwise use board context order
- if still ambiguous, return clarification rather than guessing

## Refresh / Navigation Rules

Voice must not create a separate app-launch or refresh pipeline.

- app open/navigation must reuse the same screen transition logic as physical input
- state changes must flow through the same refresh policy
- partial/full refresh decisions remain owned by the shared refresh system

## Implementation Guardrails

Future changes should preserve these invariants:

- no voice-specific branch for post-action UI semantics
- no second app-launch stack for voice
- no second refresh strategy for voice
- no mutation on `no_action`

## Current Shared Touchpoints

- State and screen semantics: `app/core/reducer.py`
- Voice action application: `app/voice/actions.py`
- Refresh behavior: `app/render/refresh_policy.py`
- Hardware runner: `tools/run_epaper_console.py`
