# Clubprogramma: notes for working on this repo

Home Assistant custom integration (`custom_components/clubprogramma`, domain `clubprogramma`) for **LISA**, the club
software most Dutch hockey clubs (and KNLTB tennis clubs) use: a member's and their family's
trainings, matches, team events, duties and attendance, as the LISA club apps and the web app
`mijn.lisahockey.nl` show them. How the API works: docs/api.md.

**Everything in this repo may become public: no personal data.** No names of family members, no real
member numbers, no club of the owner, no tokens. Tests and examples use made-up members and clubs.

Decided (Nov 2026):
- Named **Clubprogramma** (domain `clubprogramma`; "LISA"/`lisa` until 15 Nov 2026) so it doesn't look like
  an official product of LISA Ledeninformatiesystemen B.V.: LISA is named only as the software it connects
  to, with "not affiliated". Same rule as the sibling integrations (Hockeycompetitie, Competitie Voetbal,
  Tenniscompetitie).
- Separate from the KNHB Hockey integration (public match data): different supplier, per-member login,
  personal data, possibly write actions later.
- Same route as LISA's own web app: the public web user (HTTP Basic) that `mijn.lisahockey.nl`
  ships to every visitor, plus the member's token from `auth_tokens`. The Basic credential is read from
  the web app's bundle at runtime, never committed. We do not extract credentials from the mobile apps.
- Attendance can be given (select entities and the `clubprogramma.set_presence` action), added on the owner's request
  on 14 Nov 2026; it changes real data in LISA that the team sees. Signing up for duties is not in it yet.
- One config entry per LISA login (one member, who sees their family). A device per family member.

## Releasing

HACS installs from GitHub releases. For a new version: bump `version` in
`custom_components/clubprogramma/manifest.json`, commit, wait for CI (Tests + Validate) to pass, then
`gh release create vX.Y.Z --title vX.Y.Z --notes "…"` (the tag must match the manifest version; a full release,
not just a tag). A README-only change needs no release. Submitted to the HACS default list on 15 Nov 2026
(hacs/default PR #14207). frenck's review (17 Nov 2026) asked for `member_id` to be redacted in diagnostics,
fixed in v0.1.1: anything that identifies the logged-in member (ids, numbers, names) stays out of diagnostics.
Never ask HACS maintainers for a review unless they ask for one: unsolicited requests get PRs closed.

## Testing locally

Copy `custom_components/clubprogramma` into your Home Assistant `custom_components/` folder and restart Home
Assistant. Personal setup notes belong in `CLAUDE.local.md`, which is git-ignored.
