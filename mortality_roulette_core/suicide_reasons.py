"""Conditional statistical-reason roll for suicide deaths.

The model is intentionally downstream of the existing underlying-cause roll.  It
never changes annual mortality, suicide incidence, ICD selection, or seasonality.
When the resolved cause is suicide, it samples one evidence-weighted salient
context from the bundled country/sex/age distribution.

The source literature does not provide a modern nationwide mutually-exclusive
"one motive per suicide" table for every cell.  The bundled dataset therefore
labels every cell by evidence/model provenance, and the returned probability is
always a *model-normalized conditional roll probability*, not proof of an
individual person's motive.
"""

from __future__ import annotations

import bisect
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_ICD_TOKEN_RE = re.compile(r"(?<![A-Z0-9])([A-Z][0-9]{2}(?:[.]?[0-9])?)(?![A-Z0-9])", re.I)


def _normalise_icd(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(code).upper())


def is_suicide_icd(code: str) -> bool:
    """Return True for ICD-10 intentional self-harm X60-X84 or Y87.0."""
    norm = _normalise_icd(code)
    if norm == "Y870":
        return True
    return len(norm) >= 3 and norm[0] == "X" and norm[1:3].isdigit() and 60 <= int(norm[1:3]) <= 84


def outcome_is_suicide(outcome: dict[str, Any] | None) -> bool:
    if not isinstance(outcome, dict) or not outcome.get("available", True):
        return False

    for key in ("code", "parent_code"):
        value = outcome.get(key)
        if value and is_suicide_icd(str(value)):
            return True

    for key in ("label", "parent_label", "classification"):
        text = str(outcome.get(key, ""))
        folded = text.casefold()
        if "suicide" in folded and ("x60" in folded or "intentional self-harm" in folded):
            return True
        for token in _ICD_TOKEN_RE.findall(text):
            if is_suicide_icd(token):
                return True
    return False


def cause_stack_is_suicide(*outcomes: dict[str, Any] | None) -> bool:
    return any(outcome_is_suicide(outcome) for outcome in outcomes)


@dataclass(frozen=True)
class SuicideReasonProfile:
    requested_country: str
    model_country: str
    model_label: str
    sex: str
    age_group: str
    fallback: bool
    provenance: str
    distribution: dict[str, float]


class SuicideReasonModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.categories = dict(payload.get("categories", {}))
        self.age_groups = list(payload.get("age_groups", []))
        self.models = dict(payload.get("models", {}))
        self.fallback_model = str(payload.get("fallback_model", "FI_CA_REFERENCE"))
        if self.fallback_model not in self.models:
            raise ValueError(f"suicide-reason fallback model {self.fallback_model!r} missing")

    @classmethod
    def from_path(cls, path: Path) -> "SuicideReasonModel":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def age_group_for(self, age: int) -> str | None:
        for row in self.age_groups:
            lo = int(row["min_age"])
            hi = row.get("max_age")
            if age >= lo and (hi is None or age <= int(hi)):
                return str(row["id"])
        return None

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

    def resolve(self, *, country: str, sex: str, age: int) -> SuicideReasonProfile | None:
        age_group = self.age_group_for(age)
        if age_group is None:
            return None
        requested = self._country_key(country)
        sex_key = self._sex_key(sex)

        model_key = requested if requested in self.models else self.fallback_model
        fallback = model_key != requested
        model = self.models[model_key]
        sex_rows = dict(model.get("profiles", {})).get(sex_key)
        if not isinstance(sex_rows, dict) or age_group not in sex_rows:
            model_key = self.fallback_model
            fallback = True
            model = self.models[model_key]
            sex_rows = dict(model.get("profiles", {})).get(sex_key)
        if not isinstance(sex_rows, dict) or age_group not in sex_rows:
            return None

        cell = dict(sex_rows[age_group])
        raw = {str(k): float(v) for k, v in dict(cell.get("distribution", {})).items() if float(v) > 0.0}
        total = sum(raw.values())
        if total <= 0:
            return None
        distribution = {k: v / total for k, v in raw.items()}
        return SuicideReasonProfile(
            requested_country=requested,
            model_country=model_key,
            model_label=str(model.get("label", model_key)),
            sex=sex_key,
            age_group=age_group,
            fallback=fallback,
            provenance=str(cell.get("provenance", model.get("provenance", "evidence-weighted model"))),
            distribution=distribution,
        )

    def roll(self, *, country: str, sex: str, age: int, rng: random.Random) -> dict[str, Any]:
        profile = self.resolve(country=country, sex=sex, age=age)
        if profile is None:
            return {"available": False, "reason": "no suicide-reason model for requested age/sex"}

        ids = list(profile.distribution)
        cumulative: list[float] = []
        running = 0.0
        for category_id in ids:
            running += profile.distribution[category_id]
            cumulative.append(running)
        u = rng.random()
        index = bisect.bisect_right(cumulative, u)
        if index >= len(ids):
            index = len(ids) - 1
        category_id = ids[index]
        category = dict(self.categories.get(category_id, {}))
        return {
            "available": True,
            "category": category_id,
            "label": str(category.get("label", category_id.replace("_", " "))),
            "conditional_probability": profile.distribution[category_id],
            "requested_country": profile.requested_country,
            "model_country": profile.model_country,
            "model_label": profile.model_label,
            "sex": profile.sex,
            "age_group": profile.age_group,
            "fallback": profile.fallback,
            "provenance": profile.provenance,
            "model_id": str(self.payload.get("model_id", "suicide-reasons")),
        }

    def roll_for_cause_stack(
        self,
        *,
        country: str,
        sex: str,
        age: int,
        rng: random.Random,
        cause: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
        deep: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not cause_stack_is_suicide(cause, detail, deep):
            return None
        return self.roll(country=country, sex=sex, age=age, rng=rng)
