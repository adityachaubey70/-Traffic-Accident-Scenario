# Traffic Accident Reporting System (Flask + SQLite)

## Run in VS Code
1. Install Python 3.10+ and open this folder in VS Code (File > Open Folder).
2. Open a terminal (Ctrl + `) and run:
   ```
   python -m venv venv
   venv\Scripts\activate          (Windows)   |   source venv/bin/activate   (Mac/Linux)
   pip install -r requirements.txt
   python app.py
   ```
3. Open http://127.0.0.1:5000 in Chrome or Edge.

## Demo logins
admin / admin123 · user1 / user123 · user2 / user123

## Files
- `app.py` - Python backend: login, role checks, validation, duplicate merge, alerts, audit log, SQLite
- `templates/index.html` - page structure
- `static/style.css` - styling
- `static/app.js` - browser code (GPS, photo compression, voice note, offline queue). The browser needs JavaScript for these; HTML/CSS alone cannot do them.
- `accidents.db` and `uploads/` are created automatically on first run (delete them to reset)

## Where each test case is handled (all in app.py unless noted)
| Test | Handled in |
|------|-----------|
| TA_01 location saved | `create_report` |
| TA_02 offline then sync | `send` / `flush` in app.js, `synced` table ignores repeats |
| TA_03 photo compress + upload | `comp` in app.js, `image_ext` checks the real file type |
| TA_04 audio note | `rb.onclick` in app.js, `/uploads/<name>` for playback |
| TA_05 duplicate merge | `create_report` (100 m, 10 min) |
| TA_06 emergency alert | `alert_units` (High severity, 25 km) |
| Future date / fake report / non-image | `create_report` (400 / 409 / 400) |
| Only admin deletes | `login_required(admin=True)` |
| Audit trail | `log()` plus SQLite triggers that block edit/delete |

Change the thresholds at the top of `app.py` to match your SRS.
