"""Modeled postmortem/pathway reconstruction downstream of a realized death.

This module never changes mortality or cause-of-death selection.  It consumes a
resolved cause stack and, when explicitly enabled, produces a clearly labelled
population-level *modeled* lead-up or associated-condition reconstruction.

Rules are intentionally sparse.  Unsupported causes return an explicit
fallback instead of receiving a medically plausible invented story.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_ICD_RE = re.compile(r"(?<![A-Z0-9])([A-Z][0-9]{2}(?:[.]?[0-9]{1,2})?)(?![A-Z0-9])", re.I)
_ICD_RANGE_RE = re.compile(r"([A-Z][0-9]{2})\s*[-–—]\s*([A-Z][0-9]{2})", re.I)
_DOCTORS = ("👩‍⚕️", "👨‍⚕️", "🧑‍⚕️")


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
    if not isinstance(outcome, dict) or not outcome.get("available", True):
        return set()
    codes: set[str] = set()
    for key in ("code", "parent_code"):
        value = outcome.get(key)
        if value:
            n = _norm_icd(str(value))
            if 3 <= len(n) <= 5:
                codes.add(n)
    text = " | ".join(str(outcome.get(k, "")) for k in ("label", "parent_label", "classification"))
    # A broad label such as V01-X59 must not make its endpoints look realized.
    text = _ICD_RANGE_RE.sub(" ", text)
    for token in _ICD_RE.findall(text):
        codes.add(_norm_icd(token))
    return codes


def _matches(outcome: dict[str, Any] | None, trigger: dict[str, Any]) -> bool:
    if not isinstance(outcome, dict) or not outcome.get("available", True):
        return False
    text = " | ".join(str(outcome.get(k, "")) for k in ("label", "parent_label", "classification")).casefold()
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


def _weighted_pick(items: list[dict[str, Any]], rng: Any) -> dict[str, Any] | None:
    rows = [(row, float(row.get("probability", 0.0))) for row in items]
    rows = [(row, p) for row, p in rows if p > 0.0]
    total = sum(p for _row, p in rows)
    if total <= 0.0:
        return None
    target = float(rng.random()) * total
    running = 0.0
    for row, p in rows:
        running += p
        if target < running:
            return dict(row)
    return dict(rows[-1][0])


class PostmortemPathwayModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.rules = list(payload.get("rules", []))
        self.model_id = str(payload.get("model_id", "postmortem-pathway-model"))

    @classmethod
    def from_path(cls, path: Path) -> "PostmortemPathwayModel":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def supports_country(self, country: str) -> bool:
        """Return whether this bundled model contains any rules for a country.

        This is deliberately separate from cause matching.  Callers use it to
        avoid presenting a Canadian doctor/fallback box for non-Canadian lives
        merely because the generic postmortem switch is enabled.
        """
        requested = str(country).strip().upper()
        for rule in self.rules:
            countries = {str(x).strip().upper() for x in rule.get("countries", [])}
            if not countries or requested in countries:
                return True
        return False

    def roll_for_cause_stack(
        self,
        *,
        country: str,
        sex: str,
        age: int,
        rng: Any,
        cause: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
        deep: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        requested_country = str(country).strip().upper()
        doctor = _DOCTORS[int(float(rng.random()) * len(_DOCTORS)) % len(_DOCTORS)]

        for rule in self.rules:
            countries = {str(x).strip().upper() for x in rule.get("countries", [])}
            if countries and requested_country not in countries:
                continue
            trigger = dict(rule.get("trigger", {}))
            matched_level = None
            for level, outcome in (("deep", deep), ("detail", detail), ("cause", cause)):
                if _matches(outcome, trigger):
                    matched_level = level
                    break
            if matched_level is None:
                continue

            kind = str(rule.get("kind", "evidence_summary"))
            result: dict[str, Any] = {
                "available": True,
                "modeled": True,
                "fallback": False,
                "doctor": doctor,
                "rule_id": str(rule.get("id", "pathway-rule")),
                "kind": kind,
                "matched_level": matched_level,
                "title": str(rule.get("title", "WHAT LIKELY HAPPENED?")),
                "model_id": self.model_id,
                "basis": str(rule.get("basis", "population-level modeled reconstruction")),
                "limitations": str(rule.get("limitations", "")),
                "provenance": list(rule.get("provenance", [])),
            }

            if kind == "two_stage_weighted":
                stages = []
                for stage in rule.get("stages", []):
                    chosen = _weighted_pick(list(stage.get("options", [])), rng)
                    if chosen is not None:
                        stages.append({
                            "stage": str(stage.get("stage", "event")),
                            "label": str(chosen.get("label", "unresolved")),
                            "probability": float(chosen.get("probability", 0.0)),
                        })
                result["stages"] = stages
                result["summary"] = " → ".join(str(x["label"]) for x in stages) or str(rule.get("summary", "Modeled pathway"))
                return result

            if kind == "marginal_associations":
                selected: list[dict[str, Any]] = []
                for item in rule.get("associations", []):
                    p = float(item.get("probability", 0.0))
                    if p > 0.0 and float(rng.random()) < p:
                        selected.append({
                            "label": str(item.get("label", "unresolved")),
                            "probability": p,
                        })
                result["associations"] = selected
                if selected:
                    result["summary"] = "; ".join(str(x["label"]) for x in selected)
                else:
                    result["summary"] = str(rule.get("none_selected", "No listed associated condition was selected in this marginal reconstruction."))
                return result

            steps = [str(x) for x in rule.get("steps", []) if str(x).strip()]
            result["steps"] = steps
            result["summary"] = " → ".join(steps) if steps else str(rule.get("summary", "Modeled evidence summary"))
            return result

        if requested_country == "CA":
            summary = "No cause-specific Canadian public-data pathway model is available for this result yet."
            basis = "unsupported Canadian cause family; no pathway invented"
        else:
            summary = "No country-specific public-data pathway model is available for this result yet."
            basis = "unsupported country/cause family; no pathway invented"
        return {
            "available": True,
            "modeled": False,
            "fallback": True,
            "doctor": doctor,
            "rule_id": "NO_SUPPORTED_PATHWAY",
            "kind": "fallback",
            "model_id": self.model_id,
            "title": "POSTMORTEM",
            "summary": summary,
            "basis": basis,
            "limitations": "The realized cause remains valid; only the modeled lead-up is unavailable.",
            "provenance": [],
        }


class PostmortemContextModel:
    """Sparse country-specific background context used when no pathway exists.

    Context is deliberately weaker than a pathway: it may report a population
    prevalence applicable to the player's age/sex stratum, but it never turns
    that prevalence into an inferred diagnosis or terminal sequence.
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.rules = list(payload.get("rules", []))
        self.model_id = str(payload.get("model_id", "postmortem-context-model"))

    @classmethod
    def from_path(cls, path: Path) -> "PostmortemContextModel":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def context_for(
        self,
        *,
        country: str,
        sex: str,
        age: int,
        rng: Any,
        cause: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
        deep: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        requested_country = str(country).strip().upper()
        sex_key = "male" if str(sex).strip().lower() in {"m", "male", "man"} else "female"
        for rule in self.rules:
            countries = {str(x).strip().upper() for x in rule.get("countries", [])}
            if countries and requested_country not in countries:
                continue
            if str(rule.get("kind", "")) != "age_sex_prevalence_context":
                continue
            trigger = dict(rule.get("trigger", {}))
            matched_level = None
            if trigger:
                for level, outcome in (("deep", deep), ("detail", detail), ("cause", cause)):
                    if _matches(outcome, trigger):
                        matched_level = level
                        break
                if matched_level is None:
                    continue
            if int(age) < int(rule.get("minimum_age", 0)):
                continue
            band = None
            for candidate in rule.get("age_bands", []):
                lo = int(candidate.get("min_age", 0))
                hi_raw = candidate.get("max_age")
                hi = None if hi_raw is None else int(hi_raw)
                if int(age) >= lo and (hi is None or int(age) <= hi):
                    band = dict(candidate)
                    break
            if band is None or sex_key not in band:
                continue
            prevalence = float(band[sex_key])
            doctor = _DOCTORS[int(float(rng.random()) * len(_DOCTORS)) % len(_DOCTORS)]
            lo = int(band["min_age"])
            hi_raw = band.get("max_age")
            age_band = f"{lo}+" if hi_raw is None else f"{lo}–{int(hi_raw)}"
            additional_benchmarks = []
            for benchmark in rule.get("additional_benchmarks", []):
                if int(age) < int(benchmark.get("minimum_age", 0)):
                    continue
                maximum = benchmark.get("maximum_age")
                if maximum is not None and int(age) > int(maximum):
                    continue
                additional_benchmarks.append(dict(benchmark))
            return {
                "available": True,
                "modeled": False,
                "contextual": True,
                "fallback": False,
                "presentation": "fi-dementia-prevalence-context",
                "doctor": doctor,
                "rule_id": str(rule.get("id", "FI_CONTEXT")),
                "kind": "age_sex_prevalence_context",
                "matched_level": matched_level,
                "model_id": self.model_id,
                "title": str(rule.get("title", "AGE-RELATED CONTEXT")),
                "condition": str(rule.get("condition", "condition")),
                "age_band": age_band,
                "sex": sex_key,
                "prevalence": prevalence,
                "summary": f"{prevalence * 100:.1f}% prevalence among {sex_key}s age {age_band}",
                "basis": str(rule.get("basis", "population prevalence context")),
                "limitations": str(rule.get("limitations", "Population context only; not an individual diagnosis.")),
                "provenance": list(rule.get("provenance", [])),
                "additional_benchmarks": additional_benchmarks,
            }
        return None
