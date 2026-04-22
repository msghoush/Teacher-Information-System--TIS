from __future__ import annotations

import re

import models


QUALIFICATION_GROUP_DEGREES = "Academic Degrees"
QUALIFICATION_GROUP_SPECIALIZATIONS = "Majors & Teaching Specializations"
QUALIFICATION_KIND_DEGREE = "degree"
QUALIFICATION_KIND_SPECIALIZATION = "specialization"

SUBJECT_ALIGNMENT_KEYWORD_GROUPS = {
    "math": (
        "math",
        "mathematics",
        "algebra",
        "geometry",
        "calculus",
        "statistics",
        "arithmetic",
        "trigonometry",
    ),
    "science": (
        "science",
        "general science",
        "laboratory",
        "lab",
    ),
    "biology": (
        "biology",
        "life science",
        "life sciences",
    ),
    "chemistry": (
        "chemistry",
        "chemical science",
    ),
    "physics": (
        "physics",
        "physical science",
    ),
    "english": (
        "english",
        "literature",
        "language arts",
        "reading",
        "writing",
        "grammar",
        "phonics",
        "ela",
    ),
    "arabic": (
        "arabic",
        "arabic literature",
        "arabic language",
    ),
    "french": (
        "french",
        "foreign language",
    ),
    "islamic": (
        "islamic",
        "quran",
        "hadith",
        "fiqh",
        "tawheed",
        "religion",
        "islamic studies",
    ),
    "social": (
        "social",
        "social studies",
        "civics",
        "humanities",
    ),
    "history": (
        "history",
        "historical studies",
    ),
    "geography": (
        "geography",
        "earth studies",
    ),
    "computer": (
        "computer",
        "computing",
        "ict",
        "technology",
        "coding",
        "programming",
        "digital",
        "informatics",
        "computer science",
    ),
    "art": (
        "art",
        "drawing",
        "design",
        "visual arts",
    ),
    "music": (
        "music",
        "performing arts",
    ),
    "pe": (
        "physical education",
        "physical",
        "pe",
        "sport",
        "sports",
        "fitness",
    ),
    "economics": (
        "economics",
        "commerce",
        "business",
        "business studies",
        "finance",
    ),
    "accounting": (
        "accounting",
        "bookkeeping",
    ),
    "kindergarten": (
        "kg",
        "kindergarten",
        "early childhood",
        "foundation stage",
    ),
}

