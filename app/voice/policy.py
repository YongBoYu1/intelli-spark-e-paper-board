from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VoicePolicyRule:
    require_confirm: bool = False
    dedup: bool = False
    require_inventory_match: bool = False
    create_inventory_if_missing: bool = False
    remove_matching_shopping: bool = False


@dataclass(frozen=True)
class VoicePolicyDecision:
    key: str
    rule: VoicePolicyRule
    reason: str = ""


_DEFAULT_RULE = VoicePolicyRule()


VOICE_POLICY_V1: dict[str, VoicePolicyRule] = {
    # Shopping
    "shopping_add_item": VoicePolicyRule(dedup=True),
    "shopping_remove_item": VoicePolicyRule(),
    "shopping_clear_all": VoicePolicyRule(require_confirm=True),
    "timer_set": VoicePolicyRule(),
    "memo_add": VoicePolicyRule(),
    "inventory_clear_all": VoicePolicyRule(require_confirm=True),
    "inventory_set_expiry": VoicePolicyRule(require_inventory_match=True),
    # Inventory semantics
    "inventory_log_event:consumed": VoicePolicyRule(require_inventory_match=True),
    "inventory_log_event:used": VoicePolicyRule(require_inventory_match=True),
    "inventory_log_event:finished": VoicePolicyRule(require_inventory_match=True),
    # Restock/bought: update existing if present; can auto-create new inventory rows (with 3-slot eviction).
    # Whether a new row is actually created may depend on shopping linkage in actions.py (e.g., buy list removal only).
    "inventory_log_event:added": VoicePolicyRule(
        create_inventory_if_missing=True,
        remove_matching_shopping=True,
    ),
    "inventory_log_event:restocked": VoicePolicyRule(
        create_inventory_if_missing=True,
        remove_matching_shopping=True,
    ),
}


def policy_key_for_action(tool: str, args: dict[str, Any] | None = None) -> str:
    tool_name = str(tool or "").strip()
    a = dict(args or {})
    if tool_name == "inventory_log_event":
        event_type = str(a.get("event_type") or "").strip().lower()
        if event_type:
            return f"{tool_name}:{event_type}"
    return tool_name


def decide_voice_policy(tool: str, args: dict[str, Any] | None = None) -> VoicePolicyDecision:
    key = policy_key_for_action(tool, args)
    rule = VOICE_POLICY_V1.get(key)
    if rule is not None:
        return VoicePolicyDecision(key=key, rule=rule, reason="policy_match")

    tool_key = str(tool or "").strip()
    tool_rule = VOICE_POLICY_V1.get(tool_key)
    if tool_rule is not None:
        return VoicePolicyDecision(key=tool_key, rule=tool_rule, reason="tool_default")

    return VoicePolicyDecision(key=key or tool_key or "unknown", rule=_DEFAULT_RULE, reason="default")
