# Feature: Advanced Search Filters

## Description
Extend the search pages (project search and global search) with faceted filters: date range, owner, measurement type, and instrument.

## Motivation
Users working on large projects with hundreds of datasets need to narrow results by more than just a text query. Currently only a free-text filter exists.

## UI Sketch
- A collapsible "Filters" panel below the search input (or in a left sidebar on wide screens).
- Filter fields:
  - **Date range**: "Created after / before" date pickers (or relative: last 7 days, 30 days, 90 days)
  - **Owner**: dropdown/typeahead populated from the project's user list
  - **Measurement type**: multi-select checkboxes from the distinct measurement values in the project
  - **Instrument**: multi-select from instruments linked to the project
- Active filters shown as removable chips above the results.
- URL-syncable: filters encoded in query params so links can be shared.

## API Endpoints Needed
- `GET /samples?owner_orcid=...&created_after=...` — check nano-crucible SDK for supported filter params.
- `GET /datasets?measurement=...&instrument_id=...` — same.

## Open Questions
- Which filter fields are supported server-side vs. must be done client-side?
- Measurement and instrument lists: fetch from project cache or separate API call?
