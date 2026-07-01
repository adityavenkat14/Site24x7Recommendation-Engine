from fastapi import FastAPI, Query, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import sqlite3

app = FastAPI(title="Site24x7 Multi-Stage Pipeline Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ─── FIXED FASTAPI CONTRACT MODELS ────────────────────────────────────
class DashboardWidgetItem(BaseModel):
    id: str
    name: str

class SaveDashboardPayload(BaseModel):
    template_id: str
    template_name: str
    category_tag: str
    widgets: List[DashboardWidgetItem]  # FIXED: id+name pairs so new/custom widgets can be catalogued on save
    username: str      # FIXED: Tracks unique user session isolation keys

class UpdateWidgetPayload(BaseModel):
    widget_id: str
    widget_name: str

class LoginPayload(BaseModel):
    username: str
    password: str

# ─── DATABASE STABILITY & RECONCILIATION LAYER ────────────────────────
def init_db():
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    
    # Secure profiles registration table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO users VALUES ('admin', 'admin123')")
    cursor.execute("INSERT OR IGNORE INTO users VALUES ('aditya', 'venkat')")
    cursor.execute("INSERT OR IGNORE INTO users VALUES ('guest', 'guest123')")
    
    # Verify and alter dashboard templates table for user multi-tenancy logs
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

    # Verify and alter dashboard defaults table to secure layout arrays by username
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
    conn.commit()
    conn.close()

init_db()

@app.get("/", response_class=HTMLResponse)
def get_ui():
    with open("index.html", "r") as f: 
        return f.read()

# ─── SESSION AUTHENTICATION ENDPOINT ──────────────────────────────────
@app.post("/api/v1/auth/login")
def login_user(payload: LoginPayload):
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username = ?", (payload.username,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or row[0] != payload.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access Denied: Invalid credentials."
        )
    return {"status": "success", "username": payload.username}

# FIXED: Serves ALL 19 default dashboards globally to admin, aditya, or guest profiles seamlessly
@app.get("/api/v1/dashboards")
def get_dashboards(username: Optional[str] = "admin"):
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dashboard_templates'")
    if not cursor.fetchone():
        conn.close()
        return []
        
    cursor.execute("""
        SELECT DISTINCT template_id, template_name, category_tag 
        FROM dashboard_templates 
        WHERE username = ? OR username = 'admin' OR username = 'global_default' OR username IS NULL
    """, (username,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "category": r[2]} for r in rows]

