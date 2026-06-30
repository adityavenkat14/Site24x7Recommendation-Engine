from fastapi import FastAPI, Query
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

class SaveDashboardPayload(BaseModel):
    template_id: str
    template_name: str
    category_tag: str
    widgets: List[str]

class UpdateWidgetPayload(BaseModel):
    widget_id: str
    widget_name: str

@app.get("/", response_class=HTMLResponse)
def get_ui():
    with open("index.html", "r") as f: 
        return f.read()

@app.get("/api/v1/dashboards")
def get_dashboards():
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dashboard_templates'")
    if not cursor.fetchone():
        conn.close()
        return []
        
    cursor.execute("SELECT template_id, template_name, category_tag FROM dashboard_templates")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "category": r[2]} for r in rows]

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
        cursor.execute("INSERT OR REPLACE INTO dashboard_templates VALUES (?, ?, ?)", 
                       (template_id, payload.get("name", "Restored View"), payload.get("category", "server")))
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
def get_dashboard_defaults(category: str, dashboard_name: Optional[str] = "Custom"):
    if not category or category == "undefined":
        return []
    
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    derived_template_id = dashboard_name.lower().replace('.', '_').replace('-', '_').replace(' ', '_')
    
    cursor.execute("SELECT COUNT(*) FROM dashboard_defaults WHERE template_id = ?", (derived_template_id,))
    has_defaults = cursor.fetchone()[0] > 0

    if has_defaults:
        cursor.execute("""
            SELECT w.widget_id, w.widget_name 
            FROM dashboard_defaults d
            JOIN widgets w ON d.widget_id = w.widget_id
            WHERE d.template_id = ?
        """, (derived_template_id,))
        rows = cursor.fetchall()
    else:
        cursor.execute("SELECT widget_id, widget_name FROM widgets WHERE category_tag = ?", (category,))
        rows = cursor.fetchall()
        
        if len(rows) == 0:
            clean_name = dashboard_name.replace('_', ' ').replace('-', ' ')
            custom_widgets = [
                (f"widget_{derived_template_id}_health", f"{clean_name} Core Node Health Index", category),
                (f"widget_{derived_template_id}_load", f"{clean_name} Resource Load Multiplier", category),
                (f"widget_{derived_template_id}_latency", f"{clean_name} Processing Latency Profile (ms)", category),
                (f"widget_{derived_template_id}_throughput", f"{clean_name} Request Ingestion Throughput", category)
            ]
            for w in custom_widgets:
                cursor.execute("INSERT OR IGNORE INTO widgets VALUES (?, ?, ?)", w)
                cursor.execute("INSERT OR IGNORE INTO dashboard_defaults VALUES (?, ?)", (derived_template_id, w[0]))
            conn.commit()
            
            cursor.execute("""
                SELECT w.widget_id, w.widget_name 
                FROM dashboard_defaults d
                JOIN widgets w ON d.widget_id = w.widget_id
                WHERE d.template_id = ?
            """, (derived_template_id,))
            rows = cursor.fetchall()
        
    conn.close()
    return [{"widget_id": r[0], "name": r[1]} for r in rows]

@app.post("/api/v1/dashboards/save")
def save_dashboard(payload: SaveDashboardPayload):
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR REPLACE INTO dashboard_templates VALUES (?, ?, ?)", 
                       (payload.template_id, payload.template_name, payload.category_tag))
        cursor.execute("DELETE FROM dashboard_defaults WHERE template_id = ?", (payload.template_id,))
        for w_id in payload.widgets:
            cursor.execute("INSERT INTO dashboard_defaults VALUES (?, ?)", (payload.template_id, w_id))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

@app.delete("/api/v1/dashboards/delete/{template_id}")
def delete_dashboard(template_id: str):
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