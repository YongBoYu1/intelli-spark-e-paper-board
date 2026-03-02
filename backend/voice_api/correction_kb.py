from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any


class CorrectionKB:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._loaded = False
        self._data: dict[str, Any] = {"version": 1, "scopes": {}}

    def apply(self, text: str, *, scope_id: str) -> tuple[str, list[dict[str, Any]]]:
        txt = str(text or "")
        if not txt:
            return txt, []
        self._load_if_needed()
        with self._lock:
            aliases = self._aliases_for_scope_locked(scope_id)
            ordered = sorted(
                ((str(k), str(v)) for k, v in aliases.items()),
                key=lambda kv: len(kv[0]),
                reverse=True,
            )

        out = txt
        hits: list[dict[str, Any]] = []
        for wrong, correct in ordered:
            wrong = wrong.strip()
            correct = correct.strip()
            if not wrong or not correct or wrong == correct:
                continue
            pat = _compile_alias_pattern(wrong)
            out, count = pat.subn(correct, out)
            if count <= 0:
                continue
            hits.append({"wrong": wrong, "correct": correct, "count": count})
        return out, hits

    def upsert(self, *, scope_id: str, wrong: str, correct: str) -> bool:
        wrong_txt = str(wrong or "").strip()
        correct_txt = str(correct or "").strip()
        if not wrong_txt or not correct_txt:
            return False
        if wrong_txt == correct_txt:
            return False
        self._load_if_needed()
        with self._lock:
            aliases = self._aliases_for_scope_locked(scope_id)
            old = str(aliases.get(wrong_txt) or "").strip()
            if old == correct_txt:
                return False
            aliases[wrong_txt] = correct_txt
            self._touch_scope_locked(scope_id)
            self._save_locked()
        return True

    def _load_if_needed(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            if self._path.exists():
                try:
                    parsed = json.loads(self._path.read_text(encoding="utf-8"))
                except Exception:
                    parsed = {}
                if isinstance(parsed, dict):
                    scopes = parsed.get("scopes")
                    if isinstance(scopes, dict):
                        self._data = {"version": 1, "scopes": scopes}
                    else:
                        self._data = {"version": 1, "scopes": {}}
                else:
                    self._data = {"version": 1, "scopes": {}}
            else:
                self._data = {"version": 1, "scopes": {}}
            self._loaded = True

    def _save_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_path, self._path)

    def _scope_locked(self, scope_id: str) -> dict[str, Any]:
        scopes = self._data.get("scopes")
        if not isinstance(scopes, dict):
            scopes = {}
            self._data["scopes"] = scopes
        sid = str(scope_id or "default").strip() or "default"
        scope = scopes.get(sid)
        if not isinstance(scope, dict):
            scope = {}
            scopes[sid] = scope
        return scope

    def _aliases_for_scope_locked(self, scope_id: str) -> dict[str, str]:
        scope = self._scope_locked(scope_id)
        aliases = scope.get("aliases")
        if not isinstance(aliases, dict):
            aliases = {}
            scope["aliases"] = aliases
        out: dict[str, str] = {}
        for k, v in aliases.items():
            kk = str(k or "").strip()
            vv = str(v or "").strip()
            if not kk or not vv:
                continue
            out[kk] = vv
        scope["aliases"] = out
        return out

    def _touch_scope_locked(self, scope_id: str) -> None:
        scope = self._scope_locked(scope_id)
        scope["updated_at"] = float(time.time())


_kb_singleton: CorrectionKB | None = None
_kb_singleton_lock = threading.Lock()


def get_correction_kb() -> CorrectionKB:
    global _kb_singleton
    with _kb_singleton_lock:
        if _kb_singleton is None:
            repo_root = Path(__file__).resolve().parents[2]
            default_path = repo_root / "backend" / "voice_api" / "data" / "correction_kb.json"
            path = str(os.environ.get("VOICE_CORRECTION_KB_PATH") or str(default_path))
            _kb_singleton = CorrectionKB(path)
        return _kb_singleton


def _compile_alias_pattern(wrong: str) -> re.Pattern[str]:
    needle = str(wrong or "").strip()
    if _is_latin_term(needle):
        core = _build_latin_fuzzy_core_pattern(needle)
        # Use ASCII token boundaries so "ham" does not match "champagne".
        return re.compile(rf"(?<![A-Za-z0-9]){core}(?![A-Za-z0-9])", flags=re.IGNORECASE)
    return re.compile(re.escape(needle))


def _is_latin_term(text: str) -> bool:
    txt = str(text or "").strip()
    if not txt:
        return False
    # Supports casual brand names like "Wendy's", "Tim-Hortons", "7-Eleven".
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 '\-_.&/]*", txt))


def _build_latin_fuzzy_core_pattern(text: str) -> str:
    parts: list[str] = []
    for ch in str(text or ""):
        if ch in {"'", "’", "‘"}:
            parts.append(r"(?:['’‘])")
            continue
        if ch in {"-", "‐", "‑", "–", "—"}:
            parts.append(r"(?:[-‐‑–—])")
            continue
        if ch.isspace():
            parts.append(r"\s+")
            continue
        parts.append(re.escape(ch))
    return "".join(parts)
