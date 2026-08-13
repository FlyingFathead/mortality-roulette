#!/usr/bin/env python3
"""Build the project-authored code-indexed ICD annotation layer.

Runtime matching is code-only. This generator may inspect the bundled WHO title
catalog to precompute descriptive transport metadata, which is then frozen into
JSON and regression-tested.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "datasets" / "who" / "icd10" / "who_icd10_titles_2019.json"
OUT = ROOT / "datasets" / "who" / "icd10" / "icd10_annotations_v1.json"
EXACT_V = re.compile(r"^V(\d{2})(?:\.(\d+))?$")

GROUPS = [
    (1, 9, "pedestrian", "pedestrian"),
    (10, 19, "pedal_cyclist", "pedal cyclist"),
    (20, 29, "motorcycle_rider", "motorcycle rider"),
    (30, 39, "three_wheeled_vehicle_occupant", "occupant of a three-wheeled motor vehicle"),
    (40, 49, "car_occupant", "car occupant"),
    (50, 59, "pickup_van_occupant", "occupant of a pick-up truck or van"),
    (60, 69, "heavy_transport_occupant", "occupant of a heavy transport vehicle"),
    (70, 79, "bus_occupant", "bus occupant"),
    (80, 89, "other_land_transport", "person involved in another land-transport event"),
    (90, 94, "water_transport", "person involved in water transport"),
    (95, 97, "air_space_transport", "person involved in air or space transport"),
    (98, 99, "other_transport", "person involved in a transport accident"),
]

COUNTERPART = {
    0: "a pedestrian or animal",
    1: "a pedal cycle",
    2: "a two- or three-wheeled motor vehicle",
    3: "a car, pick-up truck or van",
    4: "a heavy transport vehicle or bus",
    5: "a railway train or railway vehicle",
    6: "another nonmotor vehicle",
    7: "a fixed or stationary object",
}
PED_COUNTERPART = {
    1: "a pedal cycle",
    2: "a two- or three-wheeled motor vehicle",
    3: "a car, pick-up truck or van",
    4: "a heavy transport vehicle or bus",
    5: "a railway train or railway vehicle",
    6: "another nonmotor vehicle",
}
ROLE_10_29 = {0:"driver",1:"passenger",2:"unspecified rider",3:"boarding or alighting",4:"driver",5:"passenger",9:"unspecified rider"}
TRAFFIC_10_29 = {0:"nontraffic",1:"nontraffic",2:"nontraffic",3:"unspecified",4:"traffic",5:"traffic",9:"traffic"}
ROLE_30_79 = {0:"driver",1:"passenger",2:"person on outside of vehicle",3:"unspecified occupant",4:"boarding or alighting",5:"driver",6:"passenger",7:"person on outside of vehicle",9:"unspecified occupant"}
TRAFFIC_30_79 = {0:"nontraffic",1:"nontraffic",2:"nontraffic",3:"nontraffic",4:"unspecified",5:"traffic",6:"traffic",7:"traffic",9:"traffic"}


def group_for(n: int):
    for lo, hi, key, label in GROUPS:
        if lo <= n <= hi:
            return key, label
    raise ValueError(n)


def title_derived_status(title: str) -> str:
    low = title.casefold()
    if "nontraffic" in low:
        return "nontraffic"
    if "traffic accident" in low or "(traffic)" in low or low.endswith(", traffic"):
        return "traffic"
    return "unspecified"


def title_derived_role(title: str) -> str | None:
    low = title.casefold()
    for needle, role in [
        ("driver ", "driver"), ("passenger ", "passenger"),
        ("person on outside", "person on outside of vehicle"),
        ("boarding or alighting", "boarding or alighting"),
        ("parachutist", "parachutist"), ("person on ground", "person on ground"),
    ]:
        if needle in low:
            return role
    return None


def build_transport(code: str, title: str, n: int, suffix: str | None) -> dict:
    group, group_label = group_for(n)
    role = None
    traffic = "unspecified"
    event_type = "transport_event"
    counterpart = None
    template_id = "transport_generic"

    digit = n % 10
    sd = int(suffix) if suffix and suffix.isdigit() and len(suffix) == 1 else None
    if 1 <= n <= 9:
        role = "pedestrian"
        traffic = title_derived_status(title)
        counterpart = PED_COUNTERPART.get(digit)
        event_type = "collision" if counterpart else "other_or_unspecified_transport"
        template_id = "land_collision" if counterpart else "land_transport_generic"
    elif 10 <= n <= 79:
        if 10 <= n <= 29 and sd is not None:
            role = ROLE_10_29.get(sd)
            traffic = TRAFFIC_10_29.get(sd, "unspecified")
        elif 30 <= n <= 79 and sd is not None:
            role = ROLE_30_79.get(sd)
            traffic = TRAFFIC_30_79.get(sd, "unspecified")
        if digit <= 7:
            counterpart = COUNTERPART[digit]
            event_type = "collision"
            template_id = "land_collision"
        elif digit == 8:
            event_type = "noncollision"
            template_id = "land_noncollision"
        else:
            event_type = "other_or_unspecified_transport"
            template_id = "land_transport_generic"
    elif 80 <= n <= 89:
        role = title_derived_role(title)
        traffic = title_derived_status(title)
        low = title.casefold()
        if "collision" in low:
            event_type, template_id = "collision", "land_collision_official_detail"
        elif "noncollision" in low or "fall from" in low or "thrown from" in low:
            event_type, template_id = "noncollision", "land_noncollision_official_detail"
        else:
            template_id = "land_transport_official_detail"
    elif 90 <= n <= 94:
        event_type = "water_transport"
        template_id = "water_transport_official_detail"
    elif 95 <= n <= 97:
        role = title_derived_role(title)
        event_type = "air_space_transport"
        template_id = "air_transport_official_detail"

    return {
        "group": group,
        "group_label": group_label,
        "role": role,
        "traffic_status": traffic,
        "event_type": event_type,
        "counterpart": counterpart,
        "template_id": template_id,
    }


def main() -> None:
    titles = json.loads(SRC.read_text(encoding="utf-8"))["codes"]
    codes: dict[str, dict] = {}
    for code, title in titles.items():
        m = EXACT_V.fullmatch(code)
        if not m:
            continue
        n = int(m.group(1))
        if not 1 <= n <= 99:
            continue
        codes[code] = {
            "scope": {"countries": "all"},
            "genres": ["transport"],
            "tags": ["transport_accident"],
            "transport": build_transport(code, str(title), n, m.group(2)),
        }

    # First non-transport genres use the same code-indexed infrastructure.
    def ann(code: str, genres: list[str], tags: list[str], explanation: str) -> None:
        row = codes.setdefault(code, {})
        row.setdefault("scope", {"countries": "all"})
        row["genres"] = list(dict.fromkeys([*row.get("genres", []), *genres]))
        row["tags"] = list(dict.fromkeys([*row.get("tags", []), *tags]))
        row["plain_language"] = explanation

    ann("F10", ["alcohol", "mental_behavioural"], ["direct_alcohol_attribution"],
        "Alcohol use is part of this diagnostic family itself; this is not merely a statistical alcohol-risk association.")
    ann("K70", ["alcohol", "liver"], ["direct_alcohol_attribution"],
        "Alcohol is part of this liver-disease diagnosis family itself.")
    ann("G31.2", ["alcohol", "neurodegeneration", "nervous_system"], ["direct_alcohol_attribution"],
        "The diagnosis itself attributes degeneration of the nervous system to alcohol.")
    ann("G40.51", ["alcohol", "neurology"], ["direct_alcohol_attribution"],
        "This Finnish detailed mortality code identifies epilepsy attributed to alcohol.")
    ann("G62.1", ["alcohol", "neurology"], ["direct_alcohol_attribution"],
        "The diagnosis itself identifies alcoholic polyneuropathy.")
    ann("G72.1", ["alcohol", "muscle"], ["direct_alcohol_attribution"],
        "The diagnosis itself identifies alcoholic myopathy.")
    ann("I42.6", ["alcohol", "cardiovascular"], ["direct_alcohol_attribution"],
        "The diagnosis itself identifies alcoholic cardiomyopathy.")
    ann("K29.2", ["alcohol", "digestive"], ["direct_alcohol_attribution"],
        "The diagnosis itself identifies alcoholic gastritis.")
    ann("K85.2", ["alcohol", "pancreas"], ["direct_alcohol_attribution"],
        "The diagnosis itself identifies alcohol-induced acute pancreatitis.")
    ann("K86.0", ["alcohol", "pancreas"], ["direct_alcohol_attribution"],
        "The diagnosis itself identifies alcohol-induced chronic pancreatitis.")
    ann("X45", ["alcohol", "poisoning", "external_cause"], ["direct_alcohol_attribution"],
        "The external-cause code itself identifies accidental poisoning by or exposure to alcohol.")

    # Dementia/Alzheimer state is established by these realized ICD families.
    # These tags are classification semantics, not population-probability estimates.
    ann("F00", ["dementia", "alzheimer", "mental_behavioural"],
        ["dementia_condition", "alzheimer_condition"],
        "The realized ICD family identifies dementia in Alzheimer disease.")
    ann("F01", ["dementia", "vascular", "mental_behavioural"],
        ["dementia_condition"],
        "The realized ICD family identifies vascular dementia.")
    ann("F02", ["dementia", "mental_behavioural"],
        ["dementia_condition"],
        "The realized ICD family identifies dementia in another disease classified elsewhere.")
    ann("F03", ["dementia", "mental_behavioural"],
        ["dementia_condition"],
        "The realized ICD family identifies unspecified dementia.")
    ann("G30", ["dementia", "alzheimer", "neurodegeneration", "nervous_system"],
        ["dementia_condition", "alzheimer_condition"],
        "The realized ICD family identifies Alzheimer disease; dementia/Alzheimer state is therefore present in the simulated death record rather than inferred from prevalence.")

    # K70 children inherit direct alcohol attribution from K70. Their own plain-language
    # explanations preserve the exact organ/pathology distinction while remaining code-first.
    k70_explanations = {
        "K70.0": "The realized ICD code identifies alcoholic fatty liver.",
        "K70.1": "The realized ICD code identifies alcoholic hepatitis.",
        "K70.2": "The realized ICD code identifies alcoholic fibrosis or sclerosis of the liver.",
        "K70.3": "The realized ICD code identifies alcoholic cirrhosis of the liver.",
        "K70.4": "The realized ICD code identifies alcoholic hepatic failure.",
        "K70.9": "The realized ICD code identifies alcoholic liver disease without a more specific K70 subtype.",
    }
    for code, explanation in k70_explanations.items():
        ann(code, ["alcohol", "liver"], ["direct_alcohol_attribution"], explanation)

    payload = {
        "schema": 1,
        "model_id": "mr-icd10-annotations-v1",
        "classification": "WHO ICD-10 2019 title backbone + project-authored code annotations",
        "runtime_matching": "exact normalized ICD code, then explicit 3-character parent inheritance; optional scope metadata; no runtime keyword classification",
        "transport_entry_count": sum(1 for row in codes.values() if "transport" in row.get("genres", [])),
        "codes": dict(sorted(codes.items())),
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {payload['transport_entry_count']} transport entries, {len(codes)} annotated codes total")


if __name__ == "__main__":
    main()
