Strukturnya sudah benar, Bas. Alurnya jelas, phased, dan cukup aman buat dijalanin agent sekali jalan.
Cuma ada beberapa bagian yang perlu dirapihin biar benar-benar production-grade dan gak bikin agent bingung atau salah asumsi.

Di bawah ini versi final revised production-grade task yang sudah diperjelas scope, edge case, dan integrasi dengan sistem yang sudah ada.


---

Contextual Location System + Auto Geolocation

Production Task


---

Goal

Refactor location handling into a context-based system where:

Location is stored inside profile.context as JSON.

Location becomes part of global contextual awareness, not only for weather.

Supports automatic browser geolocation.

Maintains backward compatibility with old latitude and longitude fields.


Location must be usable by:

Weather tool

Context builder

Future awareness features



---

Scope

Files to modify

database.py

app.py

tools/weather.py

web.py

templates/config.html

static/js/config.js


Do NOT modify

Memory schema

Tool registry

Tool execution loop

Message flow

System personality logic

Structured memory system



---

Phase 1 — Database Migration

1. Add context column

In profile table:

ALTER TABLE profile ADD COLUMN context TEXT DEFAULT '{}';

If table creation logic exists, update it to:

context TEXT DEFAULT '{}'


---

2. Safe migration logic

When profile is loaded:

If:

(latitude != 0 OR longitude != 0)
AND context has no location

Then:

Move values into:

context.location = {
  "lat": latitude,
  "lon": longitude
}

Then set:

latitude = 0
longitude = 0

Do NOT remove old columns.


---

Phase 2 — Profile context helpers

Add in database.py:

get_context()

Returns:

dict

Parsed from profile.context.

If invalid JSON:

Return empty dict

Do not crash



---

update_context(context_dict)

Behavior:

1. Convert dict → JSON


2. Store into profile.context




---

Phase 3 — Weather tool adaptation

Modify:

tools/weather.py

Old logic

lat = profile["latitude"]
lon = profile["longitude"]

New logic

context = get_context()
location = context.get("location", {})

lat = location.get("lat", 0)
lon = location.get("lon", 0)

Behavior

If:

lat == 0 or lon == 0

Return:

{ "error": "location_not_set" }

Do not call API.


---

Phase 4 — Context builder awareness

In app.py, inside the system context builder:

If location exists:

Append to system context:

Current location:
Latitude: <lat>
Longitude: <lon>

Rules:

Do NOT modify persona tone.

Do NOT add emotional text.

Only append factual information.



---

Phase 5 — Config UI changes

1. Rename section

From:

Weather Location

To:

Location


---

2. Input IDs

Change input IDs to:

location-lat
location-lon


---

3. Add auto-location button

Under inputs:

[ Use current device location ]

Button ID:

use-current-location


---

Phase 6 — Browser geolocation

In:

static/js/config.js

Add:

function useCurrentLocation() {
    if (!navigator.geolocation) {
        alert("Geolocation not supported.");
        return;
    }

    navigator.geolocation.getCurrentPosition(
        pos => {
            const lat = pos.coords.latitude;
            const lon = pos.coords.longitude;

            document.getElementById("location-lat").value = lat;
            document.getElementById("location-lon").value = lon;
        },
        err => {
            alert("Location permission denied or unavailable.");
        }
    );
}

Bind:

document
  .getElementById("use-current-location")
  .addEventListener("click", useCurrentLocation);


---

Phase 7 — Backend endpoint

In web.py:

New route

POST /api/update_location

Input:

{
  "lat": float,
  "lon": float
}

Behavior:

1. Load profile context.


2. Update:



context["location"] = {
    "lat": lat,
    "lon": lon
}

3. Save using update_context().



Return:

{ "status": "ok" }


---

Phase 8 — Config save logic

When user clicks:

Save Location

Frontend must:

POST:

/api/update_location

With:

{
  "lat": <value>,
  "lon": <value>
}


---

Phase 9 — Testing scenarios

1. Manual location

Enter lat/lon

Save

Reload config


Expected:

Values persist



---

2. Auto location

Click “Use current device location”

Browser permission appears

Values auto-filled

Save

Reload


Expected:

Values persist



---

3. Weather tool

Case A: location set

User:

How’s the weather?

Expected:

Weather tool used

Correct response



---

Case B: no location

User asks weather.

Expected:

Tool returns location_not_set

Model asks for location



---

4. Context awareness

User:

Where am I?

Expected:

Model references stored location

Uses context builder data



---

Expected Result

System now has:

Context-based location storage

Persistent location across reloads

Automatic browser geolocation

Weather tool integrated with context

Location available to system awareness


This becomes the foundation for:

Time-of-day awareness

Environment awareness

Situation-based responses