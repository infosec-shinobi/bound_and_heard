from datetime import date
from urllib.parse import parse_qs, urlsplit

from app.services.metadata_providers import (
    GoogleBooksClient,
    OpenLibraryClient,
    normalize_isbn_query,
    normalize_title_author_query,
)


class StubHttpClient:
    def __init__(self, raw_response, http_status=200, headers=None, error_message=None):
        self.raw_response = raw_response
        self.http_status = http_status
        self.headers = headers or {}
        self.error_message = error_message
        self.urls = []

    def get_json(self, url: str, *, timeout_seconds: float = 10.0):
        self.urls.append(url)
        return self.raw_response, self.http_status, self.headers, self.error_message


def test_normalizes_lookup_queries() -> None:
    assert normalize_isbn_query("978-1-234-56789-0") == "9781234567890"
    assert normalize_title_author_query("  The   Book ", " Jane   Doe ") == "the book|jane doe"
    assert normalize_title_author_query("  The   Book ") == "the book"


def test_open_library_parses_common_result_shape_and_keeps_raw_response() -> None:
    raw_response = {
        "docs": [
            {
                "key": "/works/OL123W",
                "title": "Example Book",
                "author_name": ["Jane Doe"],
                "publisher": ["Example Press"],
                "first_publish_year": 2020,
                "isbn": ["123456789X", "9781234567890"],
                "number_of_pages_median": 321,
                "cover_i": 42,
                "subject": ["Fiction", "Adventure"],
            }
        ]
    }
    http_client = StubHttpClient(raw_response)

    response = OpenLibraryClient(http_client).lookup_isbn("978-1-234-56789-0")

    assert response.status == "succeeded"
    assert response.lookup_type == "isbn"
    assert response.normalized_query == "9781234567890"
    assert response.raw_response == raw_response
    assert response.http_status == 200
    result = response.results[0]
    assert result.provider == "open_library"
    assert result.title == "Example Book"
    assert result.authors == ("Jane Doe",)
    assert result.publisher == "Example Press"
    assert result.publication_year == 2020
    assert result.isbn10 == "123456789X"
    assert result.isbn13 == "9781234567890"
    assert result.page_count == 321
    assert result.cover_url == "https://covers.openlibrary.org/b/id/42-L.jpg"
    assert result.categories == ("Fiction", "Adventure")
    assert result.raw_record == raw_response["docs"][0]


def test_google_books_parses_common_result_shape_and_keeps_raw_response() -> None:
    raw_response = {
        "items": [
            {
                "id": "abc123",
                "volumeInfo": {
                    "title": "Example Book",
                    "subtitle": "A Test",
                    "authors": ["Jane Doe"],
                    "publisher": "Example Press",
                    "publishedDate": "2020-05-04",
                    "industryIdentifiers": [
                        {"type": "ISBN_10", "identifier": "123456789X"},
                        {"type": "ISBN_13", "identifier": "9781234567890"},
                    ],
                    "pageCount": 321,
                    "imageLinks": {"thumbnail": "https://example.test/cover.jpg"},
                    "categories": ["Fiction"],
                    "description": "A useful description.",
                },
            }
        ]
    }
    http_client = StubHttpClient(raw_response)

    response = GoogleBooksClient(http_client).lookup_title_author("Example Book", "Jane Doe")

    assert response.status == "succeeded"
    assert response.lookup_type == "title_author"
    assert response.normalized_query == "example book|jane doe"
    assert response.raw_response == raw_response
    result = response.results[0]
    assert result.provider == "google_books"
    assert result.title == "Example Book"
    assert result.subtitle == "A Test"
    assert result.authors == ("Jane Doe",)
    assert result.publisher == "Example Press"
    assert result.published_on == date(2020, 5, 4)
    assert result.publication_year == 2020
    assert result.isbn10 == "123456789X"
    assert result.isbn13 == "9781234567890"
    assert result.page_count == 321
    assert result.cover_url == "https://example.test/cover.jpg"
    assert result.categories == ("Fiction",)
    assert result.description == "A useful description."
    assert result.raw_record == raw_response["items"][0]


def test_google_books_lookup_omits_api_key_when_unconfigured() -> None:
    http_client = StubHttpClient({"items": []})

    GoogleBooksClient(http_client).lookup_isbn("9781234567890")

    query = parse_qs(urlsplit(http_client.urls[0]).query)
    assert query["q"] == ["isbn:9781234567890"]
    assert "key" not in query


def test_google_books_lookup_includes_api_key_when_configured() -> None:
    http_client = StubHttpClient({"items": []})

    GoogleBooksClient(http_client, api_key=" test-key ").lookup_isbn("9781234567890")

    query = parse_qs(urlsplit(http_client.urls[0]).query)
    assert query["q"] == ["isbn:9781234567890"]
    assert query["key"] == ["test-key"]


def test_provider_returns_no_results_for_empty_result_sets() -> None:
    response = GoogleBooksClient(StubHttpClient({"items": []})).lookup_isbn("9781234567890")

    assert response.status == "no_results"
    assert response.results == ()
    assert response.raw_response == {"items": []}


def test_provider_returns_malformed_for_unexpected_response_shape() -> None:
    response = OpenLibraryClient(StubHttpClient({"docs": {}})).lookup_isbn("9781234567890")

    assert response.status == "malformed"
    assert response.results == ()
    assert response.error_message == "Expected docs list."


def test_provider_maps_rate_limit_and_other_errors_safely() -> None:
    rate_limited = GoogleBooksClient(StubHttpClient({"error": "slow down"}, http_status=429, error_message="429 Too Many Requests")).lookup_isbn("9781234567890")
    failed = OpenLibraryClient(StubHttpClient(None, http_status=None, error_message="timed out")).lookup_isbn("9781234567890")

    assert rate_limited.status == "rate_limited"
    assert rate_limited.raw_response == {"error": "slow down"}
    assert failed.status == "failed"
    assert failed.error_message == "timed out"


def test_provider_rejects_empty_queries_without_network_call() -> None:
    http_client = StubHttpClient({"items": []})

    response = GoogleBooksClient(http_client).lookup_isbn("not an isbn")

    assert response.status == "invalid_query"
    assert response.error_message == "Missing lookup query."
    assert http_client.urls == []
