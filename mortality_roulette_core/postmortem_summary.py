"""Generic factual postmortem composition from already-realized simulation state.

This layer is deliberately downstream-only. It does not roll mortality, causes,
places, crash context, substances, or seasonality. It translates those already-
resolved fields into a compact factual narrative, then exposes code-indexed ICD
knowledge for optional specialist enrichments.

Runtime classification is code-first. Text may be displayed, but title keywords
are never used to decide a medical genre or attribution.
"""
from __future__ import annotations

import re
from typing import Any

from .icd_knowledge import IcdKnowledgeBase, format_icd_code, normalize_icd_code

_ICD_TOKEN_RE = re.compile(r"(?<![A-Z0-9])([A-Z][0-9]{2}(?:[.]?[A-Z0-9]{1,2})?)(?![A-Z0-9])", re.I)
_ICD_RANGE_RE = re.compile(r"[A-Z][0-9]{2}\s*[-–—]\s*[A-Z][0-9]{2}", re.I)


def _sex_word(sex: str) -> str:
    return "male" if str(sex).strip().lower() in {"m", "male", "man"} else "female"


def _available(outcome: dict[str, Any] | None) -> bool:
    return isinstance(outcome, dict) and bool(outcome.get("available", True))


def _exact_code_from_outcome(outcome: dict[str, Any] | None) -> str:
    """Return one exact ICD code from an outcome, never a broad range endpoint."""
    if not _available(outcome):
        return ""
    assert outcome is not None
    raw = str(outcome.get("code", "")).strip()
    norm = normalize_icd_code(raw)
    if norm:
        return norm

    # Some legacy/public-detail outcomes carry the exact code only in the label.
    # Removing ranges before tokenization prevents V40-V79 from becoming a fake V40.
    text = " | ".join(str(outcome.get(k, "")) for k in ("label", "parent_label", "classification"))
    text = _ICD_RANGE_RE.sub(" ", text)
    match = _ICD_TOKEN_RE.search(text)
    return normalize_icd_code(match.group(1)) if match else ""


def realized_icd(
    *,
    cause: dict[str, Any] | None,
    detail: dict[str, Any] | None,
    deep: dict[str, Any] | None,
) -> tuple[str, str, dict[str, Any] | None]:
    """Return deepest exact ICD code + level + source outcome when available."""
    for level, outcome in (("deep", deep), ("detail", detail), ("cause", cause)):
        code = _exact_code_from_outcome(outcome)
        if code:
            return code, level, outcome
    return "", "", None


def _display_label(outcome: dict[str, Any] | None) -> str:
    if not _available(outcome):
        return ""
    assert outcome is not None
    return str(outcome.get("label", outcome.get("classification", ""))).strip()


def _transport_sentence(age: int, sex: str, code: str, row: dict[str, Any]) -> list[str]:
    title = str(row.get("title", "")).strip()
    transport = dict(row.get("transport", {}))
    group = str(transport.get("group_label", "person involved in a transport accident")).strip()
    role = str(transport.get("role", "") or "").strip()
    event_type = str(transport.get("event_type", "transport_event")).strip()
    counterpart = str(transport.get("counterpart", "") or "").strip()
    traffic_status = str(transport.get("traffic_status", "unspecified")).strip()
    template_id = str(transport.get("template_id", "transport_generic")).strip()

    subject = f"This {int(age)}-year-old {_sex_word(sex)} died in a fatal transport accident."
    lines = [subject]

    formatted = format_icd_code(code)
    if template_id == "land_collision" and counterpart:
        if role:
            detail = f"ICD-10 {formatted} identifies the decedent as {group} ({role}) in a collision with {counterpart}."
        else:
            detail = f"ICD-10 {formatted} identifies the decedent as {group} in a collision with {counterpart}."
        lines.append(detail)
    elif template_id == "land_noncollision":
        qualifier = f" ({role})" if role else ""
        lines.append(f"ICD-10 {formatted} identifies the decedent as {group}{qualifier} in a non-collision transport accident.")
    elif title:
        lines.append(f"The recorded ICD-10 detail was {formatted}: {title}.")
    else:
        lines.append(f"The recorded ICD-10 detail was {formatted} ({group}).")

    if traffic_status == "traffic":
        lines.append("The ICD code classifies this as a traffic accident.")
    elif traffic_status == "nontraffic":
        lines.append("The ICD code classifies this as a nontraffic accident.")
    elif template_id in {"land_transport_generic", "transport_generic"}:
        lines.append("The ICD code does not resolve the crash configuration more specifically.")
    return lines


