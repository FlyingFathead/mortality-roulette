"""Data-driven explanatory notes for selected resolved underlying causes.

Notes are deterministic annotations downstream of cause selection. They never
change mortality, cause/detail probabilities, RNG state, PLACE, seasonality, or
other context rolls. The table is intentionally sparse: a note is shown only
where the project has a specific reason to clarify what an underlying-cause
code does (and does not) tell us.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_ICD_RE = re.compile(r"(?<![A-Z0-9])([A-Z][0-9]{2}(?:[.]?[0-9]{1,2})?)(?![A-Z0-9])", re.I)
_ICD_RANGE_RE = re.compile(r"([A-Z][0-9]{2})\s*[-–—]\s*([A-Z][0-9]{2})", re.I)


def _norm_icd(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _icd3_key(code: str) -> tuple[int, int] | None:
    n = _norm_icd(code)
    if len(n) < 3 or not n[0].isalpha() or not n[1:3].isdigit():
        return None
    return (ord(n[0]), int(n[1:3]))


def _icd3_in_range(code: str, spec: str) -> bool:
    m = _ICD_RANGE_RE.fullmatch(str(spec).strip())
    if not m:
        return False
    key = _icd3_key(code)
    lo = _icd3_key(m.group(1))
    hi = _icd3_key(m.group(2))
    return bool(key and lo and hi and lo <= key <= hi)


def _specific_codes(outcome: dict[str, Any] | None) -> set[str]:
    """Extract realized ICD codes without treating broad range endpoints as hits."""
    if not isinstance(outcome, dict) or not outcome.get("available", True):
        return set()
    codes: set[str] = set()
    for key in ("code", "parent_code"):
        value = outcome.get(key)
        if value:
            n = _norm_icd(str(value))
            if 3 <= len(n) <= 5:
                codes.add(n)
    text = " | ".join(
        str(outcome.get(k, ""))
        for k in ("label", "parent_label", "classification")
    )
    text = _ICD_RANGE_RE.sub(" ", text)
    for token in _ICD_RE.findall(text):
        codes.add(_norm_icd(token))
    return codes


def _matches(outcome: dict[str, Any] | None, trigger: dict[str, Any]) -> bool:
    if not isinstance(outcome, dict) or not outcome.get("available", True):
        return False

    source = str(outcome.get("source", "")).casefold()
    required_sources = [str(x).casefold() for x in trigger.get("source_contains", [])]
    if required_sources and not any(piece in source for piece in required_sources):
        return False

    text = " | ".join(
        str(outcome.get(k, ""))
        for k in ("label", "parent_label", "classification")
    ).casefold()
    for excluded in trigger.get("exclude_label_contains", []):
        if str(excluded).casefold() in text:
            return False

    codes = _specific_codes(outcome)
    exact = {_norm_icd(x) for x in trigger.get("icd_exact", [])}
    if exact and codes & exact:
        return True
    ranges = list(trigger.get("icd_ranges", []))
    if ranges and any(_icd3_in_range(code, spec) for code in codes for spec in ranges):
        return True
    labels = [str(x).casefold() for x in trigger.get("label_contains", [])]
    return bool(labels and any(piece in text for piece in labels))


class CauseNoteModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.notes = list(payload.get("notes", []))

    @classmethod
    def from_path(cls, path: Path) -> "CauseNoteModel":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def note_for_cause_stack(
        self,
        *,
        country: str,
        cause: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
        deep: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        requested_country = str(country).strip().upper()
        for rule in self.notes:
            countries = {str(x).strip().upper() for x in rule.get("countries", [])}
            if countries and requested_country not in countries:
                continue
            trigger = dict(rule.get("trigger", {}))
            for level, outcome in (("deep", deep), ("detail", detail), ("cause", cause)):
                if _matches(outcome, trigger):
                    return {
                        "available": True,
                        "id": str(rule.get("id", "cause-note")),
                        "text": str(rule.get("text", "")).strip(),
                        "level": level,
                        "provenance": str(rule.get("provenance", "")).strip(),
                        "model_id": str(self.payload.get("model_id", "cause-note-model")),
                    }
        return None
