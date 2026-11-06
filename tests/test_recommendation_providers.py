import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app.services.recommendation_providers import (
    DeterministicRecommendationProvider,
    LocalOpenAICompatibleRecommendationProvider,
    OpenAICompatibleRecommendationProvider,
    RecommendationRequest,
)
from app.services.recommendation_service import generate_recommendations


def request_context(**kwargs):
    return RecommendationRequest(history={
        "series": {"active_or_paused": [{
            "series_id": 7, "name": "Local Saga", "status": "active",
            "wants_to_continue": True, "known_entries": 3, "completed_entries": 1,
            "next_unread": {"series_id": 7, "series_name": "Local Saga", "title": "Next Book", "position": 2, "local_book_id": 9},
        }]},
    }, **kwargs)


def suggestion(**kwargs):
    return {
        "recommendation_type": "new_series", "title": "New Saga",
        "reasoning": "Related to your favorite fantasy genre.", "confidence": "medium",
        "source_context": ["favorite_genre:Fantasy"], **kwargs,
    }


def envelope(items):
    return {"choices": [{"message": {"content": json.dumps({"recommendations": items})}}]}


def remote(handler, **kwargs):
    return OpenAICompatibleRecommendationProvider(
        base_url="https://provider.example/v1", model="test-model",
        transport=httpx.MockTransport(handler), **kwargs,
    )


def test_fallback_is_deterministic_and_non_mutating():
    request = request_context()
    before = request.model_dump()
    first = asyncio.run(generate_recommendations(request))
    second = asyncio.run(generate_recommendations(request))
    assert first == second
    assert first.provider == "local"
    assert first.model is None
    assert first.status == "succeeded"
    item = first.recommendations[0]
    assert item.title == "Next Book"
    assert item.local_series_id == 7
    assert item.local_book_id == 9
    assert item.confidence == "high"
    assert item.reasoning and item.source_context
    assert "deterministic" in first.message
    assert request.model_dump() == before


@pytest.mark.parametrize("status,intent", [("paused", True), ("abandoned", True), ("completed", True), ("unknown", True), ("active", False)])
def test_fallback_respects_series_intent(status, intent):
    request = request_context()
    series = request.history.series.active_or_paused[0]
    series.status = status
    series.wants_to_continue = intent
    assert asyncio.run(generate_recommendations(request)).status == "no_results"


@pytest.mark.parametrize("kind", ["new_series", "genre_exploration", "author_adjacent"])
def test_fallback_does_not_invent_discovery(kind):
    response = asyncio.run(generate_recommendations(request_context(recommendation_type=kind)))
    assert response.status == "no_results"
    assert not response.recommendations


def test_empty_history_and_backlog():
    assert asyncio.run(generate_recommendations(RecommendationRequest(history={}))).status == "no_results"
    response = asyncio.run(generate_recommendations(request_context(recommendation_type="backlog_prioritization")))
    assert response.recommendations[0].recommendation_type == "backlog_prioritization"


def test_fallback_limit_and_uncertainty():
    request = request_context(max_results=1)
    series = request.history.series.active_or_paused[0]
    series.next_unread.position = None
    request.history.series.active_or_paused.append(series.model_copy(deep=True))
    response = asyncio.run(DeterministicRecommendationProvider().generate(request))
    assert len(response.recommendations) == 1
    assert response.recommendations[0].confidence == "medium"
    assert response.recommendations[0].caveats


def test_remote_request_privacy_and_response():
    history = request_context().history.model_dump()
    history.update({"secrets": "PRIVATE", "note_summaries": ["PRIVATE"], "raw_import": "PRIVATE"})
    history["series"]["active_or_paused"][0]["next_unread"]["raw_data"] = "PRIVATE"
    history["recent"] = {"completed": [{"title": "Safe Book", "notes": "PRIVATE", "raw_data": "PRIVATE"}]}
    request = RecommendationRequest(history=history)

    def handler(http_request):
        payload = json.loads(http_request.content)
        assert http_request.url == "https://provider.example/v1/chat/completions"
        assert http_request.headers["authorization"] == "Bearer SECRET_KEY"
        assert "PRIVATE" not in http_request.content.decode()
        assert "SECRET_KEY" not in http_request.content.decode()
        assert "Safe Book" in payload["messages"][1]["content"]
        assert payload["stream"] is False
        return httpx.Response(200, json=envelope([suggestion(local_book_id=999, local_series_id=888)]))

    response = asyncio.run(generate_recommendations(request, provider=remote(handler, api_key="SECRET_KEY")))
    assert response.status == "succeeded"
    assert response.model == "test-model"
    assert response.recommendations[0].local_book_id is None
    assert response.recommendations[0].local_series_id is None


