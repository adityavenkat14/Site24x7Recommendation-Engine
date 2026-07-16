# ─── Add this to your existing app.py ───
# Paste the pydantic models near your other `class ...Payload(BaseModel)`
# definitions (around line 226-252), and the two @app.route functions
# anywhere after `app = FastAPI(...)` is defined (e.g. right before your
# `if __name__ == "__main__":` block at the bottom).
#
# No new pip installs needed — your app already has CORS wide open
# (allow_origins=["*"]) and already imports sqlite3, json, etc.

# ── 1. Pydantic models (put alongside your other Payload classes) ──

class CapturedWidget(BaseModel):
    widget_id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    meta: Optional[dict] = {}

class LiveWidgetCapturePayload(BaseModel):
    widgets: List[CapturedWidget]
    dashboard_url: Optional[str] = None
    dashboard_title: Optional[str] = None
    captured_at: Optional[str] = None


# ── 2. DB setup — call init_live_widgets_table() once inside your
#      existing init_db() function, right before it returns/closes ──

def init_live_widgets_table():
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS live_widget_captures (
            dashboard_url TEXT PRIMARY KEY,
            dashboard_title TEXT,
            widgets_json TEXT NOT NULL,
            captured_at TEXT
        )
    """)
    conn.commit()
    conn.close()


# ── 3. Routes — receive captures from the extension, and list them ──

@app.post("/api/widgets")
def receive_widgets(payload: LiveWidgetCapturePayload):
    if not payload.widgets:
        return {"status": "error", "message": "No widgets in payload."}

    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO live_widget_captures (dashboard_url, dashboard_title, widgets_json, captured_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(dashboard_url) DO UPDATE SET
            dashboard_title = excluded.dashboard_title,
            widgets_json = excluded.widgets_json,
            captured_at = excluded.captured_at
    """, (
        payload.dashboard_url or "unknown",
        payload.dashboard_title,
        json.dumps([w.dict() for w in payload.widgets]),
        payload.captured_at,
    ))
    conn.commit()
    conn.close()

    print(f"[widgets] {payload.dashboard_url}: {len(payload.widgets)} widget(s) captured")
    return {"status": "ok", "stored": len(payload.widgets)}


@app.get("/api/widgets")
def list_captured_dashboards():
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    cursor.execute("SELECT dashboard_url, dashboard_title, widgets_json, captured_at FROM live_widget_captures")
    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "dashboard_url": url,
            "dashboard_title": title,
            "widgets": json.loads(widgets_json),
            "captured_at": captured_at,
        }
        for url, title, widgets_json, captured_at in rows
    ]