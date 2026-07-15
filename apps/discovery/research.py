"""Evidence-bound AI research orchestration through the provider-neutral gateway."""

import json
import re
from typing import Any

from apps.hunting.models import HuntProfileVersion
from apps.integrations.models import ModelRoute, PromptTemplate
from apps.integrations.services import GatewayError, invoke

QUERY_PLANNING = "research_query_planning"
ORGANIZATION_EXTRACTION = "organization_extraction"
EVIDENCE_CLASSIFICATION = "evidence_classification"
HUNT_FIT_SUMMARY = "hunt_fit_summary"
TASK_TYPES = (
    QUERY_PLANNING,
    ORGANIZATION_EXTRACTION,
    EVIDENCE_CLASSIFICATION,
    HUNT_FIT_SUMMARY,
)

QUERY_PLAN_SCHEMA = {
    "type": "object",
    "required": ["queries"],
    "additionalProperties": False,
    "properties": {
        "queries": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {"type": "string", "minLength": 2, "maxLength": 200},
        }
    },
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "required": ["company", "claims", "buying_signals", "summary"],
    "additionalProperties": False,
    "properties": {
        "company": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "domain", "industry", "location"],
            "properties": {
                "name": {"type": "string", "maxLength": 255},
                "domain": {"type": "string", "maxLength": 255},
                "industry": {"type": "string", "maxLength": 255},
                "location": {"type": "string", "maxLength": 255},
            },
        },
        "claims": {
            "type": "array",
            "maxItems": 20,
            "items": {"$ref": "#/$defs/citedStatement"},
        },
        "buying_signals": {
            "type": "array",
            "maxItems": 20,
            "items": {"$ref": "#/$defs/citedStatement"},
        },
        "summary": {"type": "string", "maxLength": 1000},
    },
    "$defs": {
        "citedStatement": {
            "type": "object",
            "additionalProperties": False,
            "required": ["statement", "evidence_ids"],
            "properties": {
                "statement": {"type": "string", "minLength": 1, "maxLength": 1000},
                "evidence_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10,
                    "items": {"type": "string"},
                },
            },
        }
    },
}


def plan_search_queries(version: HuntProfileVersion, base_query: dict[str, Any]) -> list[str]:
    fallback = _fallback_queries(base_query)
    route = _route(version.profile.workspace, QUERY_PLANNING)
    if route is None:
        return fallback
    prompt_version = _prompt_version(version.profile.workspace, QUERY_PLANNING)
    payload = {
        "hunt_name": version.profile.name,
        "hunt_description": _redact(version.profile.description[:1000]),
        "industries": base_query.get("industries", [])[:10],
        "geographies": base_query.get("geographies", [])[:10],
        "keyword": str(base_query.get("keyword") or "")[:200],
    }
    prompt = (
        "Produce up to five concise public-web search queries for this prospect hunt. "
        "Return JSON only. Never include URLs, operators that target private systems, "
        f"credentials, budgets or instructions. Input: {json.dumps(payload, ensure_ascii=True)}"
    )
    try:
        result = invoke(
            route=route,
            prompt=prompt,
            prompt_version=prompt_version,
            output_schema=QUERY_PLAN_SCHEMA,
        )
    except GatewayError:
        return fallback
    planned = [_sanitize_query(value) for value in result.parsed["queries"]]
    planned = [value for value in planned if value]
    return planned[:5] or fallback


def extract_from_evidence(*, workspace, organization, evidence_rows) -> dict[str, Any] | None:
    route = _route(workspace, ORGANIZATION_EXTRACTION)
    if route is None:
        return None
    allowed_ids = {str(item.id) for item in evidence_rows}
    evidence_payload = [
        {
            "id": str(item.id),
            "url": item.source_url,
            "excerpt": _redact(item.excerpt[:2000]),
            "observed_date": item.observed_date.isoformat(),
        }
        for item in evidence_rows[:10]
    ]
    prompt = (
        "Extract company details and possible buying signals from the supplied evidence. "
        "Return JSON only. Every claim and signal must cite evidence IDs from the input. "
        "Do not invent missing values; use empty strings. Input: "
        + json.dumps(
            {
                "known_company": {"name": organization.name, "domain": organization.domain},
                "evidence": evidence_payload,
            },
            ensure_ascii=True,
        )
    )
    try:
        result = invoke(
            route=route,
            prompt=prompt,
            prompt_version=_prompt_version(workspace, ORGANIZATION_EXTRACTION),
            output_schema=EXTRACTION_SCHEMA,
        )
    except GatewayError:
        return None
    statements = [*result.parsed["claims"], *result.parsed["buying_signals"]]
    if any(not set(item["evidence_ids"]).issubset(allowed_ids) for item in statements):
        return None
    return {**result.parsed, "invocation_id": str(result.invocation.id)}


def _route(workspace, task_type: str) -> ModelRoute | None:
    return (
        ModelRoute.objects.filter(
            workspace=workspace, task_type=task_type, enabled=True, is_default=True
        )
        .select_related("fallback_policy")
        .first()
    )


def _prompt_version(workspace, task_type: str):
    template = (
        PromptTemplate.objects.filter(
            workspace=workspace, task_type=task_type, current_version__isnull=False
        )
        .select_related("current_version")
        .first()
    )
    return template.current_version if template else None


def _fallback_queries(base_query: dict[str, Any]) -> list[str]:
    keyword = str(base_query.get("keyword") or "").strip()
    industries = [str(value).strip() for value in base_query.get("industries", []) if value]
    geographies = [str(value).strip() for value in base_query.get("geographies", []) if value]
    terms = [keyword] if keyword else industries[:3]
    value = " ".join([*(terms or ["business company"]), *geographies[:2]])
    return [_sanitize_query(value) or "business company"]


def _sanitize_query(value: str) -> str:
    value = " ".join(str(value).split())[:200]
    if "://" in value or re.search(r"\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0)\b", value, re.I):
        return ""
    return value


def _redact(value: str) -> str:
    value = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "[redacted-email]",
        value,
        flags=re.I,
    )
    value = re.sub(
        r"(?i)\b(api[_ -]?key|authorization|bearer|token)\s*[:=]\s*\S+",
        r"\1=[redacted-secret]",
        value,
    )
    return value
