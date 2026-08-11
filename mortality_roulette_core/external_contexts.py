"""Conditional context rolls for selected external-cause ICD outcomes.

These models are deliberately downstream of the existing mortality and cause
roulette.  They add broad, non-actionable context only (for example an X80
site type or poisoning-substance context) and never alter annual mortality,
cause selection, detail selection, or seasonality.
"""

from __future__ import annotations

import bisect
import json
import random
import re
from pathlib import Path
from typing import Any

_ICD_TOKEN_RE = re.compile(r"(?<![A-Z0-9])([A-Z][0-9]{2}(?:[.]?[0-9])?)(?![A-Z0-9])", re.I)
_ICD_RANGE_RE = re.compile(
    r"(?<![A-Z0-9])([A-Z][0-9]{2}(?:[.]?[0-9])?)\s*[-–—]\s*"
    r"([A-Z][0-9]{2}(?:[.]?[0-9])?)(?![A-Z0-9])",
    re.I,
)


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
        # A broad classification label may mention a code only as the endpoint
        # of an ICD range, e.g. ``V01-X44, X46-Y89``.  Range membership does
        # not mean that the realized outcome is the endpoint code itself.
        # Blank whole range expressions before looking for standalone tokens.
        standalone_text = _ICD_RANGE_RE.sub(" ", text)
        for token in _ICD_TOKEN_RE.findall(standalone_text):
            if _norm_icd(token) == wanted:
                return True
    return False


def cause_stack_has_icd(code: str, *outcomes: dict[str, Any] | None) -> bool:
    return any(outcome_has_icd(outcome, code) for outcome in outcomes)


def _outcome_road_user_role(outcome: dict[str, Any] | None) -> str | None:
    """Return a road-user role only from a realized detail/code, never a broad range.

    Finland's StatFin short-list detail rows use numeric codes 001-004.  WHO/
    Canadian detail rows may carry an exact V-code. Broad parent labels such as
    ``V01-X44`` are deliberately ignored.
    """
    if not isinstance(outcome, dict) or not outcome.get("available", True):
        return None

    code = str(outcome.get("code", "")).strip().upper()
    short_roles = {
        "001": "pedestrian",
        "002": "pedal_cyclist",
        "003": "motorcyclist",
        "004": "motor_vehicle_occupant",
    }
    if code in short_roles:
        return short_roles[code]

    # Some synthetic/older detail objects only preserved the StatFin short-list
    # identifier in the label.  Accept it only at the beginning of the realized
    # outcome label, not anywhere inside a parent classification range.
    label = str(outcome.get("label", "")).strip()
    m = re.match(r"^(00[1-4])(?:\D|$)", label)
    if m:
        return short_roles.get(m.group(1))

    # Exact ICD V-codes: use the first three characters (V01..V79). The
    # ``code`` field itself must be exact; never infer from a range in labels.
    norm = _norm_icd(code)
    if re.fullmatch(r"V\d{2}(?:\d)?", norm):
        n = int(norm[1:3])
        if 1 <= n <= 9:
            return "pedestrian"
        if 10 <= n <= 19:
            return "pedal_cyclist"
        if 20 <= n <= 39:
            return "motorcyclist"
        if 40 <= n <= 79:
            return "motor_vehicle_occupant"
    return None


def cause_stack_road_user_role(
    cause: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
    deep: dict[str, Any] | None = None,
) -> str | None:
    """Resolve road-user role from the most-specific realized outcome available."""
    for outcome in (deep, detail, cause):
        role = _outcome_road_user_role(outcome)
        if role is not None:
            return role
    return None


def _outcome_is_explicit_nontraffic_transport(outcome: dict[str, Any] | None) -> bool:
    """Return True only for a realized V-code explicitly labelled nontraffic."""
    if not isinstance(outcome, dict) or not outcome.get("available", True):
        return False
    code = str(outcome.get("code", "")).strip()
    specific_v = bool(code and _norm_icd(code).startswith("V"))
    if not specific_v:
        # Older/synthetic detail objects may preserve the exact V-code only in label.
        for token in _ICD_TOKEN_RE.findall(_ICD_RANGE_RE.sub(" ", str(outcome.get("label", "")))):
            if _norm_icd(token).startswith("V"):
                specific_v = True
                break
    if not specific_v:
        return False
    text = str(outcome.get("label", "")).casefold()
    if "unspecified whether traffic or nontraffic accident" in text:
        return False
    return "nontraffic accident" in text


