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
    allow_methods=["*"],
    allow_headers=["*"],
)

class SaveDashboardPayload(BaseModel):
    template_id: str
    template_name: str
    category_tag: str
    widgets: List[str]

@app.get("/", response_class=HTMLResponse)
def get_ui():
    with open("index.html", "r") as f: 
        return f.read()

@app.get("/api/v1/dashboards")
def get_dashboards():
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    
    # Check if dashboard_templates exists to prevent startup errors
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dashboard_templates'")
    if not cursor.fetchone():
        conn.close()
        return []
        
    cursor.execute("SELECT template_id, template_name, category_tag FROM dashboard_templates")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "category": r[2]} for r in rows]

@app.get("/api/v1/dashboard-defaults")
def get_dashboard_defaults(category: str, dashboard_name: Optional[str] = "Custom"):
    if not category or category == "undefined":
        return []
    
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    
    # Check if widgets table has anything for this category tag
    cursor.execute("SELECT COUNT(*) FROM widgets WHERE category_tag = ?", (category,))
    if cursor.fetchone()[0] == 0:
        custom_widgets = [
            (f"widget_{category}_traffic", f"{dashboard_name} Traffic Volume", category),
            (f"widget_{category}_latency", f"{dashboard_name} Response Latency (ms)", category),
            (f"widget_{category}_errors", f"{dashboard_name} Error Rate (%)", category),
            (f"widget_{category}_success", f"{dashboard_name} Transaction Success Core Index", category)
        ]
        for w in custom_widgets:
            cursor.execute("INSERT OR IGNORE INTO widgets VALUES (?, ?, ?)", w)
        conn.commit()

    # MODIFIED: Instead of just pulling blindly from widgets catalog, we cross-reference 
    # the exact template relationships mapped out inside dashboard_defaults if a matching template exists.
    derived_template_id = dashboard_name.lower().replace('.', '_').replace('-', '_').replace(' ', '_')
    
    cursor.execute("SELECT COUNT(*) FROM dashboard_defaults WHERE template_id = ?", (derived_template_id,))
    has_defaults = cursor.fetchone()[0] > 0

    if has_defaults:
        # Pull specific mapped default choices for preset templates
        cursor.execute("""
            SELECT w.widget_id, w.widget_name 
            FROM dashboard_defaults d
            JOIN widgets w ON d.widget_id = w.widget_id
            WHERE d.template_id = ?
        """, (derived_template_id,))
    else:
        # Fall back to pulling items by general category tag matching for fresh typing options
        cursor.execute("SELECT widget_id, widget_name FROM widgets WHERE category_tag = ?", (category,))
        
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

@app.get("/api/v1/recommendations")
def get_recommendations(widget_id: List[str] = Query(None), category: Optional[str] = None):
    if not category or category == "":
        return {"recommendations": []}

    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    
    compiled_recs = []
    seen_widget_ids = set(widget_id) if widget_id else set()

    # 1. Look for explicit co-occurrence mappings if items are on the canvas
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

    # 2. Find any widgets in the catalog belonging to this dashboard's type that are unselected
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
            base_confidence -= 2.0  # Slightly lower confidence score for ranking variety

    # 3. GLOBAL INFRASTRUCTURE CROSS-SELL: Fallback pillars so recommendation panel is never empty
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

    # Sort everything uniformly by confidence score percentage
    compiled_recs = sorted(compiled_recs, key=lambda x: x['confidence'], reverse=True)
    conn.close()
    return {"recommendations": compiled_recs[:6]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)