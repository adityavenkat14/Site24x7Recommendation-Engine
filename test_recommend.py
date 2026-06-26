import sqlite3

def get_recommendations(current_widgets):
    conn = sqlite3.connect('metrics_engine.db')
    cursor = conn.cursor()
    
    # Format our list of active widgets for a SQL query (e.g., ['k8s_cpu'] becomes ('k8s_cpu'))
    if len(current_widgets) == 1:
        widget_filter = f"('{current_widgets[0]}')"
    else:
        widget_filter = str(tuple(current_widgets))
        
    # Query rules where widget_a is on the dashboard, but widget_b isn't yet!
    query = f"""
        SELECT widget_b_id, widget_name, confidence_score 
        FROM rec_co_occurrence
        JOIN widgets ON rec_co_occurrence.widget_b_id = widgets.widget_id
        WHERE widget_a_id IN {widget_filter}
          AND widget_b_id NOT IN {widget_filter}
        ORDER BY confidence_score DESC
        LIMIT 3
    """
    
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return results

# --- SIMULATION ---
# Let's pretend a user just dragged the "Kubernetes Node CPU" widget onto their new dashboard
user_dashboard = ['k8s_cpu']

print(f"User currently has these widgets on their dashboard: {user_dashboard}\n")
print("💡 Amazon-style recommendations for this dashboard:")
print("-" * 60)

recommendations = get_recommendations(user_dashboard)

if not recommendations:
    print("No recommendations found for this combination.")
else:
    for item in recommendations:
        widget_id, name, confidence = item
        print(f"➡️ Add Next: {name} ({widget_id}) | 🎯 Match Confidence: {confidence*100:.0f}%")