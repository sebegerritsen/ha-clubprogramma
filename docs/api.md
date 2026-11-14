# LISA's member API

What we know about the API behind LISA's web app for members, found by reading the web app's public
JavaScript bundle (`https://mijn.lisahockey.nl/assets/index-*.js`) and by trying it with a real member
login. Not officially documented; it may change. Last checked: November 2026.

## Hosts and the web app

| | Hockey | Tennis (KNLTB) |
|---|---|---|
| Web app for members | `mijn.lisahockey.nl` | `leden.knltb.club` |
| API | `https://api.lisahockey.nl/api/v1/my` | `https://api.knltb.club/api/v1/my` (same backend) |

The bundle sets `VITE_API_HOCKEY_URL`, `VITE_API_TENNIS_URL` and `VITE_API_AUTHORIZATION`, an HTTP Basic
credential for a public web user that every visitor's browser sends. The integration reads it from the
bundle at runtime; it is not in this repository.

## Requests

- Every request: `Authorization: Basic …` (the public web user) and `Accept: application/json`.
- After login: also `x-lisa-auth-token: <token>`.
- Parameters and bodies in snake_case; answers in snake_case.

## Finding a club and logging in

1. `GET /federations?domain=<web app host>` → `{"id": "<federation id>", "sport": "hockey", "name": …}`.
2. `GET /federations/{federationId}/clubs?name_pattern=X&city_pattern=X` → `{"clubs": [{"club": {"id": "<uuid>",
   "name", "short_name", "city", "federation_code", "has_branded_app", …}}]}`. `federation_code` is the
   KNHB club code.
3. `POST /clubs/{clubId}/auth_tokens` with
   `{"club_membership_number": "<number>", "federation_membership_number": null, "password": "…"}`
   (or the federation number in the other field) → **201**
   `{"login_status": "success", "token": "…", "device_token": null, "has_logged_in_mobile": true,
   "club_member": {"id": "<member uuid>", "interanlid": …}}`. A refused login is **403** with an empty body.
   The token is short and opaque, without an expiry; when it stops working, log in again.
   `DELETE /clubs/{clubId}/auth_tokens/{token}` logs out.
4. `GET /clubs/{clubId}/members/{memberId}` → `{"club_member": {first_name, last_name, …, referee_info,
   custom_roles, is_staff_role_or_captain, …}}`.

## The program

`GET /federations/{federationId}/program?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD` → the timeline of the LISA
apps, for the member **and their family**:

```json
{"pinned_items": [], "tiles": [ … ], "page_end_date": "…Z", "timeline_end_date": "…Z"}
```

It comes in pages: when `page_end_date` is before `to_date`, ask again from `page_end_date`.

Each tile: `type`, `date`, `team_id`, `club_member_id`, `club_member_first_name`, `club_member_full_name`,
`relation_type` (`family`, `none`), `club_id`, and an object named after `type`. Types in the web app's code:
`training`, `match`, `agenda`, `duty`, `referee`, `teamEvent`, `booking`.

- **match**: `id`, `time`, `starts_at`, `ends_at` (null), `meeting_time` (the team's meet time), `is_home`,
  `home_team_name`/`away_team_name` (+ `_short`, `_id`, club `_name`/`_short`/`_logo`/`_id`), `opponent_club_name`,
  `opponent_team`, `location {name, address {street, house_number, house_number_extension, zip_code, city, geo}}`,
  `pitch {name, number, quarters, type}`, `status` (`normal`, …), `result` (a JSON *string*:
  `{"homescore", "awayscore", "homeextratime", …}`), `alternate_kit`, `is_match_time_known`, `presence`,
  `tasks[]`, `match_umpires[]`, `is_member_a_player_in_tile`, `is_member_a_staff_in_tile`, `show_roster`, `pool_id`.
- **training**: `id`, `training_id`, `starts_at`, `ends_at`, `cancelled`, `team_name`, `team_abbreviation`,
  `location`, `pitch`, `trainers[]`, `presence`, `person_staff_roles[] {id, role_name}`, `is_member_a_*_in_tile`.
- **agenda**: `id`, `title`, `starts_at`, `ends_at`, `location` (a string), `sub_location`.
- **presence**: `{status, show_presence_toggle, reactions: {present, absent, unknown}}`; `status` is `unknown`,
  `present` or `absent`; `reactions` counts the team's answers.

## Other routes the web app uses

Under `/clubs/{clubId}/`: `teams` (`personal_teams`, `favourite_teams`), `duties/my`, `duties/{id}/assignments`,
`referees/matches`, `referees/summary`, `trainings`, `matches/{id}`, `team_events`, `events`, `tasks/{id}`,
`members/{id}/tasks/{taskId}/task-assignments`, presence writes under `matches/…/presence` and
`trainings/…/presence`, `invoices`, `documents`. The full list of URL templates is in the bundle (search for
`${this.BASE_URL}`).
