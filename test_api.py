import requests
import json

BOT_URL = "http://127.0.0.1:8080"

def test():
    print("1. Healthz")
    r = requests.get(f"{BOT_URL}/v1/healthz")
    print(r.status_code, r.json())
    print("\n2. Metadata")
    r = requests.get(f"{BOT_URL}/v1/metadata")
    print(r.status_code, r.json())
    print("\n3. Context Push (Category)")
    r = requests.post(f"{BOT_URL}/v1/context", json={
      "scope": "category",
      "context_id": "dentists",
      "version": 1,
      "delivered_at": "2026-04-26T09:45:00Z",
      "payload": {
        "slug": "dentists",
        "voice": { "tone": "peer_clinical", "vocab_taboo": ["guaranteed", "100% safe"] },
        "offer_catalog": [],
        "peer_stats": { "avg_rating": 4.4, "avg_ctr": 0.030 },
        "digest": [{"id": "d_2026W17_jida_fluoride", "kind": "research", "title": "3-month fluoride recall cuts caries 38% better", "source": "JIDA Oct 2026, p.14"}]
      }
    })
    print(r.status_code, r.json())
    
    print("\n4. Context Push (Merchant)")
    r = requests.post(f"{BOT_URL}/v1/context", json={
      "scope": "merchant",
      "context_id": "m_001_drmeera_dentist_delhi",
      "version": 1,
      "delivered_at": "2026-04-26T09:45:30Z",
      "payload": {
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "category_slug": "dentists",
        "identity": { "name": "Dr. Meera's Dental Clinic", "city": "Delhi" },
        "subscription": { "status": "active", "plan": "Pro", "days_remaining": 82 },
        "performance": { "window_days": 30, "views": 2410, "calls": 18, "directions": 45, "ctr": 0.021, "delta_7d": { "views_pct": 0.18, "calls_pct": -0.05 } }
      }
    })
    print(r.status_code, r.json())

    print("\n5. Context Push (Trigger)")
    r = requests.post(f"{BOT_URL}/v1/context", json={
      "scope": "trigger",
      "context_id": "trg_001_research_digest_dentists",
      "version": 1,
      "delivered_at": "2026-04-26T10:32:00Z",
      "payload": {
        "id": "trg_001_research_digest_dentists",
        "scope": "merchant",
        "kind": "research_digest",
        "source": "external",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": None,
        "payload": {
          "category": "dentists",
          "top_item_id": "d_2026W17_jida_fluoride"
        },
        "urgency": 2,
        "suppression_key": "research:dentists:2026-W17",
        "expires_at": "2026-05-03T00:00:00Z"
      }
    })
    print(r.status_code, r.json())

    print("\n6. Tick")
    r = requests.post(f"{BOT_URL}/v1/tick", json={
      "now": "2026-04-26T10:35:00Z",
      "available_triggers": ["trg_001_research_digest_dentists"]
    })
    print(r.status_code, json.dumps(r.json(), indent=2))
    
    actions = r.json().get("actions", [])
    if actions:
        conv_id = actions[0]["conversation_id"]
        print("\n7. Reply (Auto-Reply)")
        r = requests.post(f"{BOT_URL}/v1/reply", json={
          "conversation_id": conv_id,
          "merchant_id": "m_001_drmeera_dentist_delhi",
          "customer_id": None,
          "from_role": "merchant",
          "message": "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.",
          "received_at": "2026-04-26T10:42:00Z",
          "turn_number": 2
        })
        print(r.status_code, json.dumps(r.json(), indent=2))
        
        print("\n8. Reply (Engaged)")
        r = requests.post(f"{BOT_URL}/v1/reply", json={
          "conversation_id": conv_id,
          "merchant_id": "m_001_drmeera_dentist_delhi",
          "customer_id": None,
          "from_role": "merchant",
          "message": "Yes please send the abstract",
          "received_at": "2026-04-26T10:45:00Z",
          "turn_number": 3
        })
        print(r.status_code, json.dumps(r.json(), indent=2))

if __name__ == "__main__":
    test()
