import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db import models
from django.utils import timezone
from jsonschema import ValidationError, validate

from .models import (
    InvocationStatus,
    ModelDefinition,
    ModelInvocation,
    ModelRoute,
    PrivacyClass,
    ProviderHealthCheck,
    UsagePolicy,
)
from .registry import get_ai_model_adapter


class GatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class GatewayResult:
    text: str
    parsed: Any
    invocation: ModelInvocation


_ALLOWED_PRIVACY: dict[str, set[str]] = {
    PrivacyClass.LOCAL_ONLY: {PrivacyClass.LOCAL_ONLY},
    PrivacyClass.PRIVATE_CLOUD: {PrivacyClass.LOCAL_ONLY, PrivacyClass.PRIVATE_CLOUD},
    PrivacyClass.PUBLIC_CLOUD: set(PrivacyClass.values),
}


def route_models(route: ModelRoute) -> list[ModelDefinition]:
    allowed = _ALLOWED_PRIVACY[route.required_privacy_class]
    return [
        entry.model
        for entry in route.entries.select_related("model__endpoint__provider").all()
        if entry.model.enabled
        and entry.model.endpoint.enabled
        and entry.model.endpoint.provider.enabled
        and entry.model.endpoint.privacy_class in allowed
        and not _circuit_is_open(entry.model)
    ]


def _circuit_is_open(model: ModelDefinition) -> bool:
    recent = list(
        ModelInvocation.objects.filter(model=model)
        .order_by("-created_at")
        .values_list("status", flat=True)[:3]
    )
    return len(recent) == 3 and all(status == InvocationStatus.FAILED for status in recent)


def _enforce_budget(route: ModelRoute, model: ModelDefinition, requested_by) -> None:
    policies = UsagePolicy.objects.filter(workspace=route.workspace, enabled=True).filter(
        models.Q(provider__isnull=True) | models.Q(provider=model.endpoint.provider)
    )
    if requested_by is not None:
        policies = policies.filter(models.Q(user__isnull=True) | models.Q(user=requested_by))
    else:
        policies = policies.filter(user__isnull=True)
    now = timezone.now()
    for policy in policies:
        invocations = ModelInvocation.objects.filter(
            workspace=route.workspace, status=InvocationStatus.SUCCEEDED
        )
        if policy.provider_id:
            invocations = invocations.filter(model__endpoint__provider=policy.provider)
        if policy.user_id:
            invocations = invocations.filter(requested_by=policy.user)
        if policy.daily_budget_cents is not None:
            spent = (
                invocations.filter(created_at__date=now.date()).aggregate(
                    total=models.Sum("estimated_cost_cents")
                )["total"]
                or 0
            )
            if spent >= policy.daily_budget_cents:
                raise GatewayError("Daily usage budget exhausted")
        if policy.monthly_budget_cents is not None:
            spent = (
                invocations.filter(
                    created_at__year=now.year, created_at__month=now.month
                ).aggregate(total=models.Sum("estimated_cost_cents"))["total"]
                or 0
            )
            if spent >= policy.monthly_budget_cents:
                raise GatewayError("Monthly usage budget exhausted")


def invoke(
    *,
    route: ModelRoute,
    prompt: str,
    requested_by=None,
    prompt_version=None,
    output_schema: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> GatewayResult:
    models = route_models(route)
    max_attempts = route.fallback_policy.max_attempts if route.fallback_policy else len(models)
    failures: list[str] = []
    for retry_count, model in enumerate(models[:max_attempts]):
        _enforce_budget(route, model, requested_by)
        invocation = ModelInvocation.objects.create(
            workspace=route.workspace,
            route=route,
            model=model,
            prompt_version=prompt_version,
            requested_by=requested_by,
            task_type=route.task_type,
            retry_count=retry_count,
        )
        adapter = get_ai_model_adapter(model.endpoint.provider.provider_type)
        started = time.monotonic()
        try:
            if adapter is None or not adapter.is_configured():
                raise GatewayError("Provider adapter is unavailable")
            adapter_options = {
                "model": model.model_name,
                "base_url": model.endpoint.base_url,
                "timeout": model.endpoint.timeout_seconds,
                **(options or {}),
            }
            if model.endpoint.credential_id:
                credential = model.endpoint.credential
                if credential is not None:
                    adapter_options["api_key"] = credential.get_secret()
            text = adapter.complete(prompt, **adapter_options)
            parsed = json.loads(text) if output_schema else None
            if output_schema:
                validate(parsed, output_schema)
            invocation.status = InvocationStatus.SUCCEEDED
            invocation.output_schema_valid = True if output_schema else None
            invocation.latency_ms = int((time.monotonic() - started) * 1000)
            invocation.input_tokens = max(1, len(prompt) // 4)
            invocation.output_tokens = max(1, len(text) // 4)
            invocation.estimated_cost_cents = (
                Decimal(invocation.input_tokens) * model.input_cost_per_million
                + Decimal(invocation.output_tokens) * model.output_cost_per_million
            ) / Decimal(10_000)
            invocation.save()
            return GatewayResult(text=text, parsed=parsed, invocation=invocation)
        except (GatewayError, RuntimeError, ValueError, ValidationError, OSError, KeyError) as exc:
            reason = exc.__class__.__name__
            failures.append(reason)
            invocation.status = InvocationStatus.FAILED
            invocation.failure_reason = reason
            invocation.output_schema_valid = False if output_schema else None
            invocation.latency_ms = int((time.monotonic() - started) * 1000)
            invocation.save()
    raise GatewayError(f"No model completed the invocation ({', '.join(failures)})")


def check_provider(provider) -> ProviderHealthCheck:
    endpoint = provider.endpoints.filter(enabled=True).first()
    started = time.monotonic()
    adapter = get_ai_model_adapter(provider.provider_type)
    try:
        if not endpoint or adapter is None or not adapter.is_configured():
            raise GatewayError("Provider is not configured")
        options = {
            "model": endpoint.models.filter(enabled=True)
            .values_list("model_name", flat=True)
            .first()
            or "health-check",
            "base_url": endpoint.base_url,
            "timeout": endpoint.timeout_seconds,
        }
        if endpoint.credential_id:
            credential = endpoint.credential
            if credential is not None:
                options["api_key"] = credential.get_secret()
        adapter.complete("health-check", **options)
        return ProviderHealthCheck.objects.create(
            workspace=provider.workspace,
            provider=provider,
            endpoint=endpoint,
            was_successful=True,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except (GatewayError, RuntimeError, ValueError, OSError, KeyError) as exc:
        return ProviderHealthCheck.objects.create(
            workspace=provider.workspace,
            provider=provider,
            endpoint=endpoint,
            was_successful=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            sanitized_error=exc.__class__.__name__,
        )
