"""Conditional context rolls for selected external-cause ICD outcomes.

These models are deliberately downstream of the existing mortality and cause
roulette.  They add broad, non-actionable context only (for example an X80
site type or an X41 drug class) and never alter annual mortality, cause
selection, detail selection, or seasonality.
"""

from __future__ import annotations

import bisect
import json
import random
import re
from pathlib import Path
from typing import Any

_ICD_TOKEN_RE = re.compile(r"(?<![A-Z0-9])([A-Z][0-9]{2}(?:[.]?[0-9])?)(?![A-Z0-9])", re.I)


def _norm_icd(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def outcome_has_icd(outcome: dict[str, Any] | None, code: str) -> bool:
    if not isinstance(outcome, dict) or not outcome.get("available", True):
        return False
    wanted = _norm_icd(code)
    for key in ("code", "parent_code"):
        value = outcome.get(key)
        if value and _norm_icd(str(value)) == wanted:
            return True
    for key in ("label", "parent_label", "classification"):
        text = str(outcome.get(key, ""))
        for token in _ICD_TOKEN_RE.findall(text):
            if _norm_icd(token) == wanted:
                return True
    return False


def cause_stack_has_icd(code: str, *outcomes: dict[str, Any] | None) -> bool:
    return any(outcome_has_icd(outcome, code) for outcome in outcomes)


class ExternalContextModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.contexts = dict(payload.get("contexts", {}))

    @classmethod
    def from_path(cls, path: Path) -> "ExternalContextModel":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _country_key(country: str) -> str:
        value = str(country).strip().upper()
        aliases = {
            "FI": "FI", "FIN": "FI", "FINLAND": "FI",
            "CA": "CA", "CAN": "CA", "CANADA": "CA",
        }
        return aliases.get(value, value)

    @staticmethod
    def _sex_key(sex: str) -> str:
        value = str(sex).strip().casefold()
        if value in {"m", "male", "men", "man"}:
            return "male"
        if value in {"f", "female", "women", "woman"}:
            return "female"
        return value

    def _resolve_distribution(
        self,
        context_id: str,
        *,
        country: str,
        sex: str,
    ) -> dict[str, Any] | None:
        context = dict(self.contexts.get(context_id, {}))
        if not context:
            return None
        requested = self._country_key(country)
        country_map = dict(context.get("country_model_map", {}))
        fallback_model = str(context.get("fallback_model", ""))
        model_key = str(country_map.get(requested, fallback_model))
        fallback = requested not in country_map or model_key == fallback_model and requested != model_key
        models = dict(context.get("models", {}))
        model = dict(models.get(model_key, {}))
        if not model:
            return None

        profile_key = None
        cell: dict[str, Any]
        profiles = model.get("profiles")
        if isinstance(profiles, dict):
            sex_key = self._sex_key(sex)
            if sex_key in profiles:
                profile_key = sex_key
            elif "all" in profiles:
                profile_key = "all"
            else:
                fallback = True
                model_key = fallback_model
                model = dict(models.get(model_key, {}))
                profiles = model.get("profiles")
                if not isinstance(profiles, dict):
                    return None
                profile_key = sex_key if sex_key in profiles else "all" if "all" in profiles else None
                if profile_key is None:
                    return None
            cell = dict(profiles[profile_key])
        else:
            cell = model

        raw = {str(k): float(v) for k, v in dict(cell.get("distribution", {})).items() if float(v) > 0}
        total = sum(raw.values())
        if total <= 0:
            return None
        distribution = {k: v / total for k, v in raw.items()}
        return {
            "context_id": context_id,
            "context": context,
            "requested_country": requested,
            "model_country": model_key,
            "model_label": str(model.get("label", model_key)),
            "profile": profile_key,
            "fallback": fallback,
            "distribution": distribution,
            "provenance": str(cell.get("provenance", model.get("provenance", "evidence model"))),
            "model_status": str(cell.get("model_status", model.get("model_status", "evidence model"))),
        }

    def roll(
        self,
        context_id: str,
        *,
        country: str,
        sex: str,
        rng: random.Random,
    ) -> dict[str, Any]:
        resolved = self._resolve_distribution(context_id, country=country, sex=sex)
        if resolved is None:
            return {"available": False, "reason": f"no model for {context_id}"}
        dist = resolved["distribution"]
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
            "heading": str(context.get("heading", context_id)),
            "compact_row": str(context.get("compact_row", context_id)),
            "category": category_id,
            "label": str(categories.get(category_id, category_id.replace("_", " "))),
            "roll": u,
            "conditional_probability": dist[category_id],
            "requested_country": resolved["requested_country"],
            "model_country": resolved["model_country"],
            "model_label": resolved["model_label"],
            "profile": resolved["profile"],
            "fallback": resolved["fallback"],
            "provenance": resolved["provenance"],
            "model_status": resolved["model_status"],
            "model_id": str(self.payload.get("model_id", "external-context")),
        }

    def roll_x80_location_for_cause_stack(
        self,
        *,
        country: str,
        sex: str,
        rng: random.Random,
        cause: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
        deep: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not cause_stack_has_icd("X80", cause, detail, deep):
            return None
        return self.roll("X80_LOCATION_TYPE", country=country, sex=sex, rng=rng)

    def roll_x41_drug_class_for_cause_stack(
        self,
        *,
        country: str,
        sex: str,
        rng: random.Random,
        cause: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
        deep: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not cause_stack_has_icd("X41", cause, detail, deep):
            return None
        return self.roll("X41_DRUG_CLASS", country=country, sex=sex, rng=rng)
