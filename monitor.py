#!/usr/bin/env python3
"""Duke of Tokyo Utrecht availability monitor -> ntfy push notifications.

Polls the public booking API for one date/room and pushes to an ntfy topic when
a slot in the wanted time window becomes bookable. Standard library only.

Usage:
  python3 monitor.py              # poll for RUN_MINUTES, every POLL_SECONDS
  python3 monitor.py --once       # single poll
  python3 monitor.py --test       # single poll on a known-available date (2027-01-30)
  python3 monitor.py --dry-run    # print notifications instead of sending them
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Amsterdam")
except Exception:  # pragma: no cover - fallback if tzdata is missing
    TZ = timezone(timedelta(hours=1))

API = "https://panel.dukeoftokyo.com/api/v1"
LOCATION_ID = "7711fe94-fd1c-4e32-81fb-d66e17228b98"  # Utrecht
BOOK_URL = "https://dukeoftokyo.com/locaties/utrecht/utrecht-kalender"
TEST_DATE = "2027-01-30"

TARGET_DATE = os.environ.get("TARGET_DATE") or "2027-02-27"
ROOM_SLUG = os.environ.get("ROOM_SLUG", "akihabara")
PREFERRED = [p.strip() for p in os.environ.get("PREFERRED", "15:45,14:45,17:00").split(",") if p.strip()]
WINDOW_START = os.environ.get("WINDOW_START", "14:30")
WINDOW_END = os.environ.get("WINDOW_END", "19:30")  # latest start time
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "60"))
RUN_MINUTES = float(os.environ.get("RUN_MINUTES", "4.5"))
REPEAT_MINUTES = float(os.environ.get("REPEAT_MINUTES", "3"))  # re-alert interval while slot stays free
HEARTBEAT_HOUR = int(os.environ.get("HEARTBEAT_HOUR", "9"))
ERROR_THRESHOLD = int(os.environ.get("ERROR_THRESHOLD", "3"))
STATE_FILE = os.environ.get("STATE_FILE", "state/state.json")

DAYS_NL = ["ma", "di", "wo", "do", "vr", "za", "zo"]
MONTHS_NL = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
USER_AGENT = "akihabara-slot-monitor/1.0"

DRY_RUN = False


def log(msg):
    print(f"[{datetime.now(TZ):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def nl_date(d):
    return f"{DAYS_NL[d.weekday()]} {d.day} {MONTHS_NL[d.month - 1]}"


def hm_to_min(hm):
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


# ---------------------------------------------------------------- state

def load_state():
    try:
        with open(STATE_FILE) as f:
            all_state = json.load(f)
    except (OSError, ValueError):
        all_state = {}
    return all_state, all_state.setdefault(TARGET_DATE, {})


def save_state(all_state):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(all_state, f, indent=1)


# ---------------------------------------------------------------- API

def fetch_slots(date):
    """Return all time slots for `date` (YYYY-MM-DD). Raises on error or unexpected shape."""
    params = urllib.parse.urlencode({
        "location": LOCATION_ID,
        "start": f"{date}T00:00:00",
        "end": f"{date}T23:59:59",
    })
    url = f"{API}/time-slots/?{params}"
    results = []
    while url:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.load(resp)
        if not body.get("success", False):
            raise RuntimeError(f"API success=false: {body.get('errors')}")
        data = body["data"]
        if isinstance(data, list):
            results.extend(data)
            url = None
        else:
            results.extend(data["results"])
            url = data.get("next")
    for s in results:  # schema check, so a silent API change raises instead of hiding slots
        s["room"]["slug"], s["start_date_time"], s["end_date_time"], s["is_available"]
    return results


def wanted_slots(slots):
    """Slots for our room whose start time falls in the window, sorted by preference."""
    lo, hi = hm_to_min(WINDOW_START), hm_to_min(WINDOW_END)
    out = []
    for s in slots:
        if s["room"]["slug"] != ROOM_SLUG:
            continue
        start = datetime.fromisoformat(s["start_date_time"]).astimezone(TZ)
        if start.date().isoformat() != TARGET_DATE:
            continue
        if lo <= start.hour * 60 + start.minute <= hi:
            out.append(s)

    def rank(s):
        hm = datetime.fromisoformat(s["start_date_time"]).astimezone(TZ).strftime("%H:%M")
        return (PREFERRED.index(hm) if hm in PREFERRED else len(PREFERRED), hm)

    return sorted(out, key=rank)


def slot_label(s):
    start = datetime.fromisoformat(s["start_date_time"]).astimezone(TZ)
    end = datetime.fromisoformat(s["end_date_time"]).astimezone(TZ)
    return f"{start:%H:%M}–{end:%H:%M}"


def slot_price(s):
    p = s.get("price") or {}
    return f"€{p['amount']}" if isinstance(p, dict) and p.get("amount") else ""


# ---------------------------------------------------------------- ntfy

def notify(title, message, priority=3, tags=None, click=BOOK_URL):
    payload = {
        "topic": NTFY_TOPIC,
        "title": title,
        "message": message,
        "priority": priority,
        "tags": tags or [],
    }
    if click:
        payload["click"] = click
        payload["actions"] = [{"action": "view", "label": "Boek nu", "url": click, "clear": False}]
    if DRY_RUN or not NTFY_TOPIC:
        log(f"(dry-run) NOTIFY p{priority}: {title} | {message}")
        return
    req = urllib.request.Request(
        NTFY_SERVER,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read()
    log(f"NOTIFY p{priority}: {title}")


# ---------------------------------------------------------------- one poll

def poll(all_state, st, prefix=""):
    now = datetime.now(TZ)
    target = datetime.fromisoformat(TARGET_DATE)
    day = nl_date(target)
    room = ROOM_SLUG.capitalize()

    try:
        slots = fetch_slots(TARGET_DATE)
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, RuntimeError) as e:
        st["errors"] = st.get("errors", 0) + 1
        log(f"API error #{st['errors']}: {e!r}")
        if st["errors"] >= ERROR_THRESHOLD and not st.get("error_alerted"):
            notify(f"{prefix}⚠️ Duke of Tokyo monitor stuk",
                   f"{st['errors']}x op rij een fout bij het ophalen van de tijdsloten: {e}. "
                   f"Check zelf de kalender en de GitHub Actions-logs.", priority=4, tags=["warning"])
            st["error_alerted"] = True
        return
    if st.get("error_alerted"):
        notify(f"{prefix}✅ Monitor werkt weer", "De API reageert weer normaal.", priority=2, tags=["white_check_mark"])
    st["errors"] = 0
    st["error_alerted"] = False

    mine = wanted_slots(slots)
    free = [s for s in mine if s["is_available"]]
    log(f"{len(slots)} slots voor {TARGET_DATE}; {room} in venster: "
        + (", ".join(f"{slot_label(s)}={'VRIJ' if s['is_available'] else 'bezet'}" for s in mine) or "geen"))

    if free:
        last = st.get("last_free_alert")
        due = not last or now - datetime.fromisoformat(last) >= timedelta(minutes=REPEAT_MINUTES)
        if due:
            best = free[0]
            others = ", ".join(slot_label(s) for s in free[1:])
            msg = f"{room} (12 pers.) {day} {slot_label(best)} {slot_price(best)} is NU boekbaar!"
            if others:
                msg += f" Ook vrij: {others}."
            msg += " Tik om te boeken. (Herhaalt tot je de workflow uitzet.)"
            notify(f"{prefix}🎤 {room.upper()} VRIJ: {day} {slot_label(best)}", msg,
                   priority=5, tags=["rotating_light", "microphone"])
            st["last_free_alert"] = now.isoformat()
        st["released"] = True
    elif slots:
        if not st.get("released_alerted"):
            if mine:
                detail = f"{room} in je venster ({', '.join(slot_label(s) for s in mine)}) is al bezet."
            else:
                detail = f"Er staan sloten online, maar geen {room}-slot tussen {WINDOW_START} en {WINDOW_END}."
            notify(f"{prefix}📅 {day} staat online, {room} niet vrij",
                   f"{detail} Meld je via de kalender aan op de wachtlijst; de monitor blijft checken op annuleringen.",
                   priority=4, tags=["calendar"])
            st["released_alerted"] = True
        st["released"] = True

    # daily heartbeat
    today = now.date().isoformat()
    if now.hour == HEARTBEAT_HOUR and st.get("heartbeat") != today:
        status = ("dag online, " + (f"{len(free)} slot(s) vrij" if free else f"{room} bezet")) if slots else "nog niet online"
        notify(f"{prefix}💓 Monitor draait", f"Check voor {day}: {status}.", priority=2, tags=["heartbeat"], click=None)
        st["heartbeat"] = today


def main():
    global TARGET_DATE, DRY_RUN
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="single poll")
    ap.add_argument("--test", action="store_true", help=f"single poll on {TEST_DATE} (known available)")
    ap.add_argument("--dry-run", action="store_true", help="print notifications instead of sending")
    args = ap.parse_args()
    DRY_RUN = args.dry_run

    prefix = ""
    if args.test:
        TARGET_DATE = TEST_DATE
        prefix = "[TEST] "
    elif TARGET_DATE != "2027-02-27":
        prefix = "[TEST] "

    all_state, st = load_state()
    once = args.once or args.test or RUN_MINUTES <= 0
    deadline = time.monotonic() + RUN_MINUTES * 60
    log(f"Monitor {ROOM_SLUG} op {TARGET_DATE} (venster {WINDOW_START}-{WINDOW_END}, voorkeur {PREFERRED})")
    while True:
        poll(all_state, st, prefix)
        save_state(all_state)
        if once or time.monotonic() + POLL_SECONDS > deadline:
            break
        time.sleep(POLL_SECONDS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
