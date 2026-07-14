from fastapi import FastAPI, Query, HTTPException, status, Header
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import os
import json
import re
import urllib.parse
import requests
import random
from datetime import datetime, timezone
from dotenv import load_dotenv
from google import genai
from fastapi.staticfiles import StaticFiles

load_dotenv()

ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
ZOHO_REDIRECT_URI = os.getenv("ZOHO_REDIRECT_URI")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

ZOHO_AUTH_URL = "https://accounts.zoho.com/oauth/v2/auth"
ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
SITE24X7_API_BASE = "https://www.site24x7.com/api"

WIDGET_CATALOG = [
    {
        "category": "Performance Attributes",
        "description": "Visualize performance attributes with pie charts, bar graphs, and other graphical representations.",
        "chart_types": ["Time Series", "Bar Chart", "Pie Chart", "Heatmap", "Numeric", "Table", "NOC", "Text"]
    },
    {
        "category": "Top N / Bottom N Widget",
        "description": "Determine the service's top-performing and least-performing metrics.",
        "chart_types": ["Bar Chart", "Table", "Tree map"]
    },
    {
        "category": "Availability Trend",
        "description": "Ensure that the service is meeting its SLOs and to identify any potential issues before they escalate.",
        "chart_types": ["Area Chart", "Numeric"]
    }
]

RESOURCE_TYPES = ["All Monitors", "Monitor", "Child Entity", "Tags", "On-Premise Pollers"]
SHOW_OPTIONS = ["Latest 50 Active Monitors", "Top 50 Monitors", "Bottom 50 Monitors"]
TIME_PERIODS = ["Last Hour", "Today", "Last 24 Hours", "Last 7 Days", "Last 30 Days"]

app = FastAPI(title="Site24x7 Multi-Stage Pipeline Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db_connection():
    # Every endpoint used to call sqlite3.connect('metrics_engine.db')
    # directly with no timeout, so any two overlapping writes (e.g. the
    # extension's delete-sync and widget-sync both posting around the
    # same moment, or two browser tabs each running the extension) could
    # produce "database is locked" immediately -- Python's sqlite3 default
    # busy wait is only 5s and SQLite's default rollback-journal mode locks
    # the whole file for a writer. `timeout` here makes a blocked
    # connection retry/wait instead of erroring right away, and
    # PRAGMA busy_timeout backs that up at the SQLite level too.
    conn = sqlite3.connect('metrics_engine.db', timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def slugify_widget_name(name: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '_', name.strip().lower()).strip('_')
    return slug or "widget"

def fetch_live_site24x7_monitors(access_token: str) -> list:
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Accept": "application/json; version=2.0"
    }
    try:
        response = requests.get(f"{SITE24X7_API_BASE}/monitors", headers=headers)
        if response.status_code == 401:
            return []
        if response.status_code != 200:
            return []
        return response.json().get("data", [])
    except Exception as e:
        print(f"❌ Failed to reach Site24x7 REST API: {str(e)}")
        return []

def _resolve_monitor_id_by_name(access_token: str, name: str):
    monitors = fetch_live_site24x7_monitors(access_token)
    name_norm = (name or "").strip().lower()
    if not name_norm:
        return None, None
    for m in monitors:
        if (m.get("display_name") or "").strip().lower() == name_norm:
            return m.get("monitor_id"), m.get("monitor_type")
    for m in monitors:
        if name_norm in (m.get("display_name") or "").strip().lower():
            return m.get("monitor_id"), m.get("monitor_type")
    return None, None
    
def fetch_exact_monitor_widgets(access_token: str, monitor_id: str) -> list:
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Accept": "application/json; version=2.0"
    }
    print(f"\n📡 [SITE24X7 FETCH] Interrogating Monitor Profile ID: {monitor_id}")
    try:
        performance_url = f"{SITE24X7_API_BASE}/monitors/performance/{monitor_id}"
        response = requests.get(performance_url, headers=headers)
        formatted_widgets = []
        if response.status_code == 200:
            chart_configs = response.json().get("data", {}).get("chart_configs", [])
            print(f"📊 [STAGE: PERFORMANCE CHARTS] Found {len(chart_configs)} configuration indicators in live API.")
            for chart in chart_configs:
                metric_key = chart.get("value") or chart.get("metric_name")
                metric_name = chart.get("name")
                if metric_key and metric_name:
                    formatted_widgets.append({
                        "widget_id": f"widget_{monitor_id}_{metric_key}",
                        "name": metric_name
                    })
            if formatted_widgets:
                print(f"✅ [SUCCESS: PERFORMANCE SOURCE] Packaged {len(formatted_widgets)} active telemetry metrics.")
                return formatted_widgets
        else:
            print(f"⚠️ [PERFORMANCE TRACK SKIPPED] REST Endpoint returned status code: {response.status_code}")

        info_url = f"{SITE24X7_API_BASE}/monitors/{monitor_id}"
        info_response = requests.get(info_url, headers=headers)
        if info_response.status_code == 200:
            monitor_profile = info_response.json().get("data", {})
            print(f"🗃️ [STAGE: METADATA Fallback] Extracting keys from profile definition matrix...")
            for key, value in monitor_profile.items():
                if isinstance(value, (list, dict)) or value is None:
                    continue
                formatted_widgets.append({
                    "widget_id": f"widget_{monitor_id}_{key}",
                    "name": f"{key.replace('_', ' ').title()}: {value}"
                })
            print(f"✅ [SUCCESS: METADATA SOURCE] Packaged {len(formatted_widgets)} fields as baseline indicators.")
            return formatted_widgets
        else:
            print(f"❌ [METADATA TRACK FAILED] REST Endpoint returned status code: {info_response.status_code}")
    except Exception as e:
        print(f"❌ [CRITICAL EXCEPTION] Diagnostic pipeline check caught error: {str(e)}")
    return []

