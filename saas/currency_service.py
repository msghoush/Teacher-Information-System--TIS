from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from saas import models

DEFAULT_CURRENCY_CODE = "USD"


@dataclass(frozen=True)
class DisplayCurrency:
    currency_code: str
    currency_symbol: str
    minor_unit: int
    locale: str
    usd_display_rate: Decimal


def _decimal(value) -> Decimal:
    return Decimal(str(value or "0"))


def get_default_currency(db: Session) -> DisplayCurrency:
    profile = db.query(models.CurrencyProfile).filter(
        models.CurrencyProfile.currency_code == DEFAULT_CURRENCY_CODE
    ).first()
    if profile:
        return DisplayCurrency(
            currency_code=profile.currency_code,
            currency_symbol=profile.currency_symbol,
            minor_unit=int(profile.minor_unit or 2),
            locale="en-US",
            usd_display_rate=Decimal("1"),
        )
    return DisplayCurrency(
        currency_code=DEFAULT_CURRENCY_CODE,
        currency_symbol="$",
        minor_unit=2,
        locale="en-US",
        usd_display_rate=Decimal("1"),
    )


def resolve_display_currency(db: Session, *, country_code: str = "") -> DisplayCurrency:
    cleaned_country = str(country_code or "").strip().upper()
    if not cleaned_country:
        return get_default_currency(db)
    mapping = db.query(models.CountryCurrencyMap).filter(
        models.CountryCurrencyMap.country_code == cleaned_country,
        models.CountryCurrencyMap.is_active == True,
    ).first()
    if not mapping:
        return get_default_currency(db)
    profile = db.query(models.CurrencyProfile).filter(
        models.CurrencyProfile.currency_code == mapping.currency_code,
        models.CurrencyProfile.is_active == True,
    ).first()
    if not profile:
        return get_default_currency(db)
    return DisplayCurrency(
        currency_code=profile.currency_code,
        currency_symbol=profile.currency_symbol,
        minor_unit=int(profile.minor_unit or 2),
        locale=str(mapping.display_locale or "en-US"),
        usd_display_rate=_decimal(mapping.usd_display_rate),
    )


def convert_minor_from_usd(base_amount_minor: int, display_currency: DisplayCurrency) -> int:
    if display_currency.currency_code == DEFAULT_CURRENCY_CODE:
        return int(base_amount_minor or 0)
    converted = (_decimal(base_amount_minor) * display_currency.usd_display_rate).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    return int(converted)


def format_minor_amount(amount_minor: int, display_currency: DisplayCurrency) -> str:
    minor_unit = max(0, int(display_currency.minor_unit or 2))
    scale = Decimal(10) ** minor_unit
    major = (_decimal(amount_minor) / scale).quantize(
        Decimal("1." + ("0" * minor_unit)) if minor_unit else Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    return f"{display_currency.currency_symbol}{major}"