_RAW_QUALIFICATION_OPTIONS = (
    {
        "key": "associate_degree",
        "label": "Associate Degree",
        "group": QUALIFICATION_GROUP_DEGREES,
        "kind": QUALIFICATION_KIND_DEGREE,
        "alignment_keys": (),
        "legacy_aliases": ("associate degree", "associate"),
    },
    {
        "key": "diploma_in_education",
        "label": "Diploma in Education",
        "group": QUALIFICATION_GROUP_DEGREES,
        "kind": QUALIFICATION_KIND_DEGREE,
        "alignment_keys": (),
        "legacy_aliases": ("diploma in education", "education diploma", "diploma"),
    },
    {
        "key": "bachelors_degree",
        "label": "Bachelor's Degree",
        "group": QUALIFICATION_GROUP_DEGREES,
        "kind": QUALIFICATION_KIND_DEGREE,
        "alignment_keys": (),
        "legacy_aliases": (
            "bachelor",
            "bachelors",
            "bachelor degree",
            "bachelor's degree",
            "ba",
            "b.a",
            "bs",
            "b.s",
            "bsc",
            "b.sc",
            "bed",
            "b.ed",
        ),
    },
    {
        "key": "postgraduate_diploma",
        "label": "Postgraduate Diploma",
        "group": QUALIFICATION_GROUP_DEGREES,
        "kind": QUALIFICATION_KIND_DEGREE,
        "alignment_keys": (),
        "legacy_aliases": (
            "postgraduate diploma",
            "pg diploma",
            "pgde",
            "pgce",
        ),
    },
    {
        "key": "masters_degree",
        "label": "Master's Degree",
        "group": QUALIFICATION_GROUP_DEGREES,
        "kind": QUALIFICATION_KIND_DEGREE,
        "alignment_keys": (),
        "legacy_aliases": (
            "master",
            "masters",
            "master degree",
            "master's degree",
            "ma",
            "m.a",
            "msc",
            "m.sc",
            "med",
            "m.ed",
        ),
    },
    {
        "key": "doctorate_degree",
        "label": "Doctorate / PhD",
        "group": QUALIFICATION_GROUP_DEGREES,
        "kind": QUALIFICATION_KIND_DEGREE,
        "alignment_keys": (),
        "legacy_aliases": ("doctorate", "phd", "ph.d", "doctoral"),
    },
    {
        "key": "double_major",
        "label": "Double Major / Dual Specialization",
        "group": QUALIFICATION_GROUP_DEGREES,
        "kind": QUALIFICATION_KIND_DEGREE,
        "alignment_keys": (),
        "legacy_aliases": ("double major", "dual specialization", "dual major"),
    },
    {
        "key": "teaching_license",
        "label": "Teaching License / Certification",
        "group": QUALIFICATION_GROUP_DEGREES,
        "kind": QUALIFICATION_KIND_DEGREE,
        "alignment_keys": (),
        "legacy_aliases": (
            "teaching license",
            "teaching licence",
            "teacher certification",
            "certification",
            "license",
        ),
    },
    {
        "key": "english_literature",
        "label": "English Literature",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("english",),
        "legacy_aliases": ("english literature", "english", "ela"),
    },
    {
        "key": "arabic_literature",
        "label": "Arabic Literature",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("arabic",),
        "legacy_aliases": ("arabic literature", "arabic language", "arabic"),
    },
    {
        "key": "mathematics",
        "label": "Mathematics",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("math",),
        "legacy_aliases": ("mathematics", "math"),
    },
    {
        "key": "physics",
        "label": "Physics",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("physics", "science"),
        "legacy_aliases": ("physics",),
    },
    {
        "key": "chemistry",
        "label": "Chemistry",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("chemistry", "science"),
        "legacy_aliases": ("chemistry",),
    },
    {
        "key": "biology",
        "label": "Biology",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("biology", "science"),
        "legacy_aliases": ("biology", "life science"),
    },
    {
        "key": "biochemistry",
        "label": "Biochemistry",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("biology", "chemistry", "science"),
        "legacy_aliases": ("biochemistry", "biochemical science"),
    },
    {
        "key": "general_science",
        "label": "General Science",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("science", "biology", "chemistry", "physics"),
        "legacy_aliases": ("general science", "science"),
    },
    {
        "key": "ict",
        "label": "ICT",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("computer",),
        "legacy_aliases": ("ict", "information technology"),
    },
    {
        "key": "computer_science",
        "label": "Computer Science",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("computer",),
        "legacy_aliases": ("computer science", "computing", "informatics"),
    },
    {
        "key": "education",
        "label": "Education",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": (),
        "legacy_aliases": ("education", "teaching", "pedagogy"),
    },
    {
        "key": "special_education",
        "label": "Special Education",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": (),
        "legacy_aliases": ("special education", "inclusive education"),
    },
    {
        "key": "early_childhood_education",
        "label": "Early Childhood Education",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("kindergarten",),
        "legacy_aliases": (
            "early childhood education",
            "early childhood",
            "kindergarten",
            "foundation stage",
        ),
    },
    {
        "key": "islamic_studies",
        "label": "Islamic Studies",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("islamic", "arabic"),
        "legacy_aliases": ("islamic studies", "islamic", "quran", "religion"),
    },
    {
        "key": "history",
        "label": "History",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("history", "social"),
        "legacy_aliases": ("history",),
    },
    {
        "key": "geography",
        "label": "Geography",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("geography", "social"),
        "legacy_aliases": ("geography",),
    },
    {
        "key": "social_studies",
        "label": "Social Studies",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("social", "history", "geography"),
        "legacy_aliases": ("social studies", "social", "civics", "humanities"),
    },
    {
        "key": "french_language",
        "label": "French Language",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("french",),
        "legacy_aliases": ("french language", "french"),
    },
    {
        "key": "business_studies",
        "label": "Business Studies",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("economics", "accounting"),
        "legacy_aliases": ("business studies", "business", "commerce"),
    },
    {
        "key": "economics",
        "label": "Economics",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("economics", "accounting"),
        "legacy_aliases": ("economics", "finance"),
    },
    {
        "key": "accounting",
        "label": "Accounting",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("accounting", "economics"),
        "legacy_aliases": ("accounting", "bookkeeping"),
    },
    {
        "key": "art_education",
        "label": "Art Education",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("art",),
        "legacy_aliases": ("art education", "art", "visual arts"),
    },
    {
        "key": "music_education",
        "label": "Music Education",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("music",),
        "legacy_aliases": ("music education", "music"),
    },
    {
        "key": "physical_education",
        "label": "Physical Education",
        "group": QUALIFICATION_GROUP_SPECIALIZATIONS,
        "kind": QUALIFICATION_KIND_SPECIALIZATION,
        "alignment_keys": ("pe",),
        "legacy_aliases": ("physical education", "pe", "sports", "sport"),
    },
)