def compose_realized_postmortem(
    *,
    country: str,
    sex: str,
    age: int,
    knowledge: IcdKnowledgeBase,
    cause: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
    deep: dict[str, Any] | None = None,
    place: dict[str, Any] | None = None,
    traffic_context: dict[str, Any] | None = None,
    substance_context: dict[str, Any] | None = None,
    suicide_reason: dict[str, Any] | None = None,
    seasonal: dict[str, Any] | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """Compose factual narration from fields the simulator has already resolved."""
    code, matched_level, selected = realized_icd(cause=cause, detail=detail, deep=deep)
    annotation = (
        knowledge.lookup(code, country=country, region=region, sex=sex, age=age)
        if code
        else None
    )
    lines: list[str] = []

    if annotation and "transport" in set(annotation.get("genres", [])):
        lines.extend(_transport_sentence(age, sex, code, annotation))
    else:
        label = _display_label(selected)
        if code:
            title = str((annotation or {}).get("title") or knowledge.title(code) or "").strip()
            rendered = f"{format_icd_code(code)} {title}".strip()
            if not title and label:
                rendered = label
            lines.append(
                f"This {int(age)}-year-old {_sex_word(sex)} died with the realized cause-of-death detail {rendered}."
            )
        else:
            # Public sources sometimes resolve only a broad/range detail. It is still
            # a realized simulation fact and can be narrated without pretending that
            # an exact ICD leaf was observed.
            broad = _display_label(detail) or _display_label(cause)
            if broad:
                lines.append(
                    f"This {int(age)}-year-old {_sex_word(sex)} died with the realized cause-of-death classification: {broad}."
                )

    if _available(place):
        assert place is not None
        place_label = str(place.get("label", "")).strip()
        if place_label:
            lines.append(f"The modeled place roll selected {place_label}.")

    if _available(traffic_context):
        assert traffic_context is not None
        road_user = str(traffic_context.get("road_user_label", "")).strip()
        impairment = str(traffic_context.get("impairment_label", traffic_context.get("label", ""))).strip()
        if road_user:
            lines.append(f"The crash-context model classified the road user as {road_user}.")
        if impairment:
            lines.append(f"Its impairment-context roll selected: {impairment}.")
        scope = str(traffic_context.get("scope", "")).strip()
        if scope:
            lines.append(f"Crash-context scope: {scope}")

    if _available(substance_context):
        assert substance_context is not None
        agent = str(substance_context.get("agent_label", substance_context.get("label", ""))).strip()
        context_label = str(substance_context.get("context_label", "")).strip()
        if agent:
            if context_label:
                lines.append(f"The substance-context roll selected {agent} ({context_label}).")
            else:
                lines.append(f"The substance-context roll selected {agent}.")

    if _available(suicide_reason):
        assert suicide_reason is not None
        reason = str(suicide_reason.get("label", "")).strip()
        if reason:
            lines.append(
                f"The separate statistical-reason roll selected {reason}; this is modeled context, not a proven individual motive."
            )

    if _available(seasonal):
        assert seasonal is not None
        month = str(seasonal.get("month_name", "")).strip()
        if month:
            lines.append(f"The timing roll placed the death in {month}.")

    state: dict[str, str] = {}
    tags = set(str(x) for x in (annotation or {}).get("tags", []))
    if "dementia_condition" in tags:
        state["dementia"] = "present"
    if "alzheimer_condition" in tags:
        state["alzheimer"] = "present"

    plain_language = str((annotation or {}).get("plain_language", "")).strip()
    return {
        "available": bool(lines),
        "lines": lines,
        "code": format_icd_code(code) if code else "",
        "matched_level": matched_level,
        "icd": annotation,
        "genres": list((annotation or {}).get("genres", [])),
        "tags": list((annotation or {}).get("tags", [])),
        "plain_language": plain_language,
        "condition_state": state,
    }
