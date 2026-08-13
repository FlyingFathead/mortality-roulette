"""Code-first ICD-10 knowledge/annotation resolver for Mortality Roulette.

The WHO title catalog remains the authoritative code/title backbone. Project-authored
annotations are keyed by ICD code and may inherit only from explicit parents (for
example K70 -> K70.1). Runtime classification never uses title keywords.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_EXACT_RE = re.compile(r"^[A-Z][0-9]{2}(?:\.?[A-Z0-9]{1,2})?$", re.I)


def normalize_icd_code(value: str) -> str:
    raw = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    if len(raw) < 3 or not raw[0].isalpha() or not raw[1:3].isdigit():
        return ""
    return raw


def format_icd_code(value: str) -> str:
    code = normalize_icd_code(value)
    if len(code) <= 3:
        return code
    return f"{code[:3]}.{code[3:]}"


class IcdKnowledgeBase:
    def __init__(self, title_payload: dict[str, Any], annotation_payload: dict[str, Any]) -> None:
        raw_titles = dict(title_payload.get("codes", {}))
        self.titles: dict[str, str] = {}
        for code, title in raw_titles.items():
            if _EXACT_RE.fullmatch(str(code)):
                norm = normalize_icd_code(str(code))
                if norm:
                    self.titles[norm] = str(title)
        self.annotations: dict[str, dict[str, Any]] = {}
        for code, row in dict(annotation_payload.get("codes", {})).items():
            norm = normalize_icd_code(str(code))
            if norm and isinstance(row, dict):
                self.annotations[norm] = dict(row)
        self.model_id = str(annotation_payload.get("model_id", "icd10-annotations"))

    @classmethod
    def from_paths(cls, title_path: Path, annotation_path: Path) -> "IcdKnowledgeBase":
        return cls(
            json.loads(title_path.read_text(encoding="utf-8")),
            json.loads(annotation_path.read_text(encoding="utf-8")),
        )

    def title(self, code: str) -> str | None:
        norm = normalize_icd_code(code)
        if not norm:
            return None
        return self.titles.get(norm) or (self.titles.get(norm[:3]) if len(norm) > 3 else None)

    @staticmethod
    def _scope_matches(
        scope: dict[str, Any] | None, *, country: str | None, region: str | None, sex: str | None, age: int | None
    ) -> bool:
        if not scope:
            return True
        countries = scope.get("countries", "all")
        if countries != "all":
            allowed = {str(x).strip().upper() for x in countries}
            if country is not None and str(country).strip().upper() not in allowed:
                return False
        excluded = {str(x).strip().upper() for x in scope.get("exclude_countries", [])}
        if country is not None and str(country).strip().upper() in excluded:
            return False
        regions = scope.get("regions", "all")
        if regions != "all" and region is not None:
            if str(region).strip().upper() not in {str(x).strip().upper() for x in regions}:
                return False
        sexes = scope.get("sex", "all")
        if sexes != "all" and sex is not None:
            key = "male" if str(sex).strip().lower() in {"m", "male", "man"} else "female"
            if key not in {str(x).strip().lower() for x in sexes}:
                return False
        if age is not None:
            if scope.get("age_min") is not None and int(age) < int(scope["age_min"]):
                return False
            if scope.get("age_max") is not None and int(age) > int(scope["age_max"]):
                return False
        return True

    def lookup(
        self, code: str, *, country: str | None = None, region: str | None = None,
        sex: str | None = None, age: int | None = None
    ) -> dict[str, Any] | None:
        norm = normalize_icd_code(code)
        if not norm:
            return None
        exact = self.annotations.get(norm)
        parent = self.annotations.get(norm[:3]) if len(norm) > 3 else None
        if exact is None and parent is None and norm not in self.titles:
            return None
        merged: dict[str, Any] = {}
        inherited_from: list[str] = []
        if parent is not None and self._scope_matches(
            parent.get("scope"), country=country, region=region, sex=sex, age=age
        ):
            merged.update(parent)
            inherited_from.append(format_icd_code(norm[:3]))
        if exact is not None and self._scope_matches(
            exact.get("scope"), country=country, region=region, sex=sex, age=age
        ):
            # merge nested dictionaries one level so a child can override a transport field
            for key, value in exact.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    nested = dict(merged[key])
                    nested.update(value)
                    merged[key] = nested
                else:
                    merged[key] = value
            inherited_from.append(format_icd_code(norm))

        # Scoped enrichment blocks are optional and never suppress universal code/title lookup.
        enrichments: list[dict[str, Any]] = []
        for source in (parent, exact):
            if not isinstance(source, dict):
                continue
            for item in source.get("enrichments", []):
                if isinstance(item, dict) and self._scope_matches(
                    item.get("scope"), country=country, region=region, sex=sex, age=age
                ):
                    enrichments.append(dict(item))
        if enrichments:
            merged["enrichments"] = enrichments
        merged["code"] = format_icd_code(norm)
        merged["normalized_code"] = norm
        merged["title"] = self.titles.get(norm) or self.titles.get(norm[:3])
        merged["parent_code"] = format_icd_code(norm[:3]) if len(norm) > 3 else None
        merged["parent_title"] = self.titles.get(norm[:3]) if len(norm) > 3 else None
        merged["annotation_sources"] = inherited_from
        return merged

    def has_tag(self, code: str, tag: str) -> bool:
        row = self.lookup(code)
        if not row:
            return False
        return str(tag) in {str(x) for x in row.get("tags", [])}

    def genres(self, code: str) -> tuple[str, ...]:
        row = self.lookup(code)
        if not row:
            return ()
        return tuple(str(x) for x in row.get("genres", []))