QUALIFICATION_OPTIONS = tuple(
    {
        "key": option["key"],
        "label": option["label"],
        "group": option["group"],
        "kind": option["kind"],
        "alignment_keys": tuple(option["alignment_keys"]),
        "legacy_aliases": tuple(option["legacy_aliases"]),
    }
    for option in _RAW_QUALIFICATION_OPTIONS
)

QUALIFICATION_LOOKUP = {
    option["key"]: option
    for option in QUALIFICATION_OPTIONS
}

_NORMALIZE_PATTERN = re.compile(r"[_\W]+", re.UNICODE)


def get_qualification_group_label(kind: str) -> str:
    normalized_kind = str(kind or "").strip().lower()
    return (
        QUALIFICATION_GROUP_DEGREES
        if normalized_kind == QUALIFICATION_KIND_DEGREE
        else QUALIFICATION_GROUP_SPECIALIZATIONS
    )


def _normalize_text(value: str) -> str:
    cleaned = _NORMALIZE_PATTERN.sub(" ", str(value or "").lower()).strip()
    return " ".join(cleaned.split())


def build_qualification_key(label: str) -> str:
    return _normalize_text(label).replace(" ", "_")


def _normalize_csv_values(value) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = str(value or "").split(",")

    normalized_values = []
    seen_values = set()
    for raw_value in raw_values:
        normalized_value = _normalize_text(raw_value)
        if not normalized_value or normalized_value in seen_values:
            continue
        seen_values.add(normalized_value)
        normalized_values.append(normalized_value)
    return tuple(normalized_values)


def _serialize_qualification_option(
    *,
    key: str,
    label: str,
    kind: str,
    alignment_keys,
    legacy_aliases,
    sort_order: int = 0,
):
    normalized_kind = (
        QUALIFICATION_KIND_DEGREE
        if str(kind or "").strip().lower() == QUALIFICATION_KIND_DEGREE
        else QUALIFICATION_KIND_SPECIALIZATION
    )
    normalized_label = " ".join(str(label or "").split()).strip()
    return {
        "key": str(key or "").strip(),
        "label": normalized_label,
        "group": get_qualification_group_label(normalized_kind),
        "kind": normalized_kind,
        "alignment_keys": _normalize_csv_values(alignment_keys),
        "legacy_aliases": _normalize_csv_values(legacy_aliases),
        "sort_order": int(sort_order or 0),
    }


def ensure_qualification_options_seeded(db) -> list[dict]:
    if db is None:
        return list(QUALIFICATION_OPTIONS)

    existing_count = db.query(models.QualificationOption).count()
    if existing_count == 0:
        for sort_order, option in enumerate(QUALIFICATION_OPTIONS, start=1):
            db.add(
                models.QualificationOption(
                    qualification_key=option["key"],
                    label=option["label"],
                    kind=option["kind"],
                    alignment_keys=",".join(option["alignment_keys"]),
                    legacy_aliases=",".join(option["legacy_aliases"]),
                    sort_order=sort_order,
                )
            )
        db.commit()

    configured_rows = db.query(models.QualificationOption).order_by(
        models.QualificationOption.kind.asc(),
        models.QualificationOption.sort_order.asc(),
        models.QualificationOption.label.asc(),
        models.QualificationOption.id.asc(),
    ).all()
    return [
        _serialize_qualification_option(
            key=row.qualification_key,
            label=row.label,
            kind=row.kind,
            alignment_keys=row.alignment_keys,
            legacy_aliases=row.legacy_aliases,
            sort_order=row.sort_order,
        )
        for row in configured_rows
        if str(row.qualification_key or "").strip() and str(row.label or "").strip()
    ]


