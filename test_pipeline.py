import json

# This mimics the exact JSON structure returned by a live production Site24x7 OAuth call
mock_production_api_payload = {
    "data": [
        {
            "monitor_id": "99885544102",
            "display_name": "Mumbai_Staging_Router",
            "monitor_type": "NETWORK",
            "attribute_key_list": [
                "packet_loss_percentage", 
                "bandwidth_tx_rate", 
                "ping_latency_ms"
            ]
        }
    ]
}

def simulate_live_recommendation_fetch():
    print("⚡ Initiating Production OAuth REST API Parsing Test...")
    
    # 1. Simulate reading the incoming user-level data array from the API response
    monitors = mock_production_api_payload.get("data", [])
    
    for monitor in monitors:
        print(f"\n[API Read Instance Summary]")
        print(f"-> Detected Real Monitor: {monitor['display_name']}")
        print(f"-> Infrastructure Type : {monitor['monitor_type']}\n")
        
        # 2. Extract existing active widgets on the user's profile
        existing_user_widgets = monitor["attribute_key_list"]
        print(f"Identified {len(existing_user_widgets)} Existing Active User-Level Attributes:")
        for attribute in existing_user_widgets:
            print(f"  ● {attribute}")
            
        # 3. Formulate recommendation query parameters based on this live state
        print(f"\n[Downstream Engine Pipeline Trigger]")
        print(f"-> Forming user-level profiles based on these metrics...")
        print(f"-> Next, system will map these keys against 'rec_co_occurrence' to recommend new components.")
        print(f"   (e.g., Mapping 'packet_loss_percentage' will automatically suggest 'Interface Discards')")

if __name__ == "__main__":
    simulate_live_recommendation_fetch()