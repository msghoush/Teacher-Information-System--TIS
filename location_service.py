import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


DATASET_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "locations"
    / "countries_states_cities.json"
)
OTHER_VALUE = "__other__"
SAUDI_REGION_ALIASES = {
    "riyadh region": "Riyadh",
    "makkah region": "Makkah",
    "madinah region": "Madinah",
    "eastern province": "Eastern Province",
    "al qassim region": "Qassim",
    "hail region": "Ha'il",
    "tabuk region": "Tabuk",
    "northern borders region": "Northern Borders",
    "al jawf region": "Al Jawf",
    "jazan region": "Jazan",
    "najran region": "Najran",
    "al bahah region": "Al Bahah",
    "asir region": "Asir",
}


class LocationValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Country:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class Region:
    id: int
    country_code: str
    name: str


@dataclass(frozen=True, slots=True)
class City:
    id: int
    region_id: int
    name: str


@dataclass(frozen=True, slots=True)
class LocationIndex:
    countries: tuple[Country, ...]
    countries_by_code: dict[str, Country]
    regions_by_country: dict[str, tuple[Region, ...]]
    regions_by_id: dict[int, Region]
    cities_by_region: dict[int, tuple[City, ...]]
    cities_by_id: dict[int, City]


@dataclass(frozen=True, slots=True)
class ResolvedLocation:
    country_code: str
    country_name: str
    region_name: str
    city_name: str


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _clean_manual_name(value: object, label: str) -> str:
    cleaned = _clean_text(value)
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise LocationValidationError(f"{label} contains unsupported control characters.")
    if len(cleaned) > 160:
        raise LocationValidationError(f"{label} must be 160 characters or fewer.")
    return cleaned


@lru_cache(maxsize=1)
def get_location_index() -> LocationIndex:
    """Load and compact the local dataset once for the lifetime of this process."""
    with DATASET_PATH.open("r", encoding="utf-8") as dataset_file:
        raw_countries = json.load(dataset_file)

    countries: list[Country] = []
    countries_by_code: dict[str, Country] = {}
    regions_by_country: dict[str, tuple[Region, ...]] = {}
    regions_by_id: dict[int, Region] = {}
    cities_by_region: dict[int, tuple[City, ...]] = {}
    cities_by_id: dict[int, City] = {}

    for raw_country in raw_countries:
        country_code = _clean_text(raw_country.get("iso2")).upper()
        country_name = _clean_text(raw_country.get("name"))
        if len(country_code) != 2 or not country_name:
            continue

        country = Country(code=country_code, name=country_name)
        countries.append(country)
        countries_by_code[country_code] = country

        country_regions: list[Region] = []
        for raw_region in raw_country.get("states") or ():
            try:
                region_id = int(raw_region.get("id"))
            except (TypeError, ValueError):
                continue
            region_name = _clean_text(raw_region.get("name"))
            if not region_name:
                continue

            region = Region(
                id=region_id,
                country_code=country_code,
                name=region_name,
            )
            country_regions.append(region)
            regions_by_id[region_id] = region

            region_cities: list[City] = []
            seen_city_names: set[str] = set()
            for raw_city in raw_region.get("cities") or ():
                try:
                    city_id = int(raw_city.get("id"))
                except (TypeError, ValueError):
                    continue
                city_name = _clean_text(raw_city.get("name"))
                city_key = city_name.casefold()
                if not city_name or city_key in seen_city_names:
                    continue
                seen_city_names.add(city_key)
                city = City(id=city_id, region_id=region_id, name=city_name)
                region_cities.append(city)
                cities_by_id[city_id] = city

            cities_by_region[region_id] = tuple(
                sorted(region_cities, key=lambda city: city.name.casefold())
            )

        regions_by_country[country_code] = tuple(
            sorted(country_regions, key=lambda region: region.name.casefold())
        )

    countries.sort(key=lambda country: country.name.casefold())
    return LocationIndex(
        countries=tuple(countries),
        countries_by_code=countries_by_code,
        regions_by_country=regions_by_country,
        regions_by_id=regions_by_id,
        cities_by_region=cities_by_region,
        cities_by_id=cities_by_id,
    )


def list_countries() -> list[dict[str, object]]:
    return [
        {"code": country.code, "name": country.name}
        for country in get_location_index().countries
    ]


def list_regions(country_code: str) -> list[dict[str, object]]:
    normalized_code = _clean_text(country_code).upper()
    index = get_location_index()
    if normalized_code not in index.countries_by_code:
        raise LocationValidationError("Select a valid country.")
    return [
        {"id": region.id, "name": region.name}
        for region in index.regions_by_country.get(normalized_code, ())
    ]


def list_cities(country_code: str, region_id: int) -> list[dict[str, object]]:
    normalized_code = _clean_text(country_code).upper()
    index = get_location_index()
    region = index.regions_by_id.get(int(region_id))
    if not region or region.country_code != normalized_code:
        raise LocationValidationError("Select a valid region for the selected country.")
    return [
        {"id": city.id, "name": city.name}
        for city in index.cities_by_region.get(region.id, ())
    ]


def resolve_location(
    *,
    country_code: str,
    region_id: str,
    region_manual: str,
    city_id: str,
    city_manual: str,
    require_city: bool = True,
) -> ResolvedLocation:
    index = get_location_index()
    normalized_code = _clean_text(country_code).upper()
    country = index.countries_by_code.get(normalized_code)
    if not country:
        raise LocationValidationError("Select a valid country.")

    submitted_region_id = _clean_text(region_id)
    if submitted_region_id == OTHER_VALUE:
        region_name = _clean_manual_name(region_manual, "Region/state/province")
        region = None
        if not region_name:
            raise LocationValidationError("Enter the region/state/province name.")
    else:
        try:
            region = index.regions_by_id.get(int(submitted_region_id))
        except (TypeError, ValueError):
            region = None
        if not region or region.country_code != normalized_code:
            raise LocationValidationError("Select a valid region for the selected country.")
        region_name = region.name

    submitted_city_id = _clean_text(city_id)
    if not submitted_city_id and not require_city:
        city_name = ""
        return ResolvedLocation(
            country_code=country.code,
            country_name=country.name,
            region_name=region_name,
            city_name=city_name,
        )
    if submitted_city_id == OTHER_VALUE:
        city_name = _clean_manual_name(city_manual, "City/locality")
        if not city_name:
            raise LocationValidationError("Enter the city name.")
    else:
        try:
            city = index.cities_by_id.get(int(submitted_city_id))
        except (TypeError, ValueError):
            city = None
        if not region or not city or city.region_id != region.id:
            raise LocationValidationError("Select a valid city for the selected region.")
        city_name = city.name

    return ResolvedLocation(
        country_code=country.code,
        country_name=country.name,
        region_name=region_name,
        city_name=city_name,
    )


def infer_legacy_saudi_location(region_name: str) -> ResolvedLocation | None:
    cleaned_region = _clean_text(region_name)
    if not cleaned_region:
        return None
    canonical_name = SAUDI_REGION_ALIASES.get(
        cleaned_region.casefold(),
        cleaned_region,
    )
    index = get_location_index()
    for region in index.regions_by_country.get("SA", ()):
        if region.name.casefold() == canonical_name.casefold():
            country = index.countries_by_code["SA"]
            return ResolvedLocation(
                country_code=country.code,
                country_name=country.name,
                region_name=region.name,
                city_name="",
            )
    return None
