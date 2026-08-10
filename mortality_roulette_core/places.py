"""Cause-conditional statistical PLACE rolls.

PLACE is deliberately downstream of mortality/cause/detail.  The model may
represent an event setting (lake, private home, rural road) or the terminal
place of death (hospital, home, long-term care); ``semantic`` records which.
No place is emitted when the bundled evidence model does not support one.
"""
from __future__ import annotations

import bisect
import json
import random
import re
from pathlib import Path
from typing import Any

_ICD_RE = re.compile(r"(?<![A-Z0-9])([A-Z][0-9]{2}(?:[.]?[0-9]{1,2})?)(?![A-Z0-9])", re.I)
_ICD_RANGE_RE = re.compile(r"([A-Z][0-9]{2})\s*[-–]\s*([A-Z][0-9]{2})", re.I)


def _norm_icd(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _icd3_key(code: str) -> tuple[int, int] | None:
    n = _norm_icd(code)
    if len(n) < 3 or not n[0].isalpha() or not n[1:3].isdigit():
        return None
    return (ord(n[0]), int(n[1:3]))


def _icd3_in_range(code: str, spec: str) -> bool:
    m = _ICD_RANGE_RE.fullmatch(spec.strip())
    if not m:
        return False
    key = _icd3_key(code)
    lo = _icd3_key(m.group(1))
    hi = _icd3_key(m.group(2))
    return bool(key and lo and hi and lo <= key <= hi)


def _outcome_text(outcome: dict[str, Any] | None) -> str:
    if not isinstance(outcome, dict) or not outcome.get("available", True):
        return ""
    return " | ".join(str(outcome.get(k, "")) for k in ("code", "parent_code", "label", "parent_label", "classification"))


def _explicit_codes(outcome: dict[str, Any] | None) -> set[str]:
    if not isinstance(outcome, dict) or not outcome.get("available", True):
        return set()
    codes: set[str] = set()
    for key in ("code", "parent_code"):
        value = outcome.get(key)
        if value:
            codes.add(_norm_icd(str(value)))
    text = _outcome_text(outcome)
    for token in _ICD_RE.findall(text):
        codes.add(_norm_icd(token))
    return codes


def _specific_icd_codes(outcome: dict[str, Any] | None) -> set[str]:
    """Extract specific ICD codes without treating range endpoints as outcomes."""
    if not isinstance(outcome, dict) or not outcome.get("available", True):
        return set()
    codes: set[str] = set()
    for key in ("code", "parent_code"):
        value = outcome.get(key)
        if value:
            n = _norm_icd(str(value))
            if 3 <= len(n) <= 5:
                codes.add(n)
    text = _ICD_RANGE_RE.sub(" ", _outcome_text(outcome))
    for token in _ICD_RE.findall(text):
        codes.add(_norm_icd(token))
    return codes


def _cause_stack_specific_codes(
    cause: dict[str, Any] | None,
    detail: dict[str, Any] | None,
    deep: dict[str, Any] | None,
) -> set[str]:
    codes: set[str] = set()
    for outcome in (deep, detail, cause):
        codes.update(_specific_icd_codes(outcome))
    return codes


def _outcome_matches_trigger(outcome: dict[str, Any] | None, trigger: dict[str, Any]) -> bool:
    if not isinstance(outcome, dict) or not outcome.get("available", True):
        return False
    text = _outcome_text(outcome).casefold()
    for excluded in trigger.get("exclude_label_contains", []):
        if str(excluded).casefold() in text:
            return False
    # Only resolved/specific ICD codes may satisfy code/range triggers.
    # Range endpoints embedded in broad labels (for example the V01 and Y89
    # in "External causes ... (V01-Y89)") are classification bounds, not
    # observed outcomes; treating them as codes can spuriously match a much
    # narrower context such as road traffic.
    codes = _specific_icd_codes(outcome)
    exact = {_norm_icd(x) for x in trigger.get("icd_exact", [])}
    if codes & exact:
        return True
    for code in codes:
        if any(_icd3_in_range(code, spec) for spec in trigger.get("icd_ranges", [])):
            return True
    return any(str(piece).casefold() in text for piece in trigger.get("label_contains", []))


def cause_stack_matches_trigger(
    trigger: dict[str, Any],
    *,
    cause: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
    deep: dict[str, Any] | None = None,
) -> bool:
    """Match the most specific resolved outcome first.

    Detail/deep matches are preferred so a broad V01-V99 transport parent does
    not get mistaken for road traffic when the selected detail is water/air.
    """
    for outcome in (deep, detail):
        if _outcome_matches_trigger(outcome, trigger):
            return True
    # Cause may itself be a specific ICD outcome in some country/data paths.
    return _outcome_matches_trigger(cause, trigger)


class PlaceModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.contexts = dict(payload.get("contexts", {}))
        self.precedence = list(payload.get("precedence", self.contexts))

    @classmethod
    def from_path(cls, path: Path) -> "PlaceModel":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _country_key(country: str) -> str:
        value = str(country).strip().upper()
        return {"FI": "FI", "FIN": "FI", "FINLAND": "FI", "CA": "CA", "CAN": "CA", "CANADA": "CA"}.get(value, value)

    @staticmethod
    def _sex_key(sex: str) -> str:
        value = str(sex).strip().casefold()
        if value in {"m", "male", "men", "man"}:
            return "male"
        if value in {"f", "female", "women", "woman"}:
            return "female"
        return value

    def _resolve_distribution(
        self, context_id: str, *, country: str, sex: str, age: int | None = None
    ) -> dict[str, Any] | None:
        context = dict(self.contexts.get(context_id, {}))
        if not context:
            return None
        requested = self._country_key(country)
        model_key = dict(context.get("country_model_map", {})).get(requested)
        if not model_key:
            return None
        model = dict(context.get("models", {}).get(model_key, {}))
        if not model:
            return None
        profile_key = None
        cell = model
        profiles = model.get("profiles")
        if isinstance(profiles, dict):
            sex_key = self._sex_key(sex)
            sex_profile = sex_key if sex_key in profiles else "all" if "all" in profiles else None
            if sex_profile is None:
                return None
            profile_key = sex_profile
            cell = dict(profiles[sex_profile])

        age_groups = cell.get("age_groups")
        if isinstance(age_groups, list):
            if age is None:
                return None
            selected = None
            for candidate in age_groups:
                if not isinstance(candidate, dict):
                    continue
                lo = int(candidate.get("min_age", -10**9))
                hi = int(candidate.get("max_age", 10**9))
                if lo <= int(age) <= hi:
                    selected = dict(candidate)
                    break
            if selected is None:
                return None
            cell = selected
            profile_key = str(
                selected.get(
                    "profile_label",
                    f"{profile_key + ' ' if profile_key and profile_key != 'all' else ''}age {age}",
                )
            )

        raw = {str(k): float(v) for k, v in dict(cell.get("distribution", {})).items() if float(v) > 0}
        total = sum(raw.values())
        if total <= 0:
            return None
        return {
            "context_id": context_id,
            "context": context,
            "requested_country": requested,
            "model_country": model_key,
            "model_label": str(model.get("label", model_key)),
            "profile": profile_key,
            "distribution": {k: v / total for k, v in raw.items()},
            "provenance": str(cell.get("provenance", model.get("provenance", "evidence model"))),
            "model_status": str(cell.get("model_status", model.get("model_status", "evidence model"))),
            "source_period": str(cell.get("source_period", model.get("source_period", ""))),
        }

    def roll(
        self,
        context_id: str,
        *,
        country: str,
        sex: str,
        rng: random.Random,
        age: int | None = None,
        allowed_categories: set[str] | None = None,
        constraint_provenance: str = "",
        constraint_status: str = "",
    ) -> dict[str, Any]:
        resolved = self._resolve_distribution(context_id, country=country, sex=sex, age=age)
        if resolved is None:
            return {"available": False, "reason": f"no place model for {context_id}"}
        dist = dict(resolved["distribution"])
        if allowed_categories is not None:
            dist = {k: v for k, v in dist.items() if k in allowed_categories}
            total = sum(dist.values())
            if total <= 0:
                return {"available": False, "reason": f"no compatible place categories for {context_id}"}
            dist = {k: v / total for k, v in dist.items()}
        ids = list(dist)
        cumulative: list[float] = []
        running = 0.0
        for category_id in ids:
            running += dist[category_id]
            cumulative.append(running)
        u = rng.random()
        idx = bisect.bisect_right(cumulative, u)
        if idx >= len(ids):
            idx = len(ids) - 1
        category_id = ids[idx]
        context = resolved["context"]
        categories = dict(context.get("categories", {}))
        return {
            "available": True,
            "context_id": context_id,
            "semantic": str(context.get("semantic", "place")),
            "heading": str(context.get("heading", "PLACE")),
            "category": category_id,
            "label": str(categories.get(category_id, category_id.replace("_", " "))),
            "roll": u,
            "conditional_probability": dist[category_id],
            "requested_country": resolved["requested_country"],
            "model_country": resolved["model_country"],
            "model_label": resolved["model_label"],
            "profile": resolved["profile"],
            "fallback": False,
            "provenance": (
                f"{resolved['provenance']} Constraint: {constraint_provenance}"
                if constraint_provenance else resolved["provenance"]
            ),
            "model_status": constraint_status or resolved["model_status"],
            "source_period": resolved["source_period"],
            "constrained": allowed_categories is not None,
            "model_id": str(self.payload.get("model_id", "cause-place")),
        }

    def roll_for_cause_stack(
        self,
        *,
        country: str,
        sex: str,
        rng: random.Random,
        age: int | None = None,
        cause: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
        deep: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        for context_id in self.precedence:
            context = self.contexts.get(context_id, {})
            if not cause_stack_matches_trigger(dict(context.get("trigger", {})), cause=cause, detail=detail, deep=deep):
                continue
            resolved = self._resolve_distribution(context_id, country=country, sex=sex, age=age)
            if resolved is None:
                continue

            specific_codes = _cause_stack_specific_codes(cause, detail, deep)
            for constraint in context.get("icd_constraints", []):
                wanted = {_norm_icd(code) for code in constraint.get("icd_exact", [])}
                if not (specific_codes & wanted):
                    continue
                fixed = constraint.get("fixed")
                if isinstance(fixed, dict):
                    return {
                        "available": True,
                        "context_id": context_id,
                        "semantic": str(context.get("semantic", "place")),
                        "heading": str(context.get("heading", "PLACE")),
                        "category": str(fixed.get("category", "icd_resolved")),
                        "label": str(fixed.get("label", "ICD-resolved place")),
                        "roll": None,
                        "conditional_probability": 1.0,
                        "requested_country": resolved["requested_country"],
                        "model_country": resolved["model_country"],
                        "model_label": f"ICD-10 resolved setting | {resolved['model_label']}",
                        "profile": resolved["profile"],
                        "fallback": False,
                        "provenance": str(constraint.get("provenance", "ICD-10 resolved setting")),
                        "model_status": str(constraint.get("model_status", "ICD-resolved event setting")),
                        "source_period": resolved["source_period"],
                        "constrained": True,
                        "model_id": str(self.payload.get("model_id", "cause-place")),
                    }
                by_model = constraint.get("allowed_categories_by_model", {})
                allowed = set(by_model.get(resolved["model_country"], []))
                if allowed:
                    return self.roll(
                        context_id, country=country, sex=sex, rng=rng, age=age,
                        allowed_categories=allowed,
                        constraint_provenance=str(constraint.get("provenance", "")),
                        constraint_status=str(constraint.get("model_status", "")),
                    )
            return self.roll(context_id, country=country, sex=sex, rng=rng, age=age)
        return None
