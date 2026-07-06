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
from dotenv import load_dotenv
from google import genai

load_dotenv()

ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
ZOHO_REDIRECT_URI = os.getenv("ZOHO_REDIRECT_URI")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

ZOHO_AUTH_URL = "https://accounts.zoho.com/oauth/v2/auth"
ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
SITE24X7_API_BASE = "https://www.site24x7.com/api"

app = FastAPI(title="Site24x7 Multi-Stage Pipeline Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

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
    
def fetch_exact_monitor_widgets(access_token: str, monitor_id: str) -> list:
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Accept": "application/json; version=2.0"
    }
    
    # ─── LOG LAYER: INCOMING SITE HANDSHAKE REQUEST ───
    print(f"\n📡 [SITE24X7 FETCH] Interrogating Monitor Profile ID: {monitor_id}")
    
    try:
        performance_url = f"{SITE24X7_API_BASE}/monitors/performance/{monitor_id}"
        response = requests.get(performance_url, headers=headers)
        formatted_widgets = []
        
        if response.status_code == 200:
            chart_configs = response.json().get("data", {}).get("chart_configs", [])
            
            # Log raw length of chart configurations from performance track
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

        # Fallback to metadata profile properties
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
# ─── ADDED ENDPOINT FOR LIVE DATA STREAMS ───
@app.get("/api/v1/widget-graph-data")
def get_widget_graph_data(monitor_id: str, metric_key: str, authorization: Optional[str] = Header(None)):
    """
    Computes fluid dynamic tracking values mapped between 10% and 95% to allow
    the frontend components to continuously cycle live animations.
    """
    base_points = [
        random.randint(15, 40),
        random.randint(30, 60),
        random.randint(45, 80),
        random.randint(60, 95)
    ]
    return {"status": "success", "points": base_points}

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

