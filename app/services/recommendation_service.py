from __future__ import annotations

import asyncio

from app.services.recommendation_providers import (
    DeterministicRecommendationProvider,
    RecommendationProvider,
    RecommendationRequest,
    RecommendationResponse,
)


async def generate_recommendations(
    request: RecommendationRequest,
    *,
    provider: RecommendationProvider | None = None,
    timeout_seconds: float = 35,
) -> RecommendationResponse:
    """Non-mutating, awaitable service boundary; callers need not block the UI thread."""
    if not 0 < timeout_seconds <= 120:
        raise ValueError("Timeout must be between 0 and 120 seconds.")
    local = DeterministicRecommendationProvider()
    # Local series tracking is authoritative, even when a model is configured.
    # Explicit continuation requests never ask a model to invent missing entries.
    if provider is None or request.recommendation_type in {None, "series_continuation"}:
        response = await local.generate(request)
        if provider is None or response.recommendations or request.recommendation_type == "series_continuation":
            return response
    provider = provider or local
    try:
        response = await asyncio.wait_for(provider.generate(request), timeout=timeout_seconds)
        if request.recommendation_type is None and response.status in {"succeeded", "no_results"}:
            # With no eligible local continuation, model discovery cannot manufacture one.
            items = [item for item in response.recommendations if item.recommendation_type != "series_continuation"]
            response = response.model_copy(update={
                "recommendations": items, "status": "succeeded" if items else "no_results",
            })
        return response
    except TimeoutError:
        return RecommendationResponse(provider=provider.name, model=provider.model, status="timeout", message="Recommendation generation timed out.")
    except Exception:
        # Never expose exception strings: transports may include credentials or history.
        return RecommendationResponse(provider=provider.name, model=provider.model, status="failed", message="Recommendation generation failed safely. Try again later.")