@pytest.mark.parametrize("body", [
    {}, [], {"choices": []}, {"choices": [None]},
    {"choices": [{"message": {"content": "not JSON"}}]},
    {"choices": [{"message": {"content": None}}]},
    envelope([suggestion(title=" ")]),
    envelope([suggestion(reasoning="")]),
    envelope([suggestion(confidence="certain")]),
    envelope([suggestion(source_context=[])]),
    envelope([suggestion(recommendation_type="unsupported")]),
    envelope([suggestion(extra="unexpected")]),
])
def test_malformed_responses(body):
    provider = remote(lambda _: httpx.Response(200, json=body))
    response = asyncio.run(provider.generate(request_context()))
    assert response.status == "malformed"
    assert response.recommendations == []


def test_non_json_oversized_and_empty_responses():
    for body in [b"not json", b"x" * 1_000_001]:
        provider = remote(lambda _: httpx.Response(200, content=body))
        assert asyncio.run(provider.generate(request_context())).status == "malformed"
    provider = remote(lambda _: httpx.Response(200, json=envelope([])))
    assert asyncio.run(provider.generate(request_context())).status == "no_results"


@pytest.mark.parametrize("code,status", [(429, "rate_limited"), (401, "failed"), (500, "failed"), (302, "failed")])
def test_http_errors_are_sanitized_and_not_retried(code, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(code, text="SECRET_KEY private provider error", headers={"location": "https://other.example"})

    response = asyncio.run(remote(handler).generate(request_context()))
    assert response.status == status
    assert "SECRET_KEY" not in response.model_dump_json()
    assert len(calls) == 1


@pytest.mark.parametrize("error,status", [(httpx.ConnectError("SECRET"), "failed"), (httpx.ReadTimeout("SECRET"), "timeout")])
def test_transport_errors(error, status):
    def handler(_):
        raise error

    response = asyncio.run(remote(handler).generate(request_context()))
    assert response.status == status
    assert "SECRET" not in response.model_dump_json()


def test_deadline_does_not_block_event_loop():
    async def handler(_):
        await asyncio.sleep(1)
        return httpx.Response(200, json=envelope([]))

    async def run():
        task = asyncio.create_task(remote(handler, timeout_seconds=0.02).generate(request_context()))
        await asyncio.sleep(0)
        assert not task.done()
        return await task

    assert asyncio.run(run()).status == "timeout"


def test_service_guards_custom_provider_errors_and_deadlines():
    class Provider:
        name = "custom"
        model = None

        async def generate(self, request):
            raise RuntimeError("SECRET private history")

    response = asyncio.run(generate_recommendations(request_context(), provider=Provider()))
    assert response.status == "failed"
    assert "SECRET" not in response.model_dump_json()

    class SlowProvider(Provider):
        async def generate(self, request):
            await asyncio.sleep(1)

    response = asyncio.run(generate_recommendations(request_context(), provider=SlowProvider(), timeout_seconds=0.01))
    assert response.status == "timeout"


def test_remote_enforces_count_and_requested_type():
    provider = remote(lambda _: httpx.Response(200, json=envelope([suggestion(), suggestion()])))
    assert asyncio.run(provider.generate(request_context(max_results=1))).status == "malformed"
    provider = remote(lambda _: httpx.Response(200, json=envelope([suggestion()])))
    assert asyncio.run(provider.generate(request_context(recommendation_type="series_continuation"))).status == "malformed"


@pytest.mark.parametrize("url", ["file:///private", "https://key:secret@example.com", "https://example.com?key=secret", "https://example.com#fragment"])
def test_invalid_base_urls(url):
    with pytest.raises(ValueError):
        OpenAICompatibleRecommendationProvider(base_url=url, model="test")


def test_local_provider_uses_same_api_without_key():
    def handler(request):
        assert "authorization" not in request.headers
        return httpx.Response(200, json=envelope([]))

    provider = LocalOpenAICompatibleRecommendationProvider(base_url="http://127.0.0.1:1234/v1", model="local", transport=httpx.MockTransport(handler))
    response = asyncio.run(provider.generate(request_context()))
    assert response.provider == "local_openai_compatible"
    assert response.status == "no_results"
    with pytest.raises(ValueError):
        LocalOpenAICompatibleRecommendationProvider(base_url="https://remote.example/v1", model="test")


@pytest.mark.parametrize("kwargs", [{"max_results": 0}, {"max_results": 21}, {"recommendation_type": "invalid"}])
def test_invalid_requests(kwargs):
    with pytest.raises(ValidationError):
        request_context(**kwargs)


@pytest.mark.parametrize("model,timeout", [(" ", 30), ("test", 0), ("test", 121), ("test", float("nan"))])
def test_invalid_provider_parameters(model, timeout):
    with pytest.raises(ValueError):
        OpenAICompatibleRecommendationProvider(base_url="https://example.com/v1", model=model, timeout_seconds=timeout)