def cause_stack_is_explicit_nontraffic_transport(
    cause: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
    deep: dict[str, Any] | None = None,
) -> bool:
    return any(_outcome_is_explicit_nontraffic_transport(outcome) for outcome in (deep, detail, cause))


def _outcome_is_railway_collision(outcome: dict[str, Any] | None) -> bool:
    if not isinstance(outcome, dict) or not outcome.get("available", True):
        return False
    text = str(outcome.get("label", "")).casefold()
    return ("railway train" in text or "railway vehicle" in text) and bool(
        str(outcome.get("code", "")).strip() or _ICD_TOKEN_RE.search(_ICD_RANGE_RE.sub(" ", text))
    )


def cause_stack_is_railway_collision(
    cause: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
    deep: dict[str, Any] | None = None,
) -> bool:
    return any(_outcome_is_railway_collision(outcome) for outcome in (deep, detail, cause))


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


    def roll_traffic_context_for_cause_stack(
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
        """Roll evidence-backed intoxication/impairment context after road deaths.

        The scope depends on the source. Finnish pedestrian/cyclist models are
        deceased-road-user intoxication distributions. Finnish motor-vehicle
        and Canadian models are crash-level/driver-factor references and must
        not be read as proof that the simulated decedent was the impaired driver.
        ``age`` and ``sex`` are carried into output for future finer cells but are
        not used to manufacture unsupported joint probabilities.
        """
        # The bundled impairment models describe road-traffic deaths/fatal
        # motor-vehicle collisions. Railway-train/vehicle collisions have a
        # different event denominator and receive no generic road impairment
        # roll; exact nontraffic V-codes are likewise outside the model.
        if cause_stack_is_railway_collision(cause, detail, deep):
            return None
        if cause_stack_is_explicit_nontraffic_transport(cause, detail, deep):
            return None

        role = cause_stack_road_user_role(cause, detail, deep)
        if role is None:
            return None
        country_key = self._country_key(country)

        if country_key == "FI":
            context_id = {
                "pedestrian": "FI_TRAFFIC_PEDESTRIAN_INTOXICATION",
                "pedal_cyclist": "FI_TRAFFIC_CYCLIST_INTOXICATION",
                "motorcyclist": "FI_FATAL_MOTOR_VEHICLE_IMPAIRMENT",
                "motor_vehicle_occupant": "FI_FATAL_MOTOR_VEHICLE_IMPAIRMENT",
            }.get(role)
        elif country_key == "CA":
            context_id = "CA_FATAL_COLLISION_IMPAIRMENT"
        else:
            context_id = None
        if context_id is None:
            return None

        outcome = self.roll(context_id, country=country_key, sex=sex, rng=rng)
        if not outcome.get("available"):
            return outcome
        context = dict(self.contexts.get(context_id, {}))
        normalized = dict(outcome)
        normalized.update({
            "heading": "CRASH CONTEXT",
            "road_user": role,
            "road_user_label": {
                "pedestrian": "Pedestrian",
                "pedal_cyclist": "Pedal cyclist",
                "motorcyclist": "Motorcyclist",
                "motor_vehicle_occupant": "Motor-vehicle occupant",
            }.get(role, role.replace("_", " ").title()),
            "impairment_label": str(outcome.get("label", "unresolved")),
            "scope": str(context.get("scope", "Crash-level context")),
            "age": int(age),
            "sex": self._sex_key(sex),
            "semantic": str(context.get("semantic", "traffic_impairment_context")),
        })
        return normalized

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

    def roll_x44_substance_count_for_cause_stack(
        self,
        *,
        country: str,
        sex: str,
        rng: random.Random,
        cause: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
        deep: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Roll broad X44 substance-count context where a country model exists.

        The bundled Canada model is an explicitly labelled proxy from national
        accidental acute-toxicity chart-review data. It does not invent exact
        molecules or a joint drug combination.
        """
        if not cause_stack_has_icd("X44", cause, detail, deep):
            return None
        if self._country_key(country) != "CA":
            return None
        return self.roll("X44_SUBSTANCE_COUNT_CONTEXT", country=country, sex=sex, rng=rng)

    def roll_substance_context_for_cause_stack(
        self,
        *,
        country: str,
        sex: str,
        x41_rng: random.Random,
        x44_rng: random.Random,
        cause: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
        deep: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Return one normalized poisoning-substance context for X40-X44.

        X41 preserves the legacy independent RNG stream and evidence-weighted
        class roll. X44 may receive a separate Canada-only count-context roll;
        elsewhere it is rendered conservatively from ICD semantics. X40/X42/X43
        are already broad agent classes in ICD and therefore need no extra roll.
        """
        stack = (cause, detail, deep)

        if cause_stack_has_icd("X41", *stack):
            outcome = self.roll_x41_drug_class_for_cause_stack(
                country=country, sex=sex, rng=x41_rng, cause=cause, detail=detail, deep=deep
            )
            if not outcome or not outcome.get("available"):
                return outcome
            normalized = dict(outcome)
            normalized.update({
                "heading": "SUBSTANCES",
                "agent_label": str(outcome.get("label", "unresolved")),
                "context_label": "Modeled broad drug class within ICD-10 X41",
                "semantic": "modeled_drug_class",
            })
            return normalized

        if cause_stack_has_icd("X44", *stack):
            rolled = self.roll_x44_substance_count_for_cause_stack(
                country=country, sex=sex, rng=x44_rng, cause=cause, detail=detail, deep=deep
            )
            if rolled and rolled.get("available"):
                category = str(rolled.get("category", ""))
                descriptions = {
                    "multiple_categories": (
                        "Multiple drugs from different categories",
                        "No single drug category identified as the main cause",
                    ),
                    "single_other_unspecified": (
                        "One other / unspecified drug",
                        "Specific drug not identified by the X44 underlying-cause code",
                    ),
                    "unknown_count": (
                        "Drug(s) not specified",
                        "Number of causal substances not identified in the reference data",
                    ),
                }
                agent, context = descriptions.get(
                    category,
                    (str(rolled.get("label", "Other / unspecified drug(s)")),
                     "Specific causal substance detail unavailable"),
                )
                normalized = dict(rolled)
                normalized.update({
                    "heading": "SUBSTANCES",
                    "agent_label": agent,
                    "context_label": context,
                    "semantic": "modeled_x44_substance_count",
                })
                return normalized

            return {
                "available": True,
                "context_id": "X44_ICD_CONTEXT",
                "heading": "SUBSTANCES",
                "agent_label": "Other / unspecified drug(s)",
                "context_label": (
                    "X44 can represent multiple drug categories when no single drug is "
                    "identified as most important"
                ),
                "requested_country": self._country_key(country),
                "model_country": "WHO",
                "model_label": "WHO ICD-10 mortality coding",
                "profile": None,
                "fallback": False,
                "provenance": (
                    "ICD-10 mortality coding guidance for multidrug poisonings; the X44 "
                    "underlying-cause code alone does not preserve the exact drug combination."
                ),
                "model_status": "ICD semantic context; exact agents unresolved",
                "model_id": str(self.payload.get("model_id", "external-context")),
                "semantic": "icd_semantic",
            }

        direct = {
            "X40": (
                "Non-opioid painkillers / fever-reducing / anti-inflammatory drugs",
                "Broad drug category fixed by ICD-10 X40",
            ),
            "X42": (
                "Narcotics / hallucinogens",
                "Broad drug category fixed by ICD-10 X42",
            ),
            "X43": (
                "Drugs acting on the autonomic nervous system",
                "Broad drug category fixed by ICD-10 X43",
            ),
        }
        for code, (agent, context) in direct.items():
            if cause_stack_has_icd(code, *stack):
                return {
                    "available": True,
                    "context_id": f"{code}_ICD_CONTEXT",
                    "heading": "SUBSTANCES",
                    "agent_label": agent,
                    "context_label": context,
                    "requested_country": self._country_key(country),
                    "model_country": "WHO",
                    "model_label": "WHO ICD-10",
                    "profile": None,
                    "fallback": False,
                    "provenance": f"Broad agent category is directly encoded by ICD-10 {code}.",
                    "model_status": "ICD-resolved broad substance category",
                    "model_id": str(self.payload.get("model_id", "external-context")),
                    "semantic": "icd_resolved",
                }
        return None
