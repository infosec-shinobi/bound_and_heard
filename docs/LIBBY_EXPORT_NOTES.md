# Libby 2026 Export Notes

Observed from `libbytimeline-2026-loans,all.json`.

## File Summary

- Top-level keys: `version`, `timeline`
- Version: 1
- Timeline items: 33
- Unique imported book identities by titleId/isbn/format: 30
- Activities: {'Borrowed': 33}
- Formats: {'audiobook': 23, 'ebook': 10}
- Libraries: {'cincinnatilibrary': 30, 'ohdbks': 3}
- Date range UTC: 2026-01-08T20:16:03+00:00 to 2026-06-11T12:35:15+00:00

## Notes

The file contains borrow events only in this sample. It has enough data for MVP 2 import:

- Libby title ID
- Share URL
- Title
- Author
- Publisher
- ISBN
- Format
- Cover URL
- Cover color
- Borrow timestamp
- Library name/key
- Loan duration details

It does not include completion percentage, which supports the need for MVP 3 Playwright progress scraping.