# ─── CROSS-USER PEER DASHBOARD SUGGESTIONS ENDPOINT ───────────────────
@app.get("/api/v1/dashboards/peer-suggestions")
def get_peer_suggestions(username: str = Query(...)): # Added explicit Query dependency
    peer_chain = {
        "aditya": "admin",
        "guest": "aditya",
        "admin": "guest"
    }
    
    target_upstream_user = peer_chain.get(username)
    if not target_upstream_user:
        return []
        
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT template_id, template_name, category_tag 
        FROM dashboard_templates 
        WHERE username = ?
    """, (target_upstream_user,))
    rows = cursor.fetchall()
    conn.close()
    
    #   Added the iteration syntax at the end
    return [{"id": r[0], "name": r[1], "category": r[2], "suggested_from": target_upstream_user} for r in rows]

@app.get("/api/v1/dashboards/recently-deleted")
def get_recently_deleted_dashboards():
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    query = """
        SELECT DISTINCT d.template_id 
        FROM dashboard_defaults d
        LEFT JOIN dashboard_templates t ON d.template_id = t.template_id
        WHERE t.template_id IS NULL
    """
    cursor.execute(query)
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

# FIXED: Safely reads user-modified custom metrics tracks and gracefully falls back to global blueprints
@app.get("/api/v1/dashboard-defaults")
def get_dashboard_defaults(
    category: str,
    template_id: Optional[str] = None,
    dashboard_name: Optional[str] = "Custom",
    username: Optional[str] = "admin",
):
    if not category or category == "undefined":
        return []

    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()

    if template_id:
        lookup_ids = [template_id]
    else:
        import re
        legacy_derived = "custom_" + re.sub(r'[^a-z0-9]', '_', dashboard_name.lower()) if dashboard_name else ""
        lookup_ids = [legacy_derived] if legacy_derived else []

    rows = []
    if lookup_ids:
        placeholders = ",".join("?" for _ in lookup_ids)

        # Query 1: Fetch user-saved specific edits
        cursor.execute(f"""
            SELECT w.widget_id, w.widget_name
            FROM dashboard_defaults d
            JOIN widgets w ON d.widget_id = w.widget_id
            WHERE d.template_id IN ({placeholders}) AND d.username = ?
        """, (*lookup_ids, username))
        rows = cursor.fetchall()

        # Query 2: Fallback to global defaults parsed from the zip package archives
        if not rows:
            cursor.execute(f"""
                SELECT w.widget_id, w.widget_name
                FROM dashboard_defaults d
                JOIN widgets w ON d.widget_id = w.widget_id
                WHERE d.template_id IN ({placeholders}) AND (d.username = 'admin' or d.username = 'global_default' OR d.username IS NULL)
            """, lookup_ids)
            rows = cursor.fetchall()

    # Query 3: Absolute domain fallback net
    if not rows:
        cursor.execute("SELECT widget_id, widget_name FROM widgets WHERE category_tag = ?", (category,))
        rows = cursor.fetchall()

    conn.close()
    return [{"widget_id": r[0], "name": r[1]} for r in rows]

# FIXED: Securely records dashboard modifications straight to the active user's space with complete widget lists
@app.post("/api/v1/dashboards/save")
def save_dashboard(payload: SaveDashboardPayload):
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR REPLACE INTO dashboard_templates VALUES (?, ?, ?, ?)", 
                       (payload.template_id, payload.template_name, payload.category_tag, payload.username))
        
        cursor.execute("DELETE FROM dashboard_defaults WHERE template_id = ? AND username = ?", (payload.template_id, payload.username))
        for w in payload.widgets:
            cursor.execute(
                "INSERT OR IGNORE INTO widgets (widget_id, widget_name, category_tag) VALUES (?, ?, ?)",
                (w.id, w.name, payload.category_tag)
            )
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
        cursor.execute("SELECT username FROM dashboard_templates WHERE template_id = ?", (template_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found.")
        owner = row[0]
        if username != owner and username != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this dashboard.")

        cursor.execute("DELETE FROM dashboard_templates WHERE template_id = ?", (template_id,))
        conn.commit()
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

@app.delete("/api/v1/dashboards/purge/{template_id}")
def purge_dashboard_permanently(template_id: str, username: str = "admin"):
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT DISTINCT username FROM dashboard_defaults WHERE template_id = ?", (template_id,))
        owners = [r[0] for r in cursor.fetchall()]
        if owners and username != "admin" and username not in owners:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this dashboard.")

        cursor.execute("DELETE FROM dashboard_defaults WHERE template_id = ?", (template_id,))
        conn.commit()
        return {"status": "success"}
    except HTTPException:
        raise
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

    if widget_id:
        for active_w in widget_id:
            cursor.execute("""
                SELECT r.widget_b_id, w.widget_name, r.confidence_score, aw.widget_name
                FROM rec_co_occurrence r
                JOIN widgets w ON r.widget_b_id = w.widget_id
                JOIN widgets aw ON r.widget_a_id = aw.widget_id
                WHERE r.widget_a_id = ?
            """, (active_w,))
            for row in cursor.fetchall():
                w_b_id, w_b_name, conf, w_a_name = row
                if w_b_id not in seen_widget_ids:
                    compiled_recs.append({
                        "widget_id": w_b_id,
                        "name": w_b_name,
                        "confidence": round(conf * 100, 1),
                        "reason": f"Frequently coupled with active metric '{w_a_name}'"
                    })
                    seen_widget_ids.add(w_b_id)

    cursor.execute("SELECT widget_id, widget_name FROM widgets WHERE category_tag = ?", (category,))
    domain_widgets = cursor.fetchall()
    base_confidence = 94.0
    for row in domain_widgets:
        w_id, w_name = row
        if w_id not in seen_widget_ids:
            compiled_recs.append({
                "widget_id": w_id,
                "name": w_name,
                "confidence": base_confidence,
                "reason": f"Unselected target companion for {category} environments"
            })
            seen_widget_ids.add(w_id)
            base_confidence -= 2.0  

    global_fallbacks = [
        ('widget_gen_cpu', 'Core Processor Load Utilization', 82.0, 'Global system CPU load context'),
        ('widget_gen_mem', 'Global Hardware Memory Allocation', 79.5, 'Global system RAM allocation profile'),
        ('widget_gen_disk', 'Storage Partition Read/Write Activity', 75.0, 'Global disk input/output metrics'),
        ('widget_gen_throughput', 'Network Controller Traffic Throughput', 71.0, 'Global network tracking delivery matrix')
    ]
    for w_id, w_name, score, reason_text in global_fallbacks:
        if w_id not in seen_widget_ids:
            compiled_recs.append({
                "widget_id": w_id,
                "name": w_name,
                "confidence": score,
                "reason": f"Infrastructure baseline: {reason_text}"
            })

    compiled_recs = sorted(compiled_recs, key=lambda x: x['confidence'], reverse=True)
    conn.close()
    return {"recommendations": compiled_recs[:6]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)