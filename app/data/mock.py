import json
import os

from app.shared.paths import find_repo_root


def load_dashboard():
    repo_root = find_repo_root(os.path.dirname(__file__))
    path = os.path.join(repo_root, "data", "dashboard.json")
    if not os.path.exists(path):
        return {
            "location": "New York",
            "battery": 84,
            "page": 1,
            "page_count": 2,
            "reminder_total": 7,
            "reminder_due": 6,
            "reminders": [
                {"title": "Doctor Appointment", "time": "14:00"},
                {"title": "Yoghurt Expires", "due": "2 Days"},
                {"title": "Morning Yoga", "time": "08:00"},
                {"title": "Buy Milk"},
            ],
            "weather": [
                {"dow": "MON", "icon": "sun", "hi": 22, "lo": 12, "humidity": 45},
                {"dow": "TUE", "icon": "cloud", "hi": 20, "lo": 14, "humidity": 52},
                {"dow": "WED", "icon": "rain", "hi": 18, "lo": 11, "humidity": 68},
                {"dow": "THU", "icon": "storm", "hi": 19, "lo": 13, "humidity": 73},
            ],
        }
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

        # Keep legacy files usable: if reminder_total/page_count are inconsistent with the
        # reminders list, prefer the list (the app-level system derives paging from data).
        reminders = data.get("reminders") or []
        if isinstance(reminders, list):
            data["reminder_total"] = len(reminders)
        data.pop("page_count", None)
        return data
