from __future__ import annotations

from pathlib import PurePosixPath


DOCUMENT_CATEGORIES = (
    ("core", "Core"),
    ("engineering", "Engineering"),
    ("decisions", "Decisions"),
    ("history", "History"),
    ("marketing", "Marketing"),
    ("supporting", "Supporting"),
)
CATEGORY_LABELS = dict(DOCUMENT_CATEGORIES)
APPROVED_CATEGORIES = frozenset(CATEGORY_LABELS)

CORE_DOCUMENTS = {
    "docs/README.md",
    "docs/KMS_NAVIGATION.md",
    "docs/AI_PROJECT_CONTEXT.md",
    "docs/DOCUMENTATION_UPDATE_POLICY.md",
    "docs/TIS_MASTER_CONTEXT.md",
    "docs/PROJECT_STATE.md",
    "docs/CHANGE_HISTORY.md",
}
ADR_MODULES = {
    "0001": "landing-page",
    "0002": "identity-access",
    "0003": "subscriptions",
    "0004": "subscriptions",
    "0005": "provisioning",
    "0006": "platform-knowledge",
    "0007": "landing-page",
}
ENGINEERING_MODULES = {
    "README": "engineering-handbook",
    "TIS_MODULE_MAP": "architecture",
    "REPOSITORY_ARCHITECTURE": "architecture",
    "USER_AND_SYSTEM_FLOWS": "architecture",
    "DATABASE_ARCHITECTURE_OVERVIEW": "database",
    "DEVELOPMENT_STANDARDS": "engineering-governance",
    "UI_UX_DESIGN_PHILOSOPHY": "design",
    "PRODUCT_ROADMAP": "product-roadmap",
    "REJECTED_DECISIONS": "architecture",
    "VISUAL_DOCUMENTATION_GUIDE": "design",
    "AI_OPTIMIZATION_GUIDE": "ai-workflow",
    "PROJECT_GOVERNANCE": "engineering-governance",
    "KNOWLEDGE_LIFECYCLE": "platform-knowledge",
    "DOCUMENTATION_AUTOMATION": "platform-knowledge",
    "KNOWLEDGE_IMPACT_ASSESSMENT_STANDARD": "platform-knowledge",
    "SELF_EVOLVING_WORKFLOW": "platform-knowledge",
    "DOCUMENTATION_DEPENDENCY_MAP": "platform-knowledge",
    "AI_CODING_WORKFLOW": "ai-workflow",
    "FUTURE_AUTOMATION_ROADMAP": "platform-knowledge",
}
MODULE_LABELS = {
    "academic-calendar": "Academic Calendar",
    "ai-workflow": "AI Workflow",
    "architecture": "Architecture",
    "database": "Database",
    "design": "Design",
    "engineering-governance": "Engineering Governance",
    "engineering-handbook": "Engineering Handbook",
    "identity-access": "Identity And Access",
    "kms-core": "KMS Core",
    "landing-page": "Landing Page",
    "location-data": "Location Data",
    "module-history": "Module History",
    "platform-knowledge": "Platform Knowledge",
    "product-roadmap": "Product Roadmap",
    "provisioning": "Provisioning",
    "saas-onboarding": "SaaS Onboarding",
    "subscriptions": "Subscriptions",
    "supporting": "Supporting",
    "workforce-planning": "Workforce Planning",
}
APPROVED_MODULES = frozenset(MODULE_LABELS)


def normalize_catalog_path(source_path: str) -> str:
    return str(source_path or "").replace("\\", "/")


def normalize_taxonomy_value(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "-").replace(" ", "-")


def document_category(source_path: str) -> str:
    normalized = normalize_catalog_path(source_path)
    if normalized in CORE_DOCUMENTS:
        return "core"
    if normalized.startswith("docs/engineering/"):
        return "engineering"
    if normalized.startswith("docs/adr/"):
        return "decisions"
    if normalized.startswith("docs/history/"):
        return "history"
    if normalized.startswith("docs/marketing/"):
        return "marketing"
    return "supporting"


def document_module(source_path: str, category: str, declared_module: str = "") -> str:
    normalized = normalize_catalog_path(source_path)
    parts = PurePosixPath(normalized).parts
    module = normalize_taxonomy_value(declared_module)
    if module:
        return module
    if category == "core":
        return "kms-core"
    if category == "engineering":
        return ENGINEERING_MODULES.get(PurePosixPath(normalized).stem, "engineering-handbook")
    if category == "decisions":
        return ADR_MODULES.get(PurePosixPath(normalized).name[:4], "architecture")
    if category == "history" and len(parts) > 2:
        if normalized == "docs/history/README.md":
            return "module-history"
        return parts[2]
    if category == "marketing":
        return "landing-page"
    if normalized == "docs/location-data-roadmap.md":
        return "location-data"
    return "supporting"


def module_label(module: str) -> str:
    return MODULE_LABELS.get(module, module.replace("-", " ").title())
