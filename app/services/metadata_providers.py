from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from json import JSONDecodeError, loads
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


JsonValue = dict[str, Any] | list[Any]


@dataclass(frozen=True)
class MetadataResult:
    provider: str
    title: str | None = None
    subtitle: str | None = None
    authors: tuple[str, ...] = ()
    publisher: str | None = None
    published_on: date | None = None
    publication_year: int | None = None
    isbn10: str | None = None
    isbn13: str | None = None
    page_count: int | None = None
    cover_url: str | None = None
    categories: tuple[str, ...] = ()
    description: str | None = None
    provider_record_id: str | None = None
    confidence: float = 0.0
    raw_record: dict[str, Any] | None = None


@dataclass(frozen=True)
class MetadataLookupResponse:
    provider: str
    lookup_type: str
    normalized_query: str
    status: str
    results: tuple[MetadataResult, ...] = ()
    raw_response: JsonValue | None = None
    http_status: int | None = None
    error_message: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def successful(self) -> bool:
        return self.status == "succeeded"


class MetadataProvider(Protocol):
    name: str

    def lookup_isbn(self, isbn: str) -> MetadataLookupResponse: ...

    def lookup_title_author(self, title: str, author: str | None = None) -> MetadataLookupResponse: ...

    def parse_cached_response(
        self,
        *,
        lookup_type: str,
        normalized_query: str,
        status: str,
        raw_response: JsonValue | None,
        http_status: int | None = None,
        error_message: str | None = None,
    ) -> MetadataLookupResponse: ...


def clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def clean_isbn(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = "".join(character for character in value if character.isdigit() or character.upper() == "X")
    return cleaned or None


def normalize_isbn_query(isbn: str) -> str:
    return clean_isbn(isbn) or ""


def normalize_title_author_query(title: str, author: str | None = None) -> str:
    normalized_title = " ".join(title.strip().casefold().split())
    normalized_author = " ".join((author or "").strip().casefold().split())
    return f"{normalized_title}|{normalized_author}" if normalized_author else normalized_title


def parse_partial_date(value: Any) -> tuple[date | None, int | None]:
    if isinstance(value, int) and 1000 <= value <= 9999:
        return None, value
    cleaned = clean_string(value)
    if cleaned is None:
        return None, None
    if len(cleaned) >= 10 and cleaned[4] == "-" and cleaned[7] == "-":
        try:
            parsed = date.fromisoformat(cleaned[:10])
            return parsed, parsed.year
        except ValueError:
            pass
    for token in cleaned.replace(",", " ").split():
        if len(token) == 4 and token.isdigit():
            year = int(token)
            if 1000 <= year <= 9999:
                return None, year
    return None, None


class JsonHttpClient:
    def get_json(self, url: str, *, timeout_seconds: float = 10.0) -> tuple[JsonValue | None, int | None, dict[str, str], str | None]:
        request = Request(url, headers={"User-Agent": "bound-and-heard/0.1"})
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8")
                return loads(body), response.status, dict(response.headers), None
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                raw_response: JsonValue | None = loads(body)
            except JSONDecodeError:
                raw_response = None
            return raw_response, exc.code, dict(exc.headers), str(exc)
        except (JSONDecodeError, URLError, TimeoutError, OSError) as exc:
            return None, None, {}, str(exc)


class OpenLibraryClient:
    name = "open_library"
    base_url = "https://openlibrary.org/search.json"

    def __init__(self, http_client: JsonHttpClient | None = None) -> None:
        self.http_client = http_client or JsonHttpClient()

    def lookup_isbn(self, isbn: str) -> MetadataLookupResponse:
        normalized_query = normalize_isbn_query(isbn)
        return self._lookup("isbn", normalized_query, {"isbn": normalized_query})

    def lookup_title_author(self, title: str, author: str | None = None) -> MetadataLookupResponse:
        normalized_query = normalize_title_author_query(title, author)
        params = {"title": title}
        if clean_string(author) is not None:
            params["author"] = author or ""
        return self._lookup("title_author", normalized_query, params)

    def _lookup(self, lookup_type: str, normalized_query: str, params: dict[str, str]) -> MetadataLookupResponse:
        if not normalized_query:
            return MetadataLookupResponse(self.name, lookup_type, normalized_query, "invalid_query", error_message="Missing lookup query.")
        raw_response, http_status, headers, error_message = self.http_client.get_json(f"{self.base_url}?{urlencode(params)}")
        response = self.parse_cached_response(
            lookup_type=lookup_type,
            normalized_query=normalized_query,
            status="failed" if error_message is not None else "succeeded",
            raw_response=raw_response,
            http_status=http_status,
            error_message=error_message,
        )
        return MetadataLookupResponse(
            provider=response.provider,
            lookup_type=response.lookup_type,
            normalized_query=response.normalized_query,
            status=response.status,
            results=response.results,
            raw_response=response.raw_response,
            http_status=response.http_status,
            error_message=response.error_message,
            headers=headers,
        )

    def parse_cached_response(
        self,
        *,
        lookup_type: str,
        normalized_query: str,
        status: str,
        raw_response: JsonValue | None,
        http_status: int | None = None,
        error_message: str | None = None,
    ) -> MetadataLookupResponse:
        if error_message is not None:
            status = "rate_limited" if http_status == 429 else "failed"
            return MetadataLookupResponse(self.name, lookup_type, normalized_query, status, raw_response=raw_response, http_status=http_status, error_message=error_message)
        if not isinstance(raw_response, dict):
            return MetadataLookupResponse(self.name, lookup_type, normalized_query, "malformed", raw_response=raw_response, http_status=http_status, error_message="Expected object response.")
        docs = raw_response.get("docs")
        if not isinstance(docs, list):
            return MetadataLookupResponse(self.name, lookup_type, normalized_query, "malformed", raw_response=raw_response, http_status=http_status, error_message="Expected docs list.")
        results = tuple(result for record in docs if isinstance(record, dict) if (result := self._parse_record(record)) is not None)
        status = "succeeded" if results else "no_results"
        return MetadataLookupResponse(self.name, lookup_type, normalized_query, status, results, raw_response, http_status)

    def _parse_record(self, record: dict[str, Any]) -> MetadataResult | None:
        title = clean_string(record.get("title"))
        if title is None:
            return None
        published_on, publication_year = parse_partial_date(record.get("first_publish_year"))
        isbn_values = tuple(clean_isbn(value) for value in record.get("isbn", []) if isinstance(value, str))
        isbn10 = next((value for value in isbn_values if value is not None and len(value) == 10), None)
        isbn13 = next((value for value in isbn_values if value is not None and len(value) == 13), None)
        cover_id = record.get("cover_i")
        cover_url = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if isinstance(cover_id, int) else None
        publishers = record.get("publisher") if isinstance(record.get("publisher"), list) else []
        subjects = record.get("subject") if isinstance(record.get("subject"), list) else []
        return MetadataResult(
            provider=self.name,
            title=title,
            authors=tuple(cleaned for value in record.get("author_name", []) if (cleaned := clean_string(value)) is not None),
            publisher=clean_string(publishers[0]) if publishers else None,
            published_on=published_on,
            publication_year=publication_year,
            isbn10=isbn10,
            isbn13=isbn13,
            page_count=record.get("number_of_pages_median") if isinstance(record.get("number_of_pages_median"), int) else None,
            cover_url=cover_url,
            categories=tuple(cleaned for value in subjects[:10] if (cleaned := clean_string(value)) is not None),
            provider_record_id=clean_string(record.get("key")),
            confidence=0.95 if isbn13 or isbn10 else 0.7,
            raw_record=record,
        )


class GoogleBooksClient:
    name = "google_books"
    base_url = "https://www.googleapis.com/books/v1/volumes"

    def __init__(self, http_client: JsonHttpClient | None = None, api_key: str | None = None) -> None:
        self.http_client = http_client or JsonHttpClient()
        self.api_key = api_key.strip() if api_key and api_key.strip() else None

    def lookup_isbn(self, isbn: str) -> MetadataLookupResponse:
        normalized_query = normalize_isbn_query(isbn)
        return self._lookup("isbn", normalized_query, {"q": f"isbn:{normalized_query}"})

    def lookup_title_author(self, title: str, author: str | None = None) -> MetadataLookupResponse:
        normalized_query = normalize_title_author_query(title, author)
        query = f"intitle:{title}"
        if clean_string(author) is not None:
            query = f"{query}+inauthor:{author}"
        return self._lookup("title_author", normalized_query, {"q": query})

    def _lookup(self, lookup_type: str, normalized_query: str, params: dict[str, str]) -> MetadataLookupResponse:
        if not normalized_query:
            return MetadataLookupResponse(self.name, lookup_type, normalized_query, "invalid_query", error_message="Missing lookup query.")
        if self.api_key is not None:
            params = {**params, "key": self.api_key}
        raw_response, http_status, headers, error_message = self.http_client.get_json(f"{self.base_url}?{urlencode(params)}")
        response = self.parse_cached_response(
            lookup_type=lookup_type,
            normalized_query=normalized_query,
            status="failed" if error_message is not None else "succeeded",
            raw_response=raw_response,
            http_status=http_status,
            error_message=error_message,
        )
        return MetadataLookupResponse(
            provider=response.provider,
            lookup_type=response.lookup_type,
            normalized_query=response.normalized_query,
            status=response.status,
            results=response.results,
            raw_response=response.raw_response,
            http_status=response.http_status,
            error_message=response.error_message,
            headers=headers,
        )

    def parse_cached_response(
        self,
        *,
        lookup_type: str,
        normalized_query: str,
        status: str,
        raw_response: JsonValue | None,
        http_status: int | None = None,
        error_message: str | None = None,
    ) -> MetadataLookupResponse:
        if error_message is not None:
            status = "rate_limited" if http_status == 429 else "failed"
            return MetadataLookupResponse(self.name, lookup_type, normalized_query, status, raw_response=raw_response, http_status=http_status, error_message=error_message)
        if not isinstance(raw_response, dict):
            return MetadataLookupResponse(self.name, lookup_type, normalized_query, "malformed", raw_response=raw_response, http_status=http_status, error_message="Expected object response.")
        items = raw_response.get("items", [])
        if not isinstance(items, list):
            return MetadataLookupResponse(self.name, lookup_type, normalized_query, "malformed", raw_response=raw_response, http_status=http_status, error_message="Expected items list.")
        results = tuple(result for record in items if isinstance(record, dict) if (result := self._parse_record(record)) is not None)
        status = "succeeded" if results else "no_results"
        return MetadataLookupResponse(self.name, lookup_type, normalized_query, status, results, raw_response, http_status)

    def _parse_record(self, record: dict[str, Any]) -> MetadataResult | None:
        volume_info = record.get("volumeInfo")
        if not isinstance(volume_info, dict):
            return None
        title = clean_string(volume_info.get("title"))
        if title is None:
            return None
        published_on, publication_year = parse_partial_date(volume_info.get("publishedDate"))
        identifiers = volume_info.get("industryIdentifiers", [])
        isbn10 = None
        isbn13 = None
        if isinstance(identifiers, list):
            for identifier in identifiers:
                if not isinstance(identifier, dict):
                    continue
                value = clean_isbn(clean_string(identifier.get("identifier")))
                if identifier.get("type") == "ISBN_10" and value is not None:
                    isbn10 = value
                if identifier.get("type") == "ISBN_13" and value is not None:
                    isbn13 = value
        image_links = volume_info.get("imageLinks") if isinstance(volume_info.get("imageLinks"), dict) else {}
        return MetadataResult(
            provider=self.name,
            title=title,
            subtitle=clean_string(volume_info.get("subtitle")),
            authors=tuple(cleaned for value in volume_info.get("authors", []) if (cleaned := clean_string(value)) is not None),
            publisher=clean_string(volume_info.get("publisher")),
            published_on=published_on,
            publication_year=publication_year,
            isbn10=isbn10,
            isbn13=isbn13,
            page_count=volume_info.get("pageCount") if isinstance(volume_info.get("pageCount"), int) else None,
            cover_url=clean_string(image_links.get("thumbnail") or image_links.get("smallThumbnail")),
            categories=tuple(cleaned for value in volume_info.get("categories", []) if (cleaned := clean_string(value)) is not None),
            description=clean_string(volume_info.get("description")),
            provider_record_id=clean_string(record.get("id")),
            confidence=0.95 if isbn13 or isbn10 else 0.7,
            raw_record=record,
        )