def get_qualification_options(db=None) -> list[dict]:
    if db is None:
        return [dict(option) for option in QUALIFICATION_OPTIONS]
    return ensure_qualification_options_seeded(db)


def get_qualification_lookup(db=None, qualification_options=None) -> dict:
    options = qualification_options if qualification_options is not None else get_qualification_options(db)
    return {
        option["key"]: option
        for option in options
        if option.get("key")
    }


def _contains_alias(normalized_text: str, alias: str) -> bool:
    normalized_alias = _normalize_text(alias)
    if not normalized_text or not normalized_alias:
        return False
    return f" {normalized_alias} " in f" {normalized_text} "


def normalize_qualification_keys(values, qualification_lookup=None) -> list[str]:
    active_lookup = qualification_lookup or QUALIFICATION_LOOKUP
    normalized_keys = []
    seen_keys = set()
    for raw_value in values or []:
        key = str(raw_value or "").strip()
        if not key or key not in active_lookup or key in seen_keys:
            continue
        seen_keys.add(key)
        normalized_keys.append(key)
    return normalized_keys


def infer_qualification_keys_from_legacy_text(
    value: str,
    *,
    qualification_options=None,
    qualification_lookup=None,
) -> list[str]:
    normalized_text = _normalize_text(value)
    if not normalized_text:
        return []

    inferred_keys = []
    active_options = (
        qualification_options
        if qualification_options is not None
        else list((qualification_lookup or QUALIFICATION_LOOKUP).values())
    )
    for option in active_options:
        for alias in option["legacy_aliases"]:
            if _contains_alias(normalized_text, alias):
                inferred_keys.append(option["key"])
                break

    return normalize_qualification_keys(
        inferred_keys,
        qualification_lookup=qualification_lookup or get_qualification_lookup(
            qualification_options=active_options
        ),
    )


def get_qualification_labels(keys, qualification_lookup=None) -> list[str]:
    active_lookup = qualification_lookup or QUALIFICATION_LOOKUP
    return [
        active_lookup[key]["label"]
        for key in normalize_qualification_keys(keys, qualification_lookup=active_lookup)
        if key in active_lookup
    ]


def build_qualification_summary(
    keys,
    *,
    fallback_text: str = "",
    max_items: int | None = None,
    max_length: int | None = None,
    qualification_lookup=None,
) -> str:
    labels = get_qualification_labels(keys, qualification_lookup=qualification_lookup)
    if not labels:
        return " ".join(str(fallback_text or "").split()).strip()

    display_labels = list(labels)
    if max_items is not None and max_items > 0 and len(display_labels) > max_items:
        remaining_count = len(display_labels) - max_items
        display_labels = display_labels[:max_items] + [f"+{remaining_count} more"]

    summary = ", ".join(display_labels)
    if max_length is not None and max_length > 0 and len(summary) > max_length:
        summary = summary[: max_length - 1].rstrip(", ") + "…"
    return summary


def build_legacy_qualification_snapshot(
    keys,
    max_length: int = 120,
    *,
    qualification_lookup=None,
) -> str:
    return build_qualification_summary(
        keys,
        max_items=6,
        max_length=max_length,
        qualification_lookup=qualification_lookup,
    )


def get_qualification_option_groups(db=None, qualification_options=None) -> list[dict]:
    active_options = qualification_options if qualification_options is not None else get_qualification_options(db)
    groups = []
    for group_label in (
        QUALIFICATION_GROUP_DEGREES,
        QUALIFICATION_GROUP_SPECIALIZATIONS,
    ):
        groups.append(
            {
                "label": group_label,
                "options": [
                    {
                        "key": option["key"],
                        "label": option["label"],
                        "kind": option["kind"],
                        "sort_order": option.get("sort_order", 0),
                        "kind_label": (
                            "Degree / award"
                            if option["kind"] == QUALIFICATION_KIND_DEGREE
                            else "Major / specialization"
                        ),
                    }
                    for option in active_options
                    if option["group"] == group_label
                ],
            }
        )
    return groups


