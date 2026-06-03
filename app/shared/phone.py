from __future__ import annotations

import re
from typing import Optional

from app.shared.country_calling_codes import (
    COUNTRY_CALLING_CODES,
    DEFAULT_COUNTRY_CODE,
    CountryCallingCode,
    format_country_code,
)
from app.shared.models import NormalizedPhone, NormalizePhoneResult

MIN_PHONE_DIGITS = 6
LEGACY_BARE_NANP_PREFIXES = ["168"]

_DEFAULT_COUNTRY = next(
    (c for c in COUNTRY_CALLING_CODES if format_country_code(c) == DEFAULT_COUNTRY_CODE), None
)
_NANP_COUNTRY = next((c for c in COUNTRY_CALLING_CODES if c.calling_code == "1"), None)
_BY_LONGEST_CALLING_CODE = sorted(
    COUNTRY_CALLING_CODES, key=lambda c: len(c.calling_code), reverse=True
)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def normalize_phone_list(input_text: str) -> NormalizePhoneResult:
    result = NormalizePhoneResult()
    seen: set[str] = set()
    originals = [line.strip() for line in re.split(r"\r?\n", input_text) if line.strip()]

    prefer_bare_nanp = any(
        len(_digits(original)) == 11
        and any(_digits(original).startswith(p) for p in LEGACY_BARE_NANP_PREFIXES)
        for original in originals
    )

    for original in originals:
        normalized = normalize_phone(original, prefer_bare_nanp=prefer_bare_nanp)
        if not normalized:
            result.invalid.append(original)
            continue
        dedupe_key = f"{normalized.country_code}:{normalized.phone}"
        if dedupe_key in seen:
            result.duplicates.append(original)
            continue
        seen.add(dedupe_key)
        result.records.append(normalized)

    return result


def normalize_mexico_phone(original: str) -> Optional[NormalizedPhone]:
    return normalize_phone(original)


def format_otp_lookup_phone(record) -> str:
    original_digits = _digits(record.original)
    if len(original_digits) > len(record.phone):
        return original_digits
    match = re.search(r"\+(\d+)$", record.country_code)
    calling_code = match.group(1) if match else ""
    return f"{calling_code}{record.phone}"


def format_standard_phone_number(record) -> str:
    match = re.search(r"\+(\d+)$", record.country_code)
    calling_code = match.group(1) if match else _digits(record.country_code)
    return f"{calling_code}{_digits(record.phone)}"


def normalize_phone(original: str, prefer_bare_nanp: bool = False) -> Optional[NormalizedPhone]:
    upper = original.upper()
    digits = _digits(upper)
    if len(digits) < MIN_PHONE_DIGITS:
        return None

    explicit = _find_explicit_country(upper, digits)
    if explicit:
        return _build_phone(original, explicit, digits[len(explicit.calling_code):])

    if not _DEFAULT_COUNTRY:
        return None

    inferred = _infer_bare_international_country(upper, digits)
    if inferred:
        return _build_phone(original, inferred, digits[len(inferred.calling_code):])

    if prefer_bare_nanp and _NANP_COUNTRY and len(digits) == 11 and digits.startswith("1"):
        return _build_phone(original, _NANP_COUNTRY, digits[1:])

    phone = digits
    if len(digits) == 11 and any(digits.startswith(p) for p in LEGACY_BARE_NANP_PREFIXES):
        phone = digits[1:]
    if len(phone) > 10 and phone.startswith(_DEFAULT_COUNTRY.calling_code):
        phone = phone[len(_DEFAULT_COUNTRY.calling_code):]

    return _build_phone(original, _DEFAULT_COUNTRY, phone)


def _find_explicit_country(upper: str, digits: str) -> Optional[CountryCallingCode]:
    iso_match = re.search(r"\b([A-Z]{2})\s*\+\s*(\d{1,4})\b", upper)
    if iso_match:
        iso_code, calling_code = iso_match.group(1), iso_match.group(2)
        country = next(
            (
                c
                for c in COUNTRY_CALLING_CODES
                if c.iso_code == iso_code
                and c.calling_code == calling_code
                and digits.startswith(c.calling_code)
            ),
            None,
        )
        if country:
            return country

    if not upper.strip().startswith("+"):
        return None

    return next((c for c in _BY_LONGEST_CALLING_CODE if digits.startswith(c.calling_code)), None)


def _infer_bare_international_country(upper: str, digits: str) -> Optional[CountryCallingCode]:
    if re.search(r"[A-Z+]", upper) or len(digits) <= 10:
        return None
    default_iso = _DEFAULT_COUNTRY.iso_code if _DEFAULT_COUNTRY else ""
    return next(
        (
            c
            for c in _BY_LONGEST_CALLING_CODE
            if c.iso_code != default_iso and c.calling_code != "1" and digits.startswith(c.calling_code)
        ),
        None,
    )


def _build_phone(original: str, country: CountryCallingCode, phone: str) -> Optional[NormalizedPhone]:
    if len(phone) < MIN_PHONE_DIGITS:
        return None
    return NormalizedPhone(
        phone=phone,
        country_code=format_country_code(country),
        original=original,
    )