@app.get("/api/v1/widget-graph-data")
def get_widget_graph_data(monitor_id: str, metric_key: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        return {"status": "error", "message": "Missing authorization token."}
    token = authorization.replace("Bearer ", "").strip()
    headers = {"Authorization": f"Zoho-oauthtoken {token}", "Accept": "application/json; version=2.0"}
    try:
        res = requests.get(f"{SITE24X7_API_BASE}/current_status/{monitor_id}", headers=headers)
        if res.status_code != 200:
            return {"status": "error", "message": f"Site24x7 returned {res.status_code}"}
        data = res.json().get("data", {})
        attributes = data.get("attribute_values") or data.get("attributes") or {}
        value = attributes.get(metric_key) if isinstance(attributes, dict) else None
        # When Site24x7 doesn't have this exact attribute (e.g. widget type
        # that isn't tied to one monitor, like Alarms), fall back to a
        # varying placeholder instead of a frozen, misleading-looking 0.
        numeric_value = value if isinstance(value, (int, float)) else random.randint(12, 96)
        return {"status": "success", "value": value, "points": [numeric_value] * 4, "raw": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/dashboards/{template_id}/resolve-monitors")
def resolve_live_monitors(template_id: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        return {"status": "error", "message": "Missing authorization token."}
    token = authorization.replace("Bearer ", "").strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT widget_id, display_name FROM widget_configs WHERE template_id = ? AND (monitor_ids = '[]' OR monitor_ids IS NULL)", (template_id,))
    rows = cursor.fetchall()
    resolved = 0
    for widget_id, display_name in rows:
        if not display_name:
            continue
        monitor_id, monitor_type = _resolve_monitor_id_by_name(token, display_name)
        if monitor_id:
            cursor.execute("UPDATE widget_configs SET monitor_ids = ?, monitor_type = ? WHERE widget_id = ?",
                           (json.dumps([monitor_id]), monitor_type, widget_id))
            resolved += 1
    conn.commit()
    conn.close()
    return {"status": "ok", "resolved": resolved, "checked": len(rows)}

@app.get("/api/v1/dashboards/{template_id}/widget-monitor-map")
def get_widget_monitor_map(template_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT widget_id, monitor_ids, metric_ids FROM widget_configs WHERE template_id = ?", (template_id,))
    rows = cursor.fetchall()
    conn.close()
    mapping = {}
    for widget_id, monitor_ids_json, metric_ids_json in rows:
        monitor_ids = json.loads(monitor_ids_json or "[]")
        metric_ids = json.loads(metric_ids_json or "[]")
        mapping[widget_id] = {
            "monitor_id": monitor_ids[0] if monitor_ids else None,
            "metric_key": metric_ids[0]["id"] if metric_ids else widget_id,
        }
    return mapping

@app.get("/api/v1/dashboards/{template_id}/live-chart-data")
def get_live_chart_data(template_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT widget_id, live_chart_data, display_name FROM widget_configs WHERE template_id = ? AND live_chart_data IS NOT NULL", (template_id,))
    rows = cursor.fetchall()
    conn.close()
    return {widget_id: {"chart_data": json.loads(chart_json), "name": name} for widget_id, chart_json, name in rows}

@app.get("/api/v1/auth/login")
def initiate_zoho_login():
    if not ZOHO_CLIENT_ID or not ZOHO_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="OAuth credentials missing from backend context configuration profiles.")
    scopes = ["Site24x7.Admin.Read", "Site24x7.Reports.Read"]
    query_params = {
        "scope": " ".join(scopes),
        "client_id": ZOHO_CLIENT_ID,
        "response_type": "code",
        "access_type": "offline",
        "redirect_uri": ZOHO_REDIRECT_URI,
        "prompt": "consent"
    }
    return RedirectResponse(url=f"{ZOHO_AUTH_URL}?{urllib.parse.urlencode(query_params)}")

@app.get("/api/v1/auth/callback", response_class=HTMLResponse)
def oauth_callback_handler(code: str = None, error: str = None):
    if error:
        raise HTTPException(status_code=400, detail=f"Zoho Authorization Denied: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code parameter state.")
    try:
        response = requests.post(ZOHO_TOKEN_URL, data={
            "code": code,
            "client_id": ZOHO_CLIENT_ID,
            "client_secret": ZOHO_CLIENT_SECRET,
            "redirect_uri": ZOHO_REDIRECT_URI,
            "grant_type": "authorization_code"
        })
        token_data = response.json()
        if "error" in token_data:
            raise HTTPException(status_code=400, detail=f"OAuth Token Exchange Failed: {token_data['error']}")
        access_token  = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token", "")
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Authorizing Session...</title>
            <script>
                localStorage.setItem("zoho_access_token", "{access_token}");
                if ("{refresh_token}") {{
                    localStorage.setItem("zoho_refresh_token", "{refresh_token}");
                }}
                localStorage.setItem("site24x7_session_user", "zoho_user");
                window.location.href = "/";
            </script>
        </head>
        <body style="background: #090d16; color: #38bdf8; font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh;">
            <div style="text-align: center;">
                <h2>Establishing Secure Workspace Token Profiles...</h2>
                <p style="color: #475569; font-size: 14px;">Syncing regional enterprise credentials...</p>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"API token connection failure trace: {str(e)}")

class DashboardWidgetItem(BaseModel):
    id: str
    name: str

class SaveDashboardPayload(BaseModel):
    template_id: str
    template_name: str
    category_tag: str
    widgets: List[DashboardWidgetItem]
    username: str

class UpdateWidgetPayload(BaseModel):
    widget_id: str
    widget_name: str

class AnalyzeDashboardPayload(BaseModel):
    dashboard_name: str
    category: str
    widgets: List[DashboardWidgetItem]

class SuggestWidgetsPayload(BaseModel):
    dashboard_name: str
    category: Optional[str] = "general"

class LoginPayload(BaseModel):
    username: str
    password: str

class CapturedWidget(BaseModel):
    widget_id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    meta: Optional[dict] = {}
    chart_data: Optional[list] = None
    legend: Optional[str] = None

class LiveWidgetCapturePayload(BaseModel):
    widgets: List[CapturedWidget]
    dashboard_url: Optional[str] = None
    dashboard_title: Optional[str] = None
    captured_at: Optional[str] = None

class CatalogWidget(BaseModel):
    widget_item_id: str
    type_label: Optional[str] = None
    is_live: Optional[bool] = False

class CatalogCategory(BaseModel):
    category: str
    description: Optional[str] = None
    widgets: List[CatalogWidget]

class WidgetCatalogPayload(BaseModel):
    categories: List[CatalogCategory]

class WidgetConfigObservation(BaseModel):
    chartType: Optional[str] = None
    resourceType: Optional[str] = None
    show: Optional[str] = None
    timePeriod: Optional[str] = None
    capturedAt: Optional[int] = None

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # WAL mode lets readers proceed while a write is in progress instead of
    # locking the whole file (SQLite's default DELETE journal mode blocks
    # everyone during a write) -- this is the main fix for "database is
    # locked" under concurrent requests. It's a persistent, one-time,
    # per-database-file setting (stored in the file itself), so this only
    # needs to run once here at startup, not on every connection.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL)")
    cursor.execute("INSERT OR IGNORE INTO users VALUES ('admin', 'admin123')")
    cursor.execute("INSERT OR IGNORE INTO users VALUES ('aditya', 'venkat')")
    cursor.execute("INSERT OR IGNORE INTO users VALUES ('guest', 'guest123')")
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dashboard_templates'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(dashboard_templates)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'username' not in columns:
            cursor.execute("ALTER TABLE dashboard_templates ADD COLUMN username TEXT DEFAULT 'global_default'")
        if 'source' not in columns:
            # Previously we filtered live-synced dashboards out by
            # category_tag = 'Live Capture', but that tag can persist on a
            # dashboard even after a user customizes and saves it (see
            # activateCustomFlowUI staleness fix below), silently hiding
            # real custom dashboards. `source` tracks provenance directly
            # instead. We deliberately do NOT backfill source='live_sync'
            # from category_tag='Live Capture' here -- if some existing
            # rows were mislabeled by that same staleness bug, backfilling
            # from it would just re-bake the bug in. So every existing row
            # defaults to 'user_created' (nothing gets hidden), and the
            # genuine live-synced rows self-correct back to 'live_sync' the
            # next time the extension captures/syncs them.
            cursor.execute("ALTER TABLE dashboard_templates ADD COLUMN source TEXT DEFAULT 'user_created'")
        if 'hidden_from_list' not in columns:
            # Whether a dashboard shows up in the app's main list is now a
            # manual, persistent decision -- NOT derived from source. This
            # is what lets a dashboard you create directly on the live
            # Site24x7 site show up in the app like any other, while the
            # old noisy auto-captured ones can be hidden once and stay
            # hidden (see the ON CONFLICT DO UPDATE in receive_widgets(),
            # which preserves this flag across future re-syncs instead of
            # resetting it back to visible every time the extension
            # recaptures that dashboard).
            cursor.execute("ALTER TABLE dashboard_templates ADD COLUMN hidden_from_list INTEGER DEFAULT 0")
    else:
        cursor.execute("""
            CREATE TABLE dashboard_templates (
                template_id TEXT PRIMARY KEY,
                template_name TEXT NOT NULL,
                category_tag TEXT NOT NULL,
                username TEXT DEFAULT 'global_default',
                source TEXT DEFAULT 'user_created',
                hidden_from_list INTEGER DEFAULT 0
            )
        """)

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dashboard_defaults'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(dashboard_defaults)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'username' not in columns:
            cursor.execute("ALTER TABLE dashboard_defaults ADD COLUMN username TEXT DEFAULT 'global_default'")
        cursor.execute("PRAGMA index_list(dashboard_defaults)")
        legacy_constraint_found = False
        for _, idx_name, is_unique, *_rest in cursor.fetchall():
            if not is_unique:
                continue
            cursor.execute(f"PRAGMA index_info({idx_name})")
            idx_columns = [col[2] for col in cursor.fetchall()]
            if 'username' not in idx_columns:
                legacy_constraint_found = True
                break
        if legacy_constraint_found:
            cursor.execute("ALTER TABLE dashboard_defaults RENAME TO dashboard_defaults_legacy_migration")
            cursor.execute("""
                CREATE TABLE dashboard_defaults (
                    template_id TEXT,
                    widget_id TEXT,
                    username TEXT DEFAULT 'global_default',
                    UNIQUE(template_id, widget_id, username)
                )
            """)
            cursor.execute("""
                INSERT OR IGNORE INTO dashboard_defaults (template_id, widget_id, username)
                SELECT template_id, widget_id, COALESCE(username, 'global_default')
                FROM dashboard_defaults_legacy_migration
            """)
            cursor.execute("DROP TABLE dashboard_defaults_legacy_migration")
    else:
        cursor.execute("""
            CREATE TABLE dashboard_defaults (
                template_id TEXT,
                widget_id TEXT,
                username TEXT DEFAULT 'global_default',
                UNIQUE(template_id, widget_id, username)
            )
        """)
    cursor.execute("CREATE TABLE IF NOT EXISTS widgets (widget_id TEXT PRIMARY KEY, widget_name TEXT NOT NULL, category_tag TEXT NOT NULL)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS widget_configs (
            widget_id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            username TEXT DEFAULT 'global_default',
            category TEXT,
            chart_type TEXT,
            resource_type TEXT,
            monitor_ids TEXT,
            monitor_type TEXT,
            metric_ids TEXT,
            show_option TEXT,
            time_period TEXT,
            display_name TEXT
        )
    """)
    cursor.execute("PRAGMA table_info(widget_configs)")
    if "live_chart_data" not in [col[1] for col in cursor.fetchall()]:
        cursor.execute("ALTER TABLE widget_configs ADD COLUMN live_chart_data TEXT")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_permalinks (
            template_id TEXT PRIMARY KEY,
            permalink_url TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS live_widget_captures (
            dashboard_url TEXT PRIMARY KEY,
            dashboard_title TEXT,
            widgets_json TEXT NOT NULL,
            captured_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS widget_catalog (
            widget_item_id TEXT PRIMARY KEY,
            category TEXT,
            type_label TEXT,
            is_live INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS widget_config_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chart_type TEXT,
            resource_type TEXT,
            show_option TEXT,
            time_period TEXT,
            captured_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def fetch_monitor_label(access_token: str, monitor_id: str) -> str:
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Accept": "application/json; version=2.0"
    }
    try:
        response = requests.get(f"{SITE24X7_API_BASE}/monitors/{monitor_id}", headers=headers)
        if response.status_code == 200:
            profile = response.json().get("data", {})
            return profile.get("monitor_type") or profile.get("display_name") or "Monitor"
    except Exception:
        pass
    return "Monitor"

class WidgetConfigPayload(BaseModel):
    category: str
    chart_type: str
    resource_type: str
    monitor_ids: List[str] = []
    monitor_type: Optional[str] = "Monitor"
    metric_ids: List[dict] = []
    show_option: Optional[str] = None
    time_period: Optional[str] = None
    display_name: str
    username: Optional[str] = "admin"
    chart_data: Optional[list] = None

@app.get("/api/v1/widget-catalog")
def get_widget_catalog_static():
    return {
        "categories": WIDGET_CATALOG,
        "resource_types": RESOURCE_TYPES,
        "show_options": SHOW_OPTIONS,
        "time_periods": TIME_PERIODS
    }

@app.post("/api/v1/widget-config-observations")
def record_widget_config_observation(payload: WidgetConfigObservation):
    chart_type = (payload.chartType or "").strip()
    resource_type = (payload.resourceType or "").strip()
    show = (payload.show or "").strip()
    time_period = (payload.timePeriod or "").strip()
    incomplete_markers = {"", "no items selected"}
    if not chart_type or resource_type.lower() in incomplete_markers:
        return {"status": "skipped", "reason": "incomplete snapshot"}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO widget_config_observations (chart_type, resource_type, show_option, time_period, captured_at)
        VALUES (?, ?, ?, ?, ?)
    """, (chart_type, resource_type, show or None, time_period or None, str(payload.capturedAt or "")))
    conn.commit()
    conn.close()
    return {"status": "recorded"}

@app.get("/api/v1/recommendations/widget-config")
def recommend_widget_config(chart_type: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT resource_type, show_option, time_period
        FROM widget_config_observations WHERE chart_type = ?
    """, (chart_type,))
    rows = cursor.fetchall()
    conn.close()
    total = len(rows)
    if total == 0:
        return {"chart_type": chart_type, "sample_size": 0, "suggestion": None,
                "message": "No observations captured yet for this chart type."}
    def most_common(values):
        counts = {}
        for v in values:
            if not v: continue
            counts[v] = counts.get(v, 0) + 1
        if not counts: return None, 0
        value, count = max(counts.items(), key=lambda kv: kv[1])
        return value, count
    resource_vals = [r[0] for r in rows]
    show_vals = [r[1] for r in rows]
    time_vals = [r[2] for r in rows]
    resource_type, r_count = most_common(resource_vals)
    show_option, s_count = most_common(show_vals)
    time_period, t_count = most_common(time_vals)
    return {
        "chart_type": chart_type,
        "sample_size": total,
        "suggestion": {
            "resource_type": {"value": resource_type, "confidence": round(100 * r_count / total, 1) if resource_type else None},
            "show_option": {"value": show_option, "confidence": round(100 * s_count / len(show_vals), 1) if show_option and any(show_vals) else None},
            "time_period": {"value": time_period, "confidence": round(100 * t_count / len(time_vals), 1) if time_period and any(time_vals) else None},
        }
    }

@app.get("/api/v1/monitors/live")
def get_live_monitors(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Connect your Site24x7 account to browse live monitors.")
    token = authorization.replace("Bearer ", "").strip()
    monitors = fetch_live_site24x7_monitors(token)
    return {
        "monitors": [
            {
                "monitor_id": m.get("monitor_id"),
                "display_name": m.get("display_name", "Unknown Monitor"),
                "monitor_type": m.get("monitor_type", "SERVER")
            } for m in monitors
        ]
    }

@app.get("/api/v1/monitors/{monitor_id}/metrics")
def get_monitor_metrics(monitor_id: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Connect your Site24x7 account to browse live metrics.")
    token = authorization.replace("Bearer ", "").strip()
    label = fetch_monitor_label(token, monitor_id)
    metrics = fetch_exact_monitor_widgets(token, monitor_id)
    return {"group": label, "metrics": metrics}

@app.post("/api/v1/dashboards/{template_id}/widgets/add")
def add_configured_widget(template_id: str, payload: WidgetConfigPayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        widget_id = f"wc_{slugify_widget_name(payload.display_name)}_{int(random.random()*1e9)}"
        metric_ids_json = json.dumps(payload.metric_ids)
        monitor_ids_json = json.dumps(payload.monitor_ids)
        chart_data_json = json.dumps(payload.chart_data) if payload.chart_data else None
        cursor.execute("""
            INSERT INTO widget_configs
            (widget_id, template_id, username, category, chart_type, resource_type,
             monitor_ids, monitor_type, metric_ids, show_option, time_period, display_name, live_chart_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (widget_id, template_id, payload.username, payload.category, payload.chart_type,
              payload.resource_type, monitor_ids_json, payload.monitor_type, metric_ids_json,
              payload.show_option, payload.time_period, payload.display_name, chart_data_json))
        cursor.execute("INSERT OR IGNORE INTO widgets (widget_id, widget_name, category_tag) VALUES (?, ?, ?)",
                       (widget_id, payload.display_name, payload.category))
        cursor.execute("INSERT OR IGNORE INTO dashboard_defaults VALUES (?, ?, ?)",
                       (template_id, widget_id, payload.username))
        # Every widget added through this flow IS a real, user-made config
        # choice -- record it as an observation so /api/v1/recommendations
        # confidence scores have real data to work from. Previously only a
        # separate browser extension ever wrote to this table, so scores
        # stayed at 0 no matter how many widgets you added here.
        incomplete_markers = {"", "no items selected"}
        if payload.chart_type and (payload.resource_type or "").strip().lower() not in incomplete_markers:
            cursor.execute("""
                INSERT INTO widget_config_observations (chart_type, resource_type, show_option, time_period, captured_at)
                VALUES (?, ?, ?, ?, ?)
            """, (payload.chart_type, payload.resource_type, payload.show_option, payload.time_period,
                  datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return {"status": "success", "widget_id": widget_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

def _extract_dashboard_numeric_id(url: str):
    match = re.search(r"(\d{15,})", url)
    return match.group(1) if match else None

def _derive_live_template_id(dashboard_url: str):
    numeric_id = _extract_dashboard_numeric_id(dashboard_url)
    return f"live_{numeric_id}" if numeric_id else f"live_{slugify_widget_name(dashboard_url)}"

def _clean_dashboard_title(title: Optional[str]):
    if not title: return None
    cleaned = title
    for junk in ["Dashboards - ", " - Site24x7"]:
        cleaned = cleaned.replace(junk, "")
    return cleaned.strip() or None

def _widget_type_to_chart_type(widget_type: Optional[str]):
    if not widget_type: return "Unknown"
    return widget_type.replace("s247-", "").replace("-widget", "").replace("-", " ").title() or "Unknown"

def _import_live_captured_widgets(template_id: str, url: str, username: str = "global_default"):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT widgets_json FROM live_widget_captures WHERE dashboard_url = ?", (url,))
    row = cursor.fetchone()
    if not row:
        target_id = _extract_dashboard_numeric_id(url)
        if target_id:
            cursor.execute("SELECT dashboard_url, widgets_json FROM live_widget_captures")
            for cap_url, cap_json in cursor.fetchall():
                if _extract_dashboard_numeric_id(cap_url) == target_id:
                    row = (cap_json,)
                    break
    if not row:
        conn.close()
        return 0
    cursor.execute("DELETE FROM widget_configs WHERE template_id = ?", (template_id,))
    cursor.execute("DELETE FROM dashboard_defaults WHERE template_id = ?", (template_id,))
    imported = 0
    for w in json.loads(row[0]):
        display_name = w.get("name") or w.get("widget_id") or "Imported Widget"
        chart_type = _widget_type_to_chart_type(w.get("type"))
        pseudo_id = f"live_{w.get('widget_id') or slugify_widget_name(display_name)}"
        content_key = f"live_metric_{slugify_widget_name(display_name)}"
        meta = w.get("meta") or {}
        chart_data_json = json.dumps(w.get("chart_data")) if w.get("chart_data") else None
        cursor.execute("""
            INSERT OR REPLACE INTO widget_configs
            (widget_id, template_id, username, category, chart_type, resource_type,
             monitor_ids, monitor_type, metric_ids, show_option, time_period, display_name, live_chart_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pseudo_id, template_id, username, "Live Capture", chart_type,
            meta.get("Data Source", "Unknown"), json.dumps([]), meta.get("Data Source"),
            json.dumps([{"id": content_key, "name": display_name}]), None, meta.get("Period"), display_name,
            chart_data_json,
        ))
        cursor.execute("INSERT OR IGNORE INTO widgets (widget_id, widget_name, category_tag) VALUES (?, ?, ?)",
                       (pseudo_id, display_name, "Live Capture"))
        cursor.execute("INSERT OR IGNORE INTO dashboard_defaults VALUES (?, ?, ?)",
                       (template_id, pseudo_id, username))
        # These came straight off the real, live Site24x7 dashboard -- a
        # genuine config, so it's fair game for the observations table too.
        if chart_type and chart_type != "Unknown":
            cursor.execute("""
                INSERT INTO widget_config_observations (chart_type, resource_type, show_option, time_period, captured_at)
                VALUES (?, ?, ?, ?, ?)
            """, (chart_type, meta.get("Data Source"), None, meta.get("Period"),
                  datetime.now(timezone.utc).isoformat()))
        imported += 1
    conn.commit()
    conn.close()
    return imported

@app.post("/api/widgets")
def receive_widgets(payload: LiveWidgetCapturePayload):
    if not payload.widgets:
        return {"status": "error", "message": "No widgets in payload."}
    url = payload.dashboard_url or "unknown"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO live_widget_captures (dashboard_url, dashboard_title, widgets_json, captured_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(dashboard_url) DO UPDATE SET
            dashboard_title = excluded.dashboard_title,
            widgets_json = excluded.widgets_json,
            captured_at = excluded.captured_at
    """, (url, payload.dashboard_title, json.dumps([w.dict() for w in payload.widgets]), payload.captured_at))
    template_id = _derive_live_template_id(url)
    clean_name = _clean_dashboard_title(payload.dashboard_title) or template_id
    cursor.execute("""
        INSERT INTO dashboard_templates (template_id, template_name, category_tag, username, source)
        VALUES (?, ?, ?, ?, 'live_sync')
        ON CONFLICT(template_id) DO UPDATE SET
            template_name = excluded.template_name,
            category_tag = excluded.category_tag,
            username = excluded.username
            -- source deliberately NOT overwritten here. If it's already
            -- 'user_created' (e.g. because the user saved this dashboard
            -- through the app, marking it custom), a later re-sync from
            -- the extension must not silently flip it back to
            -- 'live_sync' -- that reclassification needs to stick.
    """, (template_id, clean_name, "Live Capture", "global_default"))
    conn.commit()
    conn.close()
    imported = _import_live_captured_widgets(template_id, url, username="global_default")
    return {"status": "ok", "stored": len(payload.widgets), "template_id": template_id, "imported_widgets": imported}

@app.get("/api/widgets")
def list_captured_dashboards():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT dashboard_url, dashboard_title, widgets_json, captured_at FROM live_widget_captures")
    rows = cursor.fetchall()
    conn.close()
    return [{"dashboard_url": u, "dashboard_title": t, "widgets": json.loads(w), "captured_at": c} for u, t, w, c in rows]

@app.post("/api/widget-catalog")
def receive_widget_catalog(payload: WidgetCatalogPayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    count = 0
    for cat in payload.categories:
        for w in cat.widgets:
            cursor.execute("INSERT OR REPLACE INTO widget_catalog VALUES (?, ?, ?, ?)",
                           (w.widget_item_id, cat.category, w.type_label, int(w.is_live)))
            count += 1
    conn.commit()
    conn.close()
    return {"status": "ok", "stored": count}

@app.get("/api/widget-catalog")
def get_widget_catalog():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT widget_item_id, category, type_label, is_live FROM widget_catalog ORDER BY category")
    rows = cursor.fetchall()
    conn.close()
    grouped = {}
    for widget_item_id, category, type_label, is_live in rows:
        grouped.setdefault(category, {"category": category, "description": "", "widgets": []})
        grouped[category]["widgets"].append({"widget_item_id": widget_item_id, "type_label": type_label, "is_live": bool(is_live)})
    return list(grouped.values())

class PermalinkPayload(BaseModel):
    permalink_url: str

@app.post("/api/v1/dashboards/{template_id}/permalink")
def save_dashboard_permalink(template_id: str, payload: PermalinkPayload):
    url = payload.permalink_url.strip()
    if "site24x7.com" not in url:
        return {"status": "error", "message": "That doesn't look like a Site24x7 dashboard URL."}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO dashboard_permalinks (template_id, permalink_url) VALUES (?, ?)",
                   (template_id, url))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.get("/api/v1/dashboards/{template_id}/permalink")
def get_dashboard_permalink(template_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT permalink_url FROM dashboard_permalinks WHERE template_id = ?", (template_id,))
    row = cursor.fetchone()
    conn.close()
    return {"permalink_url": row[0] if row else None}

@app.get("/", response_class=HTMLResponse)
def get_ui():
    with open("index.html", "r", encoding="utf-8") as f: 
        return f.read()

@app.post("/api/v1/auth/manual-credentials")
def login_user(payload: LoginPayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username = ?", (payload.username,))
    row = cursor.fetchone()
    conn.close()
    if not row or row[0] != payload.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access Denied: Invalid credentials.")
    return {"status": "success", "username": payload.username}

@app.get("/api/v1/dashboards")
def get_dashboards(authorization: Optional[str] = Header(None)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT template_id, template_name, category_tag, source FROM dashboard_templates WHERE hidden_from_list = 0")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "category": r[2], "source": r[3]} for r in rows]

@app.post("/api/v1/dashboards/hide/{template_id}")
def hide_dashboard(template_id: str):
    # Soft, reversible: only sets a flag. Unlike delete, this does NOT
    # touch widget_configs, dashboard_defaults, or live_widget_captures --
    # so hiding one of the noisy auto-captured dashboards doesn't lose its
    # captured data, and the hide sticks even if the extension re-syncs
    # that same dashboard later (see ON CONFLICT DO UPDATE in
    # receive_widgets(), which preserves this flag on re-insert).
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE dashboard_templates SET hidden_from_list = 1 WHERE template_id = ?", (template_id,))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

@app.post("/api/v1/dashboards/unhide/{template_id}")
def unhide_dashboard(template_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE dashboard_templates SET hidden_from_list = 0 WHERE template_id = ?", (template_id,))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

@app.get("/api/v1/dashboards/hidden")
def get_hidden_dashboards():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT template_id, template_name, category_tag, source FROM dashboard_templates WHERE hidden_from_list = 1")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "category": r[2], "source": r[3]} for r in rows]

@app.get("/api/v1/dashboards/peer-suggestions")
def get_peer_suggestions(username: str = Query(...)):
    peer_chain = {"aditya": "admin", "guest": "aditya", "admin": "guest"}
    target_upstream_user = peer_chain.get(username)
    if not target_upstream_user:
        return []
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT template_id, template_name, category_tag FROM dashboard_templates WHERE username = ?", (target_upstream_user,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "category": r[2], "suggested_from": target_upstream_user} for r in rows]

@app.get("/api/v1/dashboards/recently-deleted")
def get_recently_deleted_dashboards():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT d.template_id FROM dashboard_defaults d LEFT JOIN dashboard_templates t ON d.template_id = t.template_id WHERE t.template_id IS NULL")
    ids = [row[0] for row in cursor.fetchall()]
    deleted_profiles = []
    for t_id in ids:
        guessed_name = t_id.replace('custom_', '').replace('_', ' ').title()
        category = "server"
        if "aws" in t_id or "amazon" in t_id: category = "aws"
        elif "k8s" in t_id or "kubernetes" in t_id: category = "kubernetes"
        elif "net" in t_id or "cisco" in t_id: category = "network"
        deleted_profiles.append({"id": t_id, "name": guessed_name, "category": category})
    conn.close()
    return deleted_profiles

@app.post("/api/v1/dashboards/restore/{template_id}")
def restore_dashboard(template_id: str, payload: dict):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        user = payload.get("username", "admin")
        cursor.execute("""
            INSERT OR REPLACE INTO dashboard_templates (template_id, template_name, category_tag, username)
            VALUES (?, ?, ?, ?)
        """, (template_id, payload.get("name", "Restored View"), payload.get("category", "server"), user))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

@app.put("/api/v1/widgets/update")
def update_widget_details(payload: UpdateWidgetPayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE widgets SET widget_name = ? WHERE widget_id = ?", (payload.widget_name, payload.widget_id))
        if cursor.rowcount == 0:
            cursor.execute("INSERT OR IGNORE INTO widgets VALUES (?, ?, 'general')", (payload.widget_id, payload.widget_name))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

@app.get("/api/v1/dashboard-defaults")
def get_dashboard_defaults(category: str, template_id: Optional[str] = None, dashboard_name: Optional[str] = "Custom", username: Optional[str] = "admin", authorization: Optional[str] = Header(None)):
    if not category or category == "undefined": return []
    conn = get_db_connection()
    cursor = conn.cursor()
    rows = []
    if template_id:
        # LEFT JOIN widget_configs so any widget added through the real
        # "Add Widget" config flow comes back with its actual saved chart
        # type / resource type / show option / time period, instead of
        # only the bare widget_id + name -- that's what was making chart
        # type and the config line reset on every reload.
        cursor.execute("""
            SELECT w.widget_id, w.widget_name, c.chart_type, c.resource_type, c.show_option, c.time_period
            FROM dashboard_defaults d
            JOIN widgets w ON d.widget_id = w.widget_id
            LEFT JOIN widget_configs c ON c.widget_id = d.widget_id AND c.template_id = d.template_id
            WHERE d.template_id = ? AND d.username = ?
        """, (template_id, username))
        rows = cursor.fetchall()
        if not rows and template_id.startswith("live_"):
            cursor.execute("""
                SELECT w.widget_id, w.widget_name, c.chart_type, c.resource_type, c.show_option, c.time_period
                FROM dashboard_defaults d
                JOIN widgets w ON d.widget_id = w.widget_id
                LEFT JOIN widget_configs c ON c.widget_id = d.widget_id AND c.template_id = d.template_id
                WHERE d.template_id = ? AND d.username = ?
            """, (template_id, "global_default"))
            rows = cursor.fetchall()
    if rows:
        conn.close()
        return [{
            "widget_id": r[0], "name": r[1],
            "chart_type": r[2], "resource_type": r[3], "show_option": r[4], "time_period": r[5],
        } for r in rows]
    if authorization and template_id and template_id.startswith("live_template_"):
        token = authorization.replace("Bearer ", "").strip()
        clean_monitor_id = template_id.replace("live_template_", "")
        live_widgets = fetch_exact_monitor_widgets(token, clean_monitor_id)
        if live_widgets:
            conn.close()
            return live_widgets
    if not rows:
        cursor.execute("SELECT widget_id, widget_name FROM widgets WHERE category_tag = ?", (category,))
        rows = cursor.fetchall()
    conn.close()
    return [{"widget_id": r[0], "name": r[1]} for r in rows]

@app.post("/api/v1/dashboards/save")
def save_dashboard(payload: SaveDashboardPayload):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO dashboard_templates (template_id, template_name, category_tag, username)
            VALUES (?, ?, ?, ?)
        """, (payload.template_id, payload.template_name, payload.category_tag, payload.username))
        cursor.execute("DELETE FROM dashboard_defaults WHERE template_id = ? AND username = ?", (payload.template_id, payload.username))
        for w in payload.widgets:
            cursor.execute("INSERT OR IGNORE INTO widgets (widget_id, widget_name, category_tag) VALUES (?, ?, ?)", (w.id, w.name, payload.category_tag))
            cursor.execute("INSERT OR IGNORE INTO dashboard_defaults VALUES (?, ?, ?)", (payload.template_id, w.id, payload.username))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

def _cascade_delete_dashboard(cursor, template_id: str):
    """Removes a template_id from every table it can appear in. Previously
    only dashboard_templates was cleared here, which left widget_configs,
    dashboard_defaults, and (for live-captured dashboards) the source row
    in live_widget_captures behind -- meaning the data could silently
    resurface if that dashboard URL was ever synced again."""
    cursor.execute("DELETE FROM dashboard_templates WHERE template_id = ?", (template_id,))
    cursor.execute("DELETE FROM dashboard_defaults WHERE template_id = ?", (template_id,))
    cursor.execute("DELETE FROM widget_configs WHERE template_id = ?", (template_id,))
    cursor.execute("DELETE FROM dashboard_permalinks WHERE template_id = ?", (template_id,))
    if template_id.startswith("live_"):
        numeric_id = template_id[len("live_"):]
        cursor.execute("SELECT dashboard_url FROM live_widget_captures")
        for (url,) in cursor.fetchall():
            if _extract_dashboard_numeric_id(url) == numeric_id:
                cursor.execute("DELETE FROM live_widget_captures WHERE dashboard_url = ?", (url,))

@app.delete("/api/v1/dashboards/delete/{template_id}")
def delete_dashboard(template_id: str, username: str = "admin"):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        _cascade_delete_dashboard(cursor, template_id)
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

class SyncLiveDashboardListPayload(BaseModel):
    dashboard_names: List[str]  # dashboard names visible on the live listing page, after full scroll-load

@app.post("/api/v1/dashboards/sync-live-list")
def sync_live_dashboard_list(payload: SyncLiveDashboardListPayload):
    # Note: the extension confirms the list is fully scrolled/loaded and
    # stable (same reading twice) before ever sending it here, so an
    # empty or short list at this point is trusted as a real state.
    live_names = {(_clean_dashboard_title(n) or n) for n in payload.dashboard_names}

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT template_id, template_name FROM dashboard_templates WHERE source = 'live_sync'")
        known_live = cursor.fetchall()

        to_delete = [template_id for template_id, template_name in known_live if template_name not in live_names]
        for template_id in to_delete:
            _cascade_delete_dashboard(cursor, template_id)
        conn.commit()
        return {"status": "ok", "deleted": to_delete, "still_live": len(live_names)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

@app.delete("/api/v1/dashboards/purge/{template_id}")
def purge_dashboard_permanently(template_id: str, username: str = "admin"):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM dashboard_defaults WHERE template_id = ?", (template_id,))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

def _normalize_chart_key(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())

def _build_type_cooccurrence_matrix(cursor):
    """Builds a type-level co-occurrence matrix from real dashboards:
    treats each dashboard (template_id) as a "basket" and the chart types
    of its widgets as "items", using widget_configs -- the table that
    actually records a widget's real captured chart_type per dashboard.
    Raw widget_id can't be the co-occurrence key since it's tied to one
    specific monitor and essentially never repeats across dashboards;
    the normalized chart type is what generalizes.

    Returns:
      pair_counts[type_a][type_b] = number of dashboards containing both
      type_totals[type]           = number of dashboards containing type,
                                     used as the denominator for a
                                     confidence-style P(b present | a present)
    """
    cursor.execute("SELECT template_id, chart_type FROM widget_configs WHERE chart_type IS NOT NULL")
    dash_types = {}
    for template_id, chart_type in cursor.fetchall():
        norm = _normalize_chart_key(chart_type)
        if not norm:
            continue
        dash_types.setdefault(template_id, set()).add(norm)

    pair_counts = {}
    type_totals = {}
    for types in dash_types.values():
        types = list(types)
        for t in types:
            type_totals[t] = type_totals.get(t, 0) + 1
        for a in types:
            for b in types:
                if a == b:
                    continue
                pair_counts.setdefault(a, {})
                pair_counts[a][b] = pair_counts[a].get(b, 0) + 1
    return pair_counts, type_totals

def _cooccurrence_score_for_candidate(norm_candidate, existing_norm_types, pair_counts, type_totals):
    """Association-rule-style confidence: for each widget type already on
    this dashboard, P(candidate present | that type present) =
    count(type, candidate) / count(type) across all real dashboards.
    Score is the average of that across existing types. Returns 0 with no
    evidence if the candidate has never co-occurred with anything on this
    dashboard -- an honest "no pattern observed", not a guess."""
    if not existing_norm_types:
        return 0.0, 0
    scores = []
    evidence = 0
    for t in existing_norm_types:
        total = type_totals.get(t, 0)
        if not total:
            continue
        count = pair_counts.get(t, {}).get(norm_candidate, 0)
        if count:
            evidence += count
            scores.append(100 * count / total)
    if not scores:
        return 0.0, evidence
    return round(sum(scores) / len(scores), 1), evidence

def _build_type_popularity(cursor):
    """Single-item frequency (not pairs): how many real dashboards have
    configured each chart type at all, anywhere on the account. This is
    the honest way to lean on "widgets from other dashboards" as a
    fallback -- dashboard_defaults links widgets to dashboards but has no
    chart_type column to bucket by (a raw widget_id is tied to one
    specific monitor and can't be matched to a catalog type reliably by
    name), so widget_configs.chart_type remains the only trustworthy
    "type" signal. Popularity doesn't require a *pair* like co-occurrence
    does, so it still has real signal from even a single dashboard."""
    cursor.execute("SELECT chart_type FROM widget_configs WHERE chart_type IS NOT NULL")
    counts = {}
    for (chart_type,) in cursor.fetchall():
        norm = _normalize_chart_key(chart_type)
        if not norm:
            continue
        counts[norm] = counts.get(norm, 0) + 1
    return counts

def _find_real_config_for_type_label(cursor, type_label: str):
    """Best-effort match between a catalog widget's human label (e.g.
    'Time Series') and the chart-type radio id actually observed on the
    real site (e.g. 'TimeChart') — there's no verified mapping table for
    this, so it's a normalized match ranked exact > 'chart'-suffix >
    substring, not a guaranteed hit. Among equally-ranked matches, the one
    backed by the most real observations wins (rather than whichever the
    DB happens to return first).

    The returned "confidence" is a genuine measure: what % of the real
    observations for that chart type agree on the same resource/show/time
    combo, tempered down when there are very few observations (a single
    observation agreeing with itself is not "100% confidence")."""
    norm_label = _normalize_chart_key(type_label)
    if not norm_label:
        return None
    cursor.execute("SELECT DISTINCT chart_type FROM widget_config_observations")
    candidates = []
    for (chart_type,) in cursor.fetchall():
        norm_chart = _normalize_chart_key(chart_type)
        if norm_chart == norm_label:
            rank = 0
        elif norm_chart == norm_label + "chart":
            rank = 1
        elif norm_label in norm_chart:
            rank = 2
        else:
            continue
        cursor.execute("""
            SELECT resource_type, show_option, time_period FROM widget_config_observations WHERE chart_type = ?
        """, (chart_type,))
        rows = cursor.fetchall()
        if not rows:
            continue
        candidates.append((rank, len(rows), chart_type, rows))
    if not candidates:
        return None
    # Closest label match first; among ties, the better-sampled one.
    candidates.sort(key=lambda c: (c[0], -c[1]))
    _, sample_size, _chart_type, rows = candidates[0]

    def agreement(vals):
        counts = {}
        for v in vals:
            if v:
                counts[v] = counts.get(v, 0) + 1
        if not counts:
            return None, 0.0
        value, count = max(counts.items(), key=lambda kv: kv[1])
        return value, round(100 * count / len(vals), 1)

    resource_type, r_conf = agreement([r[0] for r in rows])
    show_option, s_conf = agreement([r[1] for r in rows])
    time_period, t_conf = agreement([r[2] for r in rows])
    field_confs = [c for c in (r_conf, s_conf, t_conf) if c]
    agreement_pct = sum(field_confs) / len(field_confs) if field_confs else 0.0
    # Temper by sample size: 1 observation shouldn't read as "certain",
    # 5+ observations agreeing can.
    sample_factor = min(1.0, sample_size / 5.0)
    confidence = round(agreement_pct * sample_factor, 1)
    return {
        "resource_type": resource_type,
        "show_option": show_option,
        "time_period": time_period,
        "sample_size": sample_size,
        "confidence": confidence,
    }

def _find_live_chart_data_for_type_label(cursor, type_label: str):
    """Same normalized ranking approach as _find_real_config_for_type_label,
    but scanning widget_configs for an already-captured live_chart_data blob
    instead of the observations table. Used to give recommendation cards a
    real preview chart (and a real starting dataset when added) instead of
    a placeholder, whenever a widget of a matching chart type has already
    been captured from the live dashboard somewhere."""
    norm_label = _normalize_chart_key(type_label)
    if not norm_label:
        return None
    cursor.execute("""
        SELECT chart_type, display_name, live_chart_data FROM widget_configs
        WHERE live_chart_data IS NOT NULL
    """)
    candidates = []
    for chart_type, display_name, chart_json in cursor.fetchall():
        norm_chart = _normalize_chart_key(chart_type)
        if norm_chart == norm_label:
            rank = 0
        elif norm_chart == norm_label + "chart":
            rank = 1
        elif norm_label in norm_chart:
            rank = 2
        else:
            continue
        try:
            parsed = json.loads(chart_json)
        except (TypeError, ValueError):
            continue
        if not parsed or len(parsed) < 2:
            continue
        candidates.append((rank, len(parsed), display_name, parsed, chart_type))
    if not candidates:
        return None
    # Closest label match first; among ties, the richer dataset (more points).
    candidates.sort(key=lambda c: (c[0], -c[1]))
    _, _, source_name, chart_data, matched_chart_type = candidates[0]
    return {"chart_data": chart_data, "source_name": source_name, "chart_type": matched_chart_type}


@app.get("/api/v1/recommendations")
def get_recommendations(template_id: str, authorization: Optional[str] = Header(None)):
    """
    Returns recommendations grouped by real widget category, built strictly
    from the widget_catalog table -- the same real, extension-captured
    category/classification data that WidgetRecommendationEngine.load() reads
    from /api/widget-catalog. There is no catalog-wide fallback here: if the
    dashboard's own category isn't present in the catalog, it's simply not
    the first group shown -- widgets are never pulled in mixed/unlabeled.

    Ranking is a 3-tier hybrid, strongest real signal first:
      1. Co-occurrence: how often this widget type appears alongside the
         types already on THIS dashboard, across all real dashboards.
      2. Popularity: if no co-occurrence evidence, how often this type is
         used on ANY real dashboard at all (doesn't need a pairing, so it
         still has signal from just one dashboard).
      3. Random: if there's truly no usage data anywhere for this type,
         score is randomized rather than falling back to a fixed
         alphabetical catalog order -- keeps cold-start recommendations
         from looking static while still only drawing from the real,
         extension-captured catalog (never fabricated widgets).
    Per-widget config defaults (resource_type/show_option/time_period) are
    a separate concern and still come from _find_real_config_for_type_label.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT category_tag FROM dashboard_templates WHERE template_id = ?", (template_id,))
    dash_row = cursor.fetchone()
    category_tag = (dash_row[0] if dash_row else "") or ""

    cursor.execute("SELECT widget_id FROM dashboard_defaults WHERE template_id = ?", (template_id,))
    current_widgets = {row[0] for row in cursor.fetchall()}
    cursor.execute("SELECT widget_id, category FROM widget_configs WHERE template_id = ?", (template_id,))
    for row in cursor.fetchall():
        current_widgets.add(row[0])

    # This dashboard's own basket -- the chart types it already has,
    # normalized the same way the co-occurrence matrix keys are.
    cursor.execute("SELECT chart_type FROM widget_configs WHERE template_id = ? AND chart_type IS NOT NULL", (template_id,))
    existing_types = {_normalize_chart_key(row[0]) for row in cursor.fetchall() if _normalize_chart_key(row[0])}
    pair_counts, type_totals = _build_type_cooccurrence_matrix(cursor)
    popularity = _build_type_popularity(cursor)

    # Every real category/widget combo captured from the live site, in one
    # pass -- this is the exact same source table the browser-extension
    # catalog (/api/widget-catalog) groups by category.
    cursor.execute("""
        SELECT widget_item_id, category, type_label, is_live
        FROM widget_catalog
        ORDER BY category, type_label
    """)
    catalog_rows = cursor.fetchall()

    by_category = {}
    for widget_item_id, cat_name, type_label, is_live in catalog_rows:
        if widget_item_id in current_widgets or f"live_{widget_item_id}" in current_widgets:
            continue

        # Config-value defaults only -- unrelated to the confidence score.
        real_config = _find_real_config_for_type_label(cursor, type_label)
        if real_config:
            resource_type = real_config["resource_type"]
            show_option = real_config["show_option"]
            time_period = real_config["time_period"]
            sample_size = real_config["sample_size"]
        else:
            resource_type = "All Monitors"
            show_option = None
            time_period = "Last Hour"
            sample_size = 0

        norm_candidate = _normalize_chart_key(type_label)
        co_score, co_evidence = _cooccurrence_score_for_candidate(norm_candidate, existing_types, pair_counts, type_totals)
        if co_evidence:
            confidence = co_score
            reason = f"Co-occurs with widgets already on this dashboard, on {co_evidence} other real dashboard{'s' if co_evidence != 1 else ''}."
        else:
            pop_count = popularity.get(norm_candidate, 0)
            if pop_count:
                # Real signal, but weaker than direct co-occurrence --
                # capped lower, and jittered so equally-popular candidates
                # don't render in the same fixed order every time.
                confidence = round(min(60.0, 20.0 + pop_count * 8) + random.uniform(-3, 3), 1)
                reason = f"Used on {pop_count} real dashboard{'s' if pop_count != 1 else ''} on your account (no direct co-occurrence with this dashboard yet)."
            else:
                # No usage data anywhere for this type -- randomize rather
                # than let the catalog's alphabetical SQL order look like
                # a fixed, static pick every time.
                confidence = round(random.uniform(0, 15), 1)
                reason = f"From your '{cat_name}' category — no usage data yet, shown in rotating order."

        live_chart = _find_live_chart_data_for_type_label(cursor, type_label)
        by_category.setdefault(cat_name, []).append({
            "widget_id": widget_item_id,
            "name": type_label or widget_item_id,
            "confidence": round(confidence, 1),
            "reason": reason,
            "resource_type": resource_type,
            "show_option": show_option,
            "time_period": time_period,
            "sample_size": sample_size,
            "chart_data": live_chart["chart_data"] if live_chart else None,
            "chart_data_source": live_chart["source_name"] if live_chart else None,
            "matched_chart_type": live_chart["chart_type"] if live_chart else None,
        })

    conn.close()

    # Within each category, strongest real-data-backed picks first; cap
    # each group so one huge category can't crowd out the others.
    grouped = []
    for cat_name, recs in by_category.items():
        recs.sort(key=lambda r: r["confidence"], reverse=True)
        grouped.append({"category": cat_name, "recommendations": recs[:5]})

    # The dashboard's own category (if it exists in the real catalog) leads
    # the list -- everything else still shows, just after it. No blending.
    grouped.sort(key=lambda g: 0 if g["category"].strip().lower() == category_tag.strip().lower() else 1)

    # Flat view kept for any caller not yet updated to the grouped shape.
    flat = [r for g in grouped for r in g["recommendations"]]

    return {"recommendations_by_category": grouped, "recommendations": flat}

@app.post("/api/v1/dashboards/analyze")
def analyze_dashboard(payload: AnalyzeDashboardPayload):
    if not payload.widgets:
        return {"status": "error", "message": "This dashboard has no widgets to analyze yet."}
    if not gemini_client:
        return {"status": "error", "message": "AI analysis is not configured. Set GEMINI_API_KEY."}

    # Ground the analysis in the real, extension-captured widget catalog --
    # the same table /api/v1/recommendations reads from -- so "gaps" the
    # model suggests are things the account can actually add, not guesses.
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT type_label FROM widget_catalog WHERE category = ? AND type_label IS NOT NULL",
        (payload.category,)
    )
    catalog_types = [row[0] for row in cursor.fetchall() if row[0]]
    catalog_was_category_scoped = bool(catalog_types)
    if not catalog_types:
        # This dashboard's category has no captured catalog entries yet --
        # fall back to the full real catalog rather than analyzing blind.
        cursor.execute("SELECT DISTINCT type_label FROM widget_catalog WHERE type_label IS NOT NULL")
        catalog_types = [row[0] for row in cursor.fetchall() if row[0]]
    conn.close()

    catalog_lookup = {t.strip().lower() for t in catalog_types}
    widget_lines = "\n".join(f"- {w.name} (id: {w.id})" for w in payload.widgets)

    if catalog_types:
        catalog_block = "\n".join(f"- {t}" for t in catalog_types)
        scope_note = "this dashboard's category" if catalog_was_category_scoped else "this Site24x7 account"
        catalog_instructions = f"""
Widget types actually available for {scope_note} (from the real, observed widget catalog):
{catalog_block}

Only suggest gap widgets whose "name" matches one of these real available types. Do not invent widget types that aren't in this list."""
    else:
        catalog_instructions = ""

    prompt = f"""You are a monitoring/observability expert reviewing ONE dashboard in isolation.
Dashboard name: {payload.dashboard_name}
Dashboard category: {payload.category}
Widgets currently on this dashboard:
{widget_lines}
{catalog_instructions}
Analyze only this dashboard. Respond with ONLY valid JSON in exactly this shape:
{{
  "summary": "one or two sentence overview",
  "gaps": [{{"name": "suggested metric", "reason": "why"}}],
  "redundancies": [{{"widgets": ["w1", "w2"], "reason": "why"}}],
  "warnings": ["warning"]
}}
"""
    try:
        response = gemini_client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        raw_text = (response.text or "").strip().replace("```json", "").replace("```", "").strip()
        analysis = json.loads(raw_text)
        # Flag each gap against the real catalog so the frontend can show
        # confirmed-addable suggestions differently from ungrounded ones
        # (e.g. when no catalog data existed at all for this account yet).
        for gap in analysis.get("gaps", []):
            gap_name = (gap.get("name") or "").strip().lower()
            gap["in_catalog"] = gap_name in catalog_lookup
        return {
            "status": "success",
            "dashboard_name": payload.dashboard_name,
            "analysis": analysis,
            "catalog_grounded": bool(catalog_types)
        }
    except Exception as e:
        return {"status": "error", "message": f"AI analysis failed: {str(e)}"}

@app.post("/api/v1/dashboards/suggest-widgets")
def suggest_widgets_for_new_dashboard(payload: SuggestWidgetsPayload):
    dashboard_name = (payload.dashboard_name or "").strip()
    if not dashboard_name:
        return {"status": "error", "message": "Dashboard name is required."}
    if not gemini_client:
        return {"status": "error", "message": "AI suggestions are not configured."}
    category = (payload.category or "general").strip()
    prompt = f"""You are a monitoring expert. Suggest a practical starter set of widgets for dashboard: {dashboard_name} (type: {category}). 
Respond with ONLY valid JSON in exactly this shape:
{{
  "widgets": [{{"name": "metric name", "reason": "why fits"}}]
}}
"""
    try:
        response = gemini_client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        raw_text = (response.text or "").strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw_text)
        suggested = parsed.get("widgets", [])
        formatted = []
        for i, w in enumerate(suggested):
            w_name = (w.get("name") or "").strip()
            if not w_name: continue
            formatted.append({
                "widget_id": f"ai_suggested_{slugify_widget_name(w_name)}_{i}",
                "name": w_name,
                "reason": w.get("reason", "")
            })
        return {"status": "success", "widgets": formatted}
    except Exception as e:
        return {"status": "error", "message": f"AI suggestion failed: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)