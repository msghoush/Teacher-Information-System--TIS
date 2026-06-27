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
    timezones: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Region:
    id: int
    country_code: str
    name: str
    timezone: str = ""


@dataclass(frozen=True, slots=True)
class City:
    id: int
    region_id: int
    name: str
    timezone: str = ""


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


@dataclass(frozen=True, slots=True)
class CountryLocation:
    country: Country
    regions: tuple[Region, ...]
    regions_by_id: dict[int, Region]
    cities_by_region: dict[int, tuple[City, ...]]
    cities_by_id: dict[int, City]


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _clean_manual_name(value: object, label: str) -> str:
    cleaned = _clean_text(value)
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise LocationValidationError(f"{label} contains unsupported control characters.")
    if len(cleaned) > 160:
        raise LocationValidationError(f"{label} must be 160 characters or fewer.")
    return cleaned


def _iter_raw_countries():
    decoder = json.JSONDecoder()
    buffer: list[str] = []
    depth = 0
    in_string = False
    escaped = False
    collecting = False

    with DATASET_PATH.open("r", encoding="utf-8") as dataset_file:
        while True:
            chunk = dataset_file.read(1024 * 64)
            if not chunk:
                break
            for character in chunk:
                if not collecting:
                    if character == "{":
                        collecting = True
                        depth = 1
                        in_string = False
                        escaped = False
                        buffer = [character]
                    continue

                buffer.append(character)
                if in_string:
                    if escaped:
                        escaped = False
                    elif character == "\\":
                        escaped = True
                    elif character == '"':
                        in_string = False
                    continue

                if character == '"':
                    in_string = True
                elif character == "{":
                    depth += 1
                elif character == "}":
                    depth -= 1
                    if depth == 0:
                        yield decoder.decode("".join(buffer))
                        collecting = False
                        buffer = []


def _country_from_raw(raw_country: dict) -> Country | None:
    country_code = _clean_text(raw_country.get("iso2")).upper()
    country_name = _clean_text(raw_country.get("name"))
    if len(country_code) != 2 or not country_name:
        return None
    timezones = tuple(
        timezone
        for raw_timezone in raw_country.get("timezones") or ()
        if (timezone := _clean_text(raw_timezone.get("zoneName")).replace("\\/", "/"))
    )
    return Country(code=country_code, name=country_name, timezones=timezones)


def _build_country_location(raw_country: dict) -> CountryLocation | None:
    country = _country_from_raw(raw_country)
    if not country:
        return None

    regions: list[Region] = []
    regions_by_id: dict[int, Region] = {}
    cities_by_region: dict[int, tuple[City, ...]] = {}
    cities_by_id: dict[int, City] = {}

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
            country_code=country.code,
            name=region_name,
            timezone=_clean_text(raw_region.get("timezone")).replace("\\/", "/"),
        )
        regions.append(region)
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
            city = City(
                id=city_id,
                region_id=region_id,
                name=city_name,
                timezone=_clean_text(raw_city.get("timezone")).replace("\\/", "/"),
            )
            region_cities.append(city)
            cities_by_id[city_id] = city

        cities_by_region[region_id] = tuple(
            sorted(region_cities, key=lambda city: city.name.casefold())
        )

    return CountryLocation(
        country=country,
        regions=tuple(sorted(regions, key=lambda region: region.name.casefold())),
        regions_by_id=regions_by_id,
        cities_by_region=cities_by_region,
        cities_by_id=cities_by_id,
    )


@lru_cache(maxsize=1)
def _countries() -> tuple[Country, ...]:
    countries = [
        country
        for raw_country in _iter_raw_countries()
        if (country := _country_from_raw(raw_country))
    ]
    return tuple(sorted(countries, key=lambda country: country.name.casefold()))


@lru_cache(maxsize=32)
def _country_location(country_code: str) -> CountryLocation | None:
    normalized_code = _clean_text(country_code).upper()
    for raw_country in _iter_raw_countries():
        if _clean_text(raw_country.get("iso2")).upper() != normalized_code:
            continue
        return _build_country_location(raw_country)
    return None


@lru_cache(maxsize=1)
def get_location_index() -> LocationIndex:
    """Load and compact the local dataset once for the lifetime of this process."""
    countries: list[Country] = []
    countries_by_code: dict[str, Country] = {}
    regions_by_country: dict[str, tuple[Region, ...]] = {}
    regions_by_id: dict[int, Region] = {}
    cities_by_region: dict[int, tuple[City, ...]] = {}
    cities_by_id: dict[int, City] = {}

    for raw_country in _iter_raw_countries():
        country_location = _build_country_location(raw_country)
        if not country_location:
            continue

        country = country_location.country
        countries.append(country)
        countries_by_code[country.code] = country
        regions_by_country[country.code] = country_location.regions
        regions_by_id.update(country_location.regions_by_id)
        cities_by_region.update(country_location.cities_by_region)
        cities_by_id.update(country_location.cities_by_id)

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
        {"code": country.code, "name": country.name, "timezones": list(country.timezones)}
        for country in _countries()
    ]


def list_regions(country_code: str) -> list[dict[str, object]]:
    normalized_code = _clean_text(country_code).upper()
    country_location = _country_location(normalized_code)
    if not country_location:
        raise LocationValidationError("Select a valid country.")
    return [
        {"id": region.id, "name": region.name, "timezone": region.timezone}
        for region in country_location.regions
    ]


def list_cities(country_code: str, region_id: int) -> list[dict[str, object]]:
    normalized_code = _clean_text(country_code).upper()
    country_location = _country_location(normalized_code)
    if not country_location:
        raise LocationValidationError("Select a valid country.")
    region = country_location.regions_by_id.get(int(region_id))
    if not region or region.country_code != normalized_code:
        raise LocationValidationError("Select a valid region for the selected country.")
    return [
        {"id": city.id, "name": city.name, "timezone": city.timezone}
        for city in country_location.cities_by_region.get(region.id, ())
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
    normalized_code = _clean_text(country_code).upper()
    country_location = _country_location(normalized_code)
    if not country_location:
        raise LocationValidationError("Select a valid country.")
    country = country_location.country

    submitted_region_id = _clean_text(region_id)
    if submitted_region_id == OTHER_VALUE:
        region_name = _clean_manual_name(region_manual, "Region/state/province")
        region = None
        if not region_name:
            raise LocationValidationError("Enter the region/state/province name.")
    else:
        try:
            region = country_location.regions_by_id.get(int(submitted_region_id))
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
            city = country_location.cities_by_id.get(int(submitted_city_id))
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
    country_location = _country_location("SA")
    if not country_location:
        return None
    for region in country_location.regions:
        if region.name.casefold() == canonical_name.casefold():
            country = country_location.country
            return ResolvedLocation(
                country_code=country.code,
                country_name=country.name,
                region_name=region.name,
                city_name="",
            )
    return None
