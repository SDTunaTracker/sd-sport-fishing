# Co-Captain `/v1/chat` contract (draft v1, NOT deployed)

Shared by the website and the mobile app. The worker owns the system prompt, the tools and the data, and loads data server-side from `https://thetunatracker.com/api/v1/app.json`. The model only chooses ids; **every number in a card is filled from data, never from the model.** The app (claude/app-dev-da24e8, a5a83aa) already types against this.

## Request
`POST https://chatbot.tylerjchristian.workers.dev/v1/chat`
Headers: `Content-Type: application/json`, `X-TT-Client: app|web`
```json
{
  "messages": [{"role": "user", "content": "..."}],
  "context": {"page": "tripplanner", "boat": "Producer", "regions": ["san_diego"]},
  "client": "app", "clientVersion": "1.0.0",
  "installId": "uuid",
  "stream": false
}
```

## Response (`stream:false`)
```json
{
  "text": "prose, no raw URLs",
  "cards": [TripCard | BoatCard],
  "sources": [{"label": "Schedule", "updatedAt": "2026-11-25T01:01:53Z"}],
  "followUps": ["..."]
}
```
With `stream:true`, the same payloads arrive as SSE events: `text` (delta), `cards`, `sources`, `followUps`, `done`, `error`.

### TripCard
| field | type | notes |
|---|---|---|
| type | `"trip"` | |
| tripId | string | `SCHEDULE.sourceId` |
| boat, landing, tripLength | string | `tripLength` is the bucket; H&M ¾-day shows as "¾ Day" |
| departLocal | string | ISO with Pacific offset, e.g. `2026-11-27T20:00:00-08:00` (both source formats are normalized) |
| returnLocal | string \| null | null when not trustworthy (H&M today) |
| price | number | whole dollars, rounded |
| openSpots, capacity | number \| null | |
| spotsAsOf | string | ISO, the scrape time |
| bookingUrl | string \| null | |
| bookingKind | `"exact_trip" \| "trip_type_calendar" \| "call_landing"` | H&M = `trip_type_calendar` (Xola, pick the date) |
| landingPhone | string? | present when `call_landing` |
| targetSpecies, included | string? | from the trip notes |
| why | string[] | ≤3 short, data-backed reasons, e.g. "Last 10 trips: 2.1 yellowfin/angler" |

### BoatCard
| field | type | notes |
|---|---|---|
| type | `"boat"` | |
| boat, landing | string | |
| photoUrl | string? | `BOAT_PROFILES.photoUrl` (site-relative) |
| boatPageUrl | string | `https://thetunatracker.com/boat/<name>` |
| stats | object | `{window: "last10" \| "season", trips, trophyPerAnglerPerDay, winRate?, lastTripDate}` |
| species | object? | `{Yellowfin: {perAngler, trips}, ...}` over the same window; trophy species only |
| nextTrip | TripCard? | soonest open trip, if any |
| upcomingCount | number | open trips scheduled |
| why | string[] | ≤3 data-backed reasons |

## Limits and errors
- No API key in clients. `installId` is a random UUID, used for rate limits and anonymous analytics only.
- About 20 messages per 10 min per IP and per installId; 150 per day per installId; 2,000 chars per message; the last 12 turns are kept.
- `429 {"error":"rate_limited","retryAfter":60}`, `400 {"error":"bad_request"}`, `503 {"error":"upstream"}`.

## Rules (each one is an eval case)
Forecasts are R&D (no predictions). Prices and spots are always "as of" plus "confirm with the landing". No refund or availability promises. Never ask for personal info. Never invent trips, prices or links.
