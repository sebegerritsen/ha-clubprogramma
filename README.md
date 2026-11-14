# LISA for Home Assistant

A [Home Assistant](https://www.home-assistant.io/) integration, installable through [HACS](https://hacs.xyz/),
for **LISA**, the club software most Dutch hockey clubs (and KNLTB tennis clubs) use. Log in with the
member number and password of your club's LISA app, and get your own and your family's trainings, matches,
team events and attendance in Home Assistant.

> **Status: early development (0.1.0).** Not affiliated with or endorsed by LISA.

## What it does

Per family member (a parent sees their children, and their partner if linked) a device with:

| Entity | State | Details |
|---|---|---|
| **Activities** (calendar) | on during an activity | trainings, matches, team events, duties and umpiring; cancelled ones left out |
| **Next activity** | start time | whatever comes first, with its details |
| **Next training** | start time | team, location, address, pitch, trainers, your attendance and how many said yes/no |
| **Next match** | kick-off | opponent, home or away, **the team's meet time**, pitch, alternate kit, tasks, umpires, attendance |
| **Meet time** | when the team meets for the next match | as the team set it in LISA |
| **Next duty**, **Next umpiring** | start time | duties (bar, …) and umpiring in the program |
| **Attendance to give** | number of activities in the next 14 days without an answer | the list, with each `activity_id` |
| **Attendance next training**, **Attendance next match** (select) | present, absent or not given | **changing it tells LISA**; the team sees it |
| **Training today**, **Match today** | on all day | start, meet time, location |

And for the login itself:

| Entity | What |
|---|---|
| **Club agenda** (calendar) | the club's agenda |
| **Activity update** (event) | fires when an activity is *cancelled*, *back on*, *rescheduled*, or gets a *new meet time*, with who and what |

The action **`lisa.set_presence`** (device, `activity_id`, `present`/`absent`/`unknown`) gives attendance
for any training, match or team event, for example from a notification button.

Changes are remembered across restarts, so what changed while Home Assistant was off is still reported.
Dutch and English.

### Blueprints

Ready-made automations that send a notification to your phone (Home Assistant app), in Dutch or English:

| Blueprint | What it does | |
|---|---|---|
| Notify on activity changes | cancelled, back on, rescheduled, new meet time | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fsebegerritsen%2Fha-lisa%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Flisa%2Factivity_update_notify.yaml) |
| Give attendance from a notification | daily at a set time, one notification per activity without an answer, with **Present** / **Absent** buttons that tell LISA | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fsebegerritsen%2Fha-lisa%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Flisa%2Fpresence_buttons.yaml) |
| Reminder before the meet time | a set time before the team meets for the next match, with venue and address | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fsebegerritsen%2Fha-lisa%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Flisa%2Fmeeting_time_reminder.yaml) |

## How it connects

The same way LISA's own web app for members (`mijn.lisahockey.nl`, for tennis `leden.knltb.club`) does:
the web app's public API user plus your member login. The integration reads that public user from the web
app when you set it up (and again if LISA changes it), and logs in again by itself when its session expires.
Your number and password are stored in Home Assistant like any other integration's login. See
[docs/api.md](docs/api.md).

It polls every 15 minutes.

## Installation

Requires Home Assistant 2025.12 or newer.

**HACS** (since Home Assistant 2026.11 part of the built-in *Marketplace*): add
`https://github.com/sebegerritsen/ha-lisa` as a custom repository of type *Integration*, install **LISA**
and restart Home Assistant. **Manually:** copy `custom_components/lisa` into your `custom_components`
folder and restart.

Then *Settings → Devices & services → Add integration → LISA*: pick hockey or tennis, find your club, and log
in with your club membership number (or federation number) and the password of the LISA app.

## Example

A notification when a training is cancelled:

```yaml
triggers:
  - trigger: state
    entity_id: event.my_club_activity_update
conditions:
  - condition: template
    value_template: >-
      {{ trigger.from_state is not none and trigger.from_state.state != 'unavailable'
         and trigger.to_state.attributes.event_type == 'cancelled' }}
actions:
  - action: notify.notify
    data:
      message: >-
        {{ trigger.to_state.attributes.title }} for {{ trigger.to_state.attributes.member }}
        on {{ as_timestamp(trigger.to_state.attributes.start) | timestamp_custom('%a %H:%M') }} is cancelled
```

## Contributing

Issues and pull requests are welcome, in English or Dutch. Tests: `pip install -r requirements_test.txt`,
then `pytest` (Python 3.14). Please don't commit personal data: no real names, member numbers or tokens in
examples or tests.

## License

[MIT](LICENSE)
