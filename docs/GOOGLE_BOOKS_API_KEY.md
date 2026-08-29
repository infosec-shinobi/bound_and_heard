# Google Books API Key

Bound & Heard can use Google Books without an API key, but Google may rate-limit unauthenticated requests. Add an API key if ISBN lookup often reports `Google Books: rate limited (429)`.

## Create A Key

1. Open Google Cloud Console: `https://console.cloud.google.com/`.
2. Create or select a Google Cloud project.
3. Open `APIs & Services` > `Library`.
4. Search for `Books API`.
5. Enable `Books API` for the project.
6. Open `APIs & Services` > `Credentials`.
7. Choose `Create credentials` > `API key`.
8. Pick "Public" as the data accessed type
8. Copy the generated key.

## Restrict The Key

Recommended restrictions:

- API restriction: restrict to `Books API`.
- Application restriction: use the least restrictive option that works for your deployment. For local/self-hosted server-side use, IP address restrictions may work if your host has a stable outbound IP. If your IP changes often, leave application restrictions unset and rely on the API restriction.

Do not commit the key to Git.

## Configure Bound & Heard

Add the key to your local `.env` file:

```dotenv
BOUND_AND_HEARD_GOOGLE_BOOKS_API_KEY=your-google-books-api-key
```

Restart the app after changing `.env`.

## Verify

Use the manual add-book screen:

1. Log in as admin.
2. Open `/books/new`.
3. Enter an ISBN.
4. Click `Lookup ISBN`.

If lookup still fails, the UI should show provider attempts such as:

```text
Open Library: no results (200); Google Books: rate limited (429)
```

If Google Books still reports `429` after adding a key, check that the Books API is enabled for the project and that key restrictions allow requests from your deployment host.

If Google Books reports `503`, Google accepted the request path but the Books API was temporarily unavailable. Retry later, or use `Refresh cached provider response` on the add-book lookup form so the app bypasses any cached failed/empty lookup result.
