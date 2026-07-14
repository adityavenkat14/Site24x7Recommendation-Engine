# Site24x7 Dashboard Widget Sync

## What it does
While you're on any Site24x7 dashboard page, this extension quietly reads
the widgets already placed on the grid (title, type, period, data source)
and sends them to your local app at `http://localhost:8000/api/widgets`.
No clicking needed beyond normal browsing — it re-sends automatically
whenever the dashboard changes (you add/remove a widget, switch dashboards, etc).

Nothing is automated on the Site24x7 side — it's your normal, hand-driven
browser tab. The extension only *reads* the page.

## 1. Wire up your app.py (FastAPI)
Open `fastapi_route_snippet.py` — it has 3 parts, follow the comments in the file:

1. Copy the two pydantic model classes (`CapturedWidget`, `LiveWidgetCapturePayload`)
   in next to your other `...Payload(BaseModel)` classes (around line 226-252 in your app.py)
2. Copy `init_live_widgets_table()` in anywhere, and call it once inside your
   existing `init_db()` function
3. Copy the two `@app.post("/api/widgets")` / `@app.get("/api/widgets")`
   functions in anywhere after `app = FastAPI(...)` — e.g. right above
   `if __name__ == "__main__":` at the bottom

No new installs needed — your app already has `sqlite3`, `json`, and CORS
wide open.

Restart your app the way you normally do:
```
python app.py
```

## 2. Load the extension in Chrome
1. Go to `chrome://extensions`
2. Turn on **Developer mode** (top-right toggle)
3. Click **Load unpacked**
4. Select this folder (`s247-widget-extension`)
5. It should appear as "Site24x7 Dashboard Widget Sync" with no errors

## 3. Try it
1. Make sure your app is running (`http://localhost:8000`)
2. Open any Site24x7 dashboard in Chrome, in the same profile where the
   extension is loaded
3. Within ~1.5 seconds it sends the widgets it finds
4. Check `http://localhost:8000/api/widgets` in a browser tab (GET) to see
   what's been captured, or watch your app's console for the print lines

## If nothing shows up
- Open DevTools (F12) → Console on the Site24x7 tab — the extension logs a
  debug message there if it can't reach localhost:8000 (e.g. your app isn't running)
- Confirm the dashboard actually uses `<gridster-item>` elements — this was
  built from a real Website Summary dashboard capture, but if Site24x7
  changes their markup this selector may need updating
- `chrome://extensions` → click "service worker"/"errors" on the extension
  card if it shows a red error badge