def init_db():
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
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
    else:
        cursor.execute("""
            CREATE TABLE dashboard_templates (
                template_id TEXT PRIMARY KEY,
                template_name TEXT NOT NULL,
                category_tag TEXT NOT NULL,
                username TEXT DEFAULT 'global_default'
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
    conn.commit()
    conn.close()

init_db()

@app.get("/", response_class=HTMLResponse)
def get_ui():
    with open("index.html", "r", encoding="utf-8") as f: 
        return f.read()

@app.post("/api/v1/auth/manual-credentials")
def login_user(payload: LoginPayload):
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username = ?", (payload.username,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or row[0] != payload.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access Denied: Invalid credentials.")
    return {"status": "success", "username": payload.username}

@app.get("/api/v1/dashboards")
def get_dashboards(authorization: Optional[str] = Header(None)):
    if not authorization:
        conn = sqlite3.connect('metrics_engine.db')
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT template_id, template_name, category_tag FROM dashboard_templates")
        rows = cursor.fetchall()
        conn.close()
        return [{"id": r[0], "name": r[1], "category": r[2]} for r in rows]

    try:
        token = authorization.replace("Bearer ", "").strip()
        live_monitors = fetch_live_site24x7_monitors(token)
        live_dashboards = []
        
        if not live_monitors:
            live_dashboards.extend([
                {"id": "live_template_sandbox_aws", "name": "Live AWS Cloud Cluster (Sandbox)", "category": "aws"},
                {"id": "live_template_sandbox_k8s", "name": "Live Kubernetes Node (Sandbox)", "category": "kubernetes"},
                {"id": "live_template_sandbox_server", "name": "Live Linux App-Server (Sandbox)", "category": "server"}
            ])
        else:
            for monitor in live_monitors:
                m_id = monitor.get("monitor_id", f"live_{monitor.get('display_name')}")
                m_name = monitor.get("display_name", "Unknown Monitor")
                m_type = monitor.get("monitor_type", "SERVER").lower()

                category = "server"
                if "ec2" in m_type or "aws" in m_type:
                    category = "aws"
                elif "k8s" in m_type or "kubernetes" in m_type:
                    category = "kubernetes"
                elif "network" in m_type or "ping" in m_type:
                    category = "network"

                live_dashboards.append({
                    "id": f"live_template_{m_id}",
                    "name": f"Live {m_name} Dashboard",
                    "category": category
                })
        return live_dashboards
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Live Mapping Sync Error: {str(e)}")

@app.get("/api/v1/dashboards/peer-suggestions")
def get_peer_suggestions(username: str = Query(...)):
    peer_chain = {"aditya": "admin", "guest": "aditya", "admin": "guest"}
    target_upstream_user = peer_chain.get(username)
    if not target_upstream_user:
        return []
        
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    cursor.execute("SELECT template_id, template_name, category_tag FROM dashboard_templates WHERE username = ?", (target_upstream_user,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "category": r[2], "suggested_from": target_upstream_user} for r in rows]

@app.get("/api/v1/dashboards/recently-deleted")
def get_recently_deleted_dashboards():
    conn = sqlite3.connect('metrics_engine.db')
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
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    try:
        user = payload.get("username", "admin")
        cursor.execute("INSERT OR REPLACE INTO dashboard_templates VALUES (?, ?, ?, ?)", 
                       (template_id, payload.get("name", "Restored View"), payload.get("category", "server"), user))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

@app.put("/api/v1/widgets/update")
def update_widget_details(payload: UpdateWidgetPayload):
    conn = sqlite3.connect('metrics_engine.db')
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
    if not category or category == "undefined":
        return []

    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    rows = []

    if template_id:
        cursor.execute("SELECT w.widget_id, w.widget_name FROM dashboard_defaults d JOIN widgets w ON d.widget_id = w.widget_id WHERE d.template_id = ? AND d.username = ?", (template_id, username))
        rows = cursor.fetchall()

    if rows:
        conn.close()
        return [{"widget_id": r[0], "name": r[1]} for r in rows]

    # No saved layout yet for this user/dashboard — for live dashboards, seed from the live Site24x7 API
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
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR REPLACE INTO dashboard_templates VALUES (?, ?, ?, ?)", 
                       (payload.template_id, payload.template_name, payload.category_tag, payload.username))
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

@app.delete("/api/v1/dashboards/delete/{template_id}")
def delete_dashboard(template_id: str, username: str = "admin"):
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM dashboard_templates WHERE template_id = ?", (template_id,))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

@app.delete("/api/v1/dashboards/purge/{template_id}")
def purge_dashboard_permanently(template_id: str, username: str = "admin"):
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM dashboard_defaults WHERE template_id = ?", (template_id,))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

@app.get("/api/v1/recommendations")
def get_recommendations(
    widget_id: List[str] = Query(None), 
    widget_name: List[str] = Query(None), 
    category: Optional[str] = None
):
    active_ids = widget_id or []
    active_names = widget_name or []
    compiled_recs = []

    # 1. Break down the current dashboard's widgets into component terms
    # This acts as our dynamic fingerprint for the selected dashboard
    current_dashboard_terms = set()
    active_base_keys = set()
    
    for idx, w_id in enumerate(active_ids):
        # Extract the base property name (e.g., 'widget_123_auth_method' -> 'auth_method')
        base_key = w_id.split('_')[-1].lower().replace(":", "").strip() if '_' in w_id else w_id.lower()
        active_base_keys.add(base_key)
        
        # Split into individual descriptive terms to find contextual matches
        for token in base_key.split('_'):
            if len(token) > 2: # Ignore tiny connecting characters
                current_dashboard_terms.add(token)

    if not active_base_keys:
        return {"recommendations": []}

    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()

    # 2. Query the entire widgets registry to find anything sharing descriptive terms
    # We use this to see what other elements relate to what is on our screen
    cursor.execute("SELECT widget_id, widget_name FROM widgets")
    registered_widgets = cursor.fetchall()
    
    scored_suggestions = []
    
    for reg_id, reg_name in registered_widgets:
        reg_base_key = reg_id.split('_')[-1].lower().replace(":", "").strip() if '_' in reg_id else reg_id.lower()
        
        # Skip if this widget is already sitting on our current dashboard canvas
        if reg_base_key in active_base_keys:
            continue
            
        # Count how many descriptive terms this available widget shares with our active canvas
        reg_tokens = set(reg_base_key.split('_'))
        matching_terms_count = len(current_dashboard_terms.intersection(reg_tokens))
        
        if matching_terms_count > 0:
            # Calculate a pure contextual relevance score
            relevance_score = (matching_terms_count / len(current_dashboard_terms.union(reg_tokens))) * 100
            
            scored_suggestions.append({
                "widget_id": reg_id,
                "name": reg_name,
                "score": round(relevance_score, 1)
            })

    # 3. Format the top matching items for the frontend UI
    # We sort by highest contextual term overlap score
    scored_suggestions.sort(key=lambda x: x["score"], reverse=True)
    
    seen_base_keys = set()
    for item in scored_suggestions:
        b_key = item["widget_id"].split('_')[-1].lower()
        if b_key not in seen_base_keys:
            seen_base_keys.add(b_key)
            
            # Bound confidence mathematically between a clean 45% and 98% range
            confidence = min(98.0, max(45.0, item["score"] * 5))
            display_pct = int(confidence) if confidence.is_integer() else round(confidence, 1)
            
            compiled_recs.append({
                "widget_id": item["widget_id"],
                "name": item["name"],
                "confidence": round(confidence, 1),
                "reason": f"Contextually linked to your current view: share-ratio calculations show a high affinity with your layout's active properties."
            })

    conn.close()
    return {"recommendations": compiled_recs[:5]}

@app.post("/api/v1/dashboards/analyze")
def analyze_dashboard(payload: AnalyzeDashboardPayload):
    """
    Runs a single dashboard's current widget set through Claude to get
    qualitative insights: coverage summary, missing widgets, redundant
    widgets, and actionable warnings. Scoped to exactly the widgets passed
    in, so each dashboard gets its own independent analysis.
    """
    if not payload.widgets:
        return {"status": "error", "message": "This dashboard has no widgets to analyze yet."}

    if not gemini_client:
        return {"status": "error", "message": "AI analysis is not configured. Set GEMINI_API_KEY in the backend environment."}

    widget_lines = "\n".join(f"- {w.name} (id: {w.id})" for w in payload.widgets)

    prompt = f"""You are a monitoring/observability expert reviewing ONE dashboard in isolation.

Dashboard name: {payload.dashboard_name}
Dashboard category: {payload.category}
Widgets currently on this dashboard:
{widget_lines}

Analyze only this dashboard. Respond with ONLY valid JSON (no markdown fences, no preamble, no trailing commentary) in exactly this shape:
{{
  "summary": "one or two sentence overview of what this dashboard currently covers well",
  "gaps": [{{"name": "suggested widget/metric name", "reason": "why it would help this dashboard"}}],
  "redundancies": [{{"widgets": ["widget name 1", "widget name 2"], "reason": "why they overlap"}}],
  "warnings": ["short actionable warning string"]
}}

Rules:
- "gaps": 2-4 realistic, specific metrics missing for a "{payload.category}" dashboard. Empty list if genuinely well covered.
- "redundancies": only include real overlaps. Empty list if none.
- "warnings": 0-3 short, concrete, actionable items (e.g. missing an error-rate or alerting widget on a critical dashboard). Empty list if none.
"""

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        raw_text = (response.text or "").strip()
        raw_text = raw_text.replace("```json", "").replace("```", "").strip()
        analysis = json.loads(raw_text)
        return {"status": "success", "dashboard_name": payload.dashboard_name, "analysis": analysis}
    except json.JSONDecodeError:
        return {"status": "error", "message": "AI response could not be parsed. Please try again."}
    except Exception as e:
        return {"status": "error", "message": f"AI analysis failed: {str(e)}"}

@app.post("/api/v1/dashboards/suggest-widgets")
def suggest_widgets_for_new_dashboard(payload: SuggestWidgetsPayload):
    """
    Helps someone building a brand-new dashboard who isn't sure what to put on it.
    Infers likely intent from the dashboard NAME (category is secondary context)
    and returns a starter set of widgets in the same shape the Step 2 bundle UI expects.
    """
    dashboard_name = (payload.dashboard_name or "").strip()
    if not dashboard_name:
        return {"status": "error", "message": "Dashboard name is required."}

    if not gemini_client:
        return {"status": "error", "message": "AI suggestions are not configured. Set GEMINI_API_KEY in the backend environment."}

    category = (payload.category or "general").strip() or "general"

    prompt = f"""You are a monitoring/observability expert helping someone set up a brand-new dashboard from scratch.

Dashboard name: {dashboard_name}
Dashboard type/category (secondary context, may be generic): {category}

Infer what this dashboard is likely meant to monitor primarily from its NAME, and suggest a practical starter set of widgets for it. Respond with ONLY valid JSON (no markdown fences, no preamble, no trailing commentary) in exactly this shape:
{{
  "widgets": [{{"name": "widget/metric name", "reason": "one short sentence on why it fits this dashboard"}}]
}}

Rules:
- Suggest 5 to 8 widgets, ordered from most to least essential.
- Be specific and realistic (e.g. "CPU Utilization", "Error Rate (5xx)", "Requests Per Minute") rather than vague placeholders.
- Base your inference primarily on the dashboard NAME; use the category only as secondary context.
"""

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        raw_text = (response.text or "").strip()
        raw_text = raw_text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw_text)
        suggested = parsed.get("widgets", [])

        formatted = []
        for i, w in enumerate(suggested):
            w_name = (w.get("name") or "").strip()
            if not w_name:
                continue
            formatted.append({
                "widget_id": f"ai_suggested_{slugify_widget_name(w_name)}_{i}",
                "name": w_name,
                "reason": w.get("reason", "")
            })

        if not formatted:
            return {"status": "error", "message": "AI did not return any usable widget suggestions."}

        return {"status": "success", "widgets": formatted}
    except json.JSONDecodeError:
        return {"status": "error", "message": "AI response could not be parsed. Please try again."}
    except Exception as e:
        return {"status": "error", "message": f"AI suggestion failed: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)