def get_qualification_options_for_json(db=None, qualification_options=None) -> list[dict]:
    active_options = qualification_options if qualification_options is not None else get_qualification_options(db)
    return [
        {
            "key": option["key"],
            "label": option["label"],
            "group": option["group"],
            "kind": option["kind"],
            "alignment_keys": list(option["alignment_keys"]),
        }
        for option in active_options
    ]


def get_subject_alignment_keyword_groups_for_json() -> dict:
    return {
        group_key: list(aliases)
        for group_key, aliases in SUBJECT_ALIGNMENT_KEYWORD_GROUPS.items()
    }


def get_selected_alignment_keys(qualification_keys, qualification_lookup=None) -> list[str]:
    active_lookup = qualification_lookup or QUALIFICATION_LOOKUP
    alignment_keys = set()
    for key in normalize_qualification_keys(qualification_keys, qualification_lookup=active_lookup):
        for alignment_key in active_lookup[key]["alignment_keys"]:
            alignment_keys.add(alignment_key)
    return sorted(alignment_keys)


def get_selected_specialization_keys(qualification_keys, qualification_lookup=None) -> list[str]:
    active_lookup = qualification_lookup or QUALIFICATION_LOOKUP
    return [
        key
        for key in normalize_qualification_keys(qualification_keys, qualification_lookup=active_lookup)
        if active_lookup[key]["kind"] == QUALIFICATION_KIND_SPECIALIZATION
    ]


def has_specialization_qualification(qualification_keys, qualification_lookup=None) -> bool:
    return bool(
        get_selected_specialization_keys(
            qualification_keys,
            qualification_lookup=qualification_lookup,
        )
    )


def get_subject_alignment_group_keys(subject_name: str, fallback_code: str = "") -> list[str]:
    normalized_text = _normalize_text(f"{fallback_code} {subject_name}")
    if not normalized_text:
        return []

    matched_group_keys = set()
    for group_key, aliases in SUBJECT_ALIGNMENT_KEYWORD_GROUPS.items():
        if _contains_alias(normalized_text, group_key):
            matched_group_keys.add(group_key)
            continue
        for alias in aliases:
            if _contains_alias(normalized_text, alias):
                matched_group_keys.add(group_key)
                break

    return sorted(matched_group_keys)


def get_subject_qualification_alignment(
    subject_name: str,
    fallback_code: str,
    qualification_keys,
    *,
    qualification_lookup=None,
) -> dict:
    active_lookup = qualification_lookup or QUALIFICATION_LOOKUP
    normalized_qualification_keys = normalize_qualification_keys(
        qualification_keys,
        qualification_lookup=active_lookup,
    )
    if not normalized_qualification_keys:
        return {
            "status": "empty",
            "label": "Add qualifications",
            "matched_qualification_keys": [],
            "matched_qualification_labels": [],
            "subject_group_keys": [],
            "recognized_subject": False,
            "has_specialization": False,
        }

    selected_alignment_keys = set(
        get_selected_alignment_keys(
            normalized_qualification_keys,
            qualification_lookup=active_lookup,
        )
    )
    if not selected_alignment_keys:
        return {
            "status": "review",
            "label": "Add specialization",
            "matched_qualification_keys": [],
            "matched_qualification_labels": [],
            "subject_group_keys": [],
            "recognized_subject": False,
            "has_specialization": False,
        }

    subject_group_keys = set(
        get_subject_alignment_group_keys(subject_name, fallback_code)
    )
    if not subject_group_keys:
        return {
            "status": "review",
            "label": "Review fit",
            "matched_qualification_keys": [],
            "matched_qualification_labels": [],
            "subject_group_keys": [],
            "recognized_subject": False,
            "has_specialization": True,
        }

    matched_keys = []
    for key in normalized_qualification_keys:
        alignment_keys = set(active_lookup[key]["alignment_keys"])
        if alignment_keys and alignment_keys.intersection(subject_group_keys):
            matched_keys.append(key)

    status = "match" if matched_keys else "review"
    label = "Qualification match" if matched_keys else "Review fit"
    return {
        "status": status,
        "label": label,
        "matched_qualification_keys": matched_keys,
        "matched_qualification_labels": get_qualification_labels(
            matched_keys,
            qualification_lookup=active_lookup,
        ),
        "subject_group_keys": sorted(subject_group_keys),
        "recognized_subject": True,
        "has_specialization": True,
    }
