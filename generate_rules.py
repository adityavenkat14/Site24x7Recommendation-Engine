import sqlite3
import pandas as pd
from mlxtend.frequent_patterns import apriori, association_rules

def train_engine():
    # Connect to the database file created by your first script
    conn = sqlite3.connect('metrics_engine.db')
    
    # 1. Pull the dashboard data into a Pandas DataFrame (like an Excel sheet)
    df = pd.read_sql("SELECT template_id AS dashboard_id, widget_id FROM dashboard_defaults", conn)
    
    if df.empty:
        print("No dashboard data found to process.")
        return

    # 2. Pivot the data into a binary matrix (Rows = Dashboards, Columns = Widgets)
    # 1 means the widget is on the dashboard, 0 means it isn't.
    basket = (df.groupby(['dashboard_id', 'widget_id'])['widget_id']
              .count().unstack().reset_index().fillna(0)
              .set_index('dashboard_id'))
    
    # Ensure it's strictly 1s and 0s
    basket_sets = basket.map(lambda x: 1 if x > 0 else 0)
    
    # 3. Find frequent widget combinations using the Apriori algorithm
    frequent_itemsets = apriori(basket_sets, min_support=0.1, use_colnames=True)
    
    # 4. Calculate Amazon-style association rules (Confidence = likelihood of pairing)
    rules = association_rules(frequent_itemsets, metric="confidence", min_threshold=0.3)
    
    # 5. Clear old calculations and save the new rules into the database
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rec_co_occurrence")
    
    for _, row in rules.iterrows():
        for ant in row['antecedents']:
            for con in row['consequents']:
                cursor.execute('''
                    INSERT OR REPLACE INTO rec_co_occurrence 
                    VALUES (?, ?, ?, ?)
                ''', (ant, con, float(row['support']), float(row['confidence'])))
                
    conn.commit()
    conn.close()
    print("🚀 Recommendation engine optimized! Math rules saved to database.")

if __name__ == '__main__':
    train_engine()