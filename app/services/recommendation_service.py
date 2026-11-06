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
    provider = provider or DeterministicRecommendationProvider()
    try:
        return await asyncio.wait_for(provider.generate(request), timeout=timeout_seconds)
    except TimeoutError:
        return RecommendationResponse(provider=provider.name, model=provider.model, status="timeout", message="Recommendation generation timed out.")
    except Exception:
        # Never expose exception strings: transports may include credentials or history.
        return RecommendationResponse(provider=provider.name, model=provider.model, status="failed", message="Recommendation generation failed safely. Try again later.")
