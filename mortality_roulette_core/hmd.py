"""Optional Human Mortality Database (HMD) local archive reader.

Mortality Roulette does not download or bundle HMD country archives.  This
module reads the HMD-created 1x1 period life tables from either an original
country ZIP (preferred) or an extracted country tree supplied by the user.
It intentionally ignores InputDB and every other archive member.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


HMD_OPEN_AGE = 110
HMD_COUNTRY_NAMES = {
    "FIN": "Finland",
    "CAN": "Canada",
    "USA": "United States",
}
HMD_COUNTRY_PAGES = {
    "FIN": "https://www.mortality.org/Country/Country?cntr=FIN",
    "CAN": "https://www.mortality.org/Country/Country?cntr=CAN",
    "USA": "https://www.mortality.org/Country/Country?cntr=USA",
}


class HmdDataError(RuntimeError):
    """Raised when an optional HMD source cannot be located or parsed."""


@dataclass(frozen=True)
class HmdPeriodLifeTable:
    country_code: str
    source: str
    data: dict[str, dict[int, dict[int, float]]]
    min_year: int
    max_year: int
    max_exact_age: int

    @property
    def country_name(self) -> str:
        return HMD_COUNTRY_NAMES.get(self.country_code, self.country_code)


def _filename_for_sex(sex: str) -> str:
    if sex == "male":
        return "mltper_1x1.txt"
    if sex == "female":
        return "fltper_1x1.txt"
    raise HmdDataError(f"unsupported HMD sex: {sex!r}")


def _parse_hmd_life_table(fh: TextIO, *, source_label: str) -> dict[int, dict[int, float]]:
    """Parse HMD 1x1 period life-table rows into year -> exact age -> qx."""
    result: dict[int, dict[int, float]] = {}
    header: list[str] | None = None

    for raw in fh:
        line = raw.strip()
        if not line:
            continue
        fields = line.split()

        if header is None:
            lowered = [x.casefold() for x in fields]
            if "year" in lowered and "age" in lowered and "qx" in lowered:
                header = lowered
            continue

        if len(fields) < len(header):
            continue
        row = dict(zip(header, fields))
        year_text = row["year"]
        age_text = row["age"]
        q_text = row["qx"]

        if not year_text.isdigit() or age_text.endswith("+") or not age_text.isdigit():
            continue
        if q_text.casefold() in {".", "na", "nan"}:
            continue

        year = int(year_text)
        age = int(age_text)
        if age >= HMD_OPEN_AGE:
            # HMD's terminal 110+ qx is an open interval and must not be treated
            # as an exact one-year probability.
            continue
        try:
            qx = float(q_text)
        except ValueError:
            continue
        if not 0.0 <= qx <= 1.0:
            raise HmdDataError(f"invalid qx {qx!r} in {source_label}")
        result.setdefault(year, {})[age] = qx

    if header is None:
        raise HmdDataError(f"HMD Year/Age/qx header not found in {source_label}")
    if not result:
        raise HmdDataError(f"no usable HMD qx rows found in {source_label}")
    return result


def _zip_member(zf: zipfile.ZipFile, country_code: str, filename: str) -> str:
    wanted = f"{country_code}/STATS/{filename}".casefold()
    exact = [n for n in zf.namelist() if n.casefold() == wanted]
    if exact:
        return exact[0]

    # Tolerate a wrapper directory around the normal HMD country tree, but do
    # not accept a different country's archive merely because it contains a
    # file with the same basename.
    suffix = "/" + wanted
    wrapped = [n for n in zf.namelist() if n.casefold().endswith(suffix)]
    if wrapped:
        return wrapped[0]
    raise HmdDataError(
        f"{country_code} HMD archive does not contain STATS/{filename}"
    )


def _find_extracted_file(base: Path, country_code: str, filename: str) -> Path | None:
    candidates = [
        base / filename,
        base / "STATS" / filename,
        base / country_code / "STATS" / filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def find_hmd_source(base: Path, country_code: str) -> Path | None:
    """Return a country ZIP or extracted-tree root under *base*, if present."""
    base = Path(base)
    country_code = country_code.upper()

    if base.is_file():
        return base if base.suffix.casefold() == ".zip" else None
    if not base.is_dir():
        return None

    for name in (f"{country_code}.zip", f"{country_code.lower()}.zip"):
        candidate = base / name
        if candidate.is_file():
            return candidate

    # Backward compatibility with the old --hmd-dir contract: a directory may
    # itself be STATS, the country root, or a parent of the country root.
    if _find_extracted_file(base, country_code, "mltper_1x1.txt") or _find_extracted_file(
        base, country_code, "fltper_1x1.txt"
    ):
        return base
    return None


def load_hmd_period_life_table(
    base: Path,
    *,
    country_code: str,
    needed_sexes: set[str],
) -> HmdPeriodLifeTable:
    """Load HMD-created male/female 1x1 period life tables from local data."""
    country_code = country_code.upper()
    source = find_hmd_source(Path(base), country_code)
    if source is None:
        raise HmdDataError(
            f"HMD {country_code} data not found under {base}"
        )

    data: dict[str, dict[int, dict[int, float]]] = {}

    if source.is_file():
        try:
            with zipfile.ZipFile(source) as zf:
                for sex in sorted(needed_sexes):
                    filename = _filename_for_sex(sex)
                    member = _zip_member(zf, country_code, filename)
                    with zf.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig") as fh:
                        data[sex] = _parse_hmd_life_table(
                            fh, source_label=f"{source}:{member}"
                        )
        except zipfile.BadZipFile as exc:
            raise HmdDataError(f"invalid HMD ZIP archive {source}: {exc}") from exc
        source_label = str(source)
    else:
        for sex in sorted(needed_sexes):
            filename = _filename_for_sex(sex)
            path = _find_extracted_file(source, country_code, filename)
            if path is None:
                raise HmdDataError(
                    f"HMD file {filename} not found under {source}"
                )
            with path.open("r", encoding="utf-8-sig") as fh:
                data[sex] = _parse_hmd_life_table(fh, source_label=str(path))
        source_label = str(source)

    data.setdefault("male", {})
    data.setdefault("female", {})
    year_sets = [set(data[sex]) for sex in needed_sexes]
    common_years = sorted(set.intersection(*year_sets))
    if not common_years:
        raise HmdDataError("HMD sex-specific tables have no common usable calendar years")

    max_exact_age = min(
        max(age for year in data[sex].values() for age in year)
        for sex in needed_sexes
    )
    return HmdPeriodLifeTable(
        country_code=country_code,
        source=source_label,
        data=data,
        min_year=common_years[0],
        max_year=common_years[-1],
        max_exact_age=max_exact_age,
    )
