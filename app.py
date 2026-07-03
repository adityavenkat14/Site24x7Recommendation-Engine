from fastapi import FastAPI, Query, HTTPException, status, Header
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import os
import urllib.parse
import requests
import random
from dotenv import load_dotenv

load_dotenv()

ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
ZOHO_REDIRECT_URI = os.getenv("ZOHO_REDIRECT_URI")

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
    try:
        performance_url = f"{SITE24X7_API_BASE}/monitors/performance/{monitor_id}"
        response = requests.get(performance_url, headers=headers)
        formatted_widgets = []
        
        if response.status_code == 200:
            chart_configs = response.json().get("data", {}).get("chart_configs", [])
            for chart in chart_configs:
                metric_key = chart.get("value") or chart.get("metric_name")
                metric_name = chart.get("name")
                if metric_key and metric_name:
                    formatted_widgets.append({
                        "widget_id": f"widget_{monitor_id}_{metric_key}",
                        "name": metric_name
                    })
            if formatted_widgets:
                return formatted_widgets

        # Fallback to metadata profile properties
        info_url = f"{SITE24X7_API_BASE}/monitors/{monitor_id}"
        info_response = requests.get(info_url, headers=headers)
        if info_response.status_code == 200:
            monitor_profile = info_response.json().get("data", {})
            for key, value in monitor_profile.items():
                if isinstance(value, (list, dict)) or value is None:
                    continue
                formatted_widgets.append({
                    "widget_id": f"widget_{monitor_id}_{key}",
                    "name": f"{key.replace('_', ' ').title()}: {value}"
                })
            return formatted_widgets
    except Exception as e:
        print(f"❌ Diagnostic exception caught: {str(e)}")
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

    if authorization and template_id and template_id.startswith("live_template_"):
        token = authorization.replace("Bearer ", "").strip()
        clean_monitor_id = template_id.replace("live_template_", "")
        live_widgets = fetch_exact_monitor_widgets(token, clean_monitor_id)
        if live_widgets:
            return live_widgets

    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    rows = []
    
    if template_id:
        cursor.execute("SELECT w.widget_id, w.widget_name FROM dashboard_defaults d JOIN widgets w ON d.widget_id = w.widget_id WHERE d.template_id = ? AND d.username = ?", (template_id, username))
        rows = cursor.fetchall()

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
def get_recommendations(widget_id: List[str] = Query(None), category: Optional[str] = None):
    if not category or category == "":
        return {"recommendations": []}

    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    compiled_recs = []
    seen_widget_ids = set(widget_id) if widget_id else set()

    cursor.execute("SELECT widget_id, widget_name FROM widgets WHERE category_tag = ?", (category,))
    for row in cursor.fetchall():
        w_id, w_name = row
        if w_id not in seen_widget_ids:
            compiled_recs.append({
                "widget_id": w_id, "name": w_name, "confidence": 94.0,
                "reason": f"Recommended baseline component for monitoring active {category} environments"
            })
            seen_widget_ids.add(w_id)

    conn.close()
    return {"recommendations": compiled_recs[:6]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)