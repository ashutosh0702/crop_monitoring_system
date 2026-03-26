#!/usr/bin/env python3
"""
Demo Data Seed Script
Creates 6 realistic farms across Punjab & Maharashtra for the investor demo.
Run this after `docker compose up -d && alembic upgrade head`.

Usage:
    python seed_demo.py
"""

import requests
import json

BASE_URL = "http://localhost:8000"
DEMO_USER = {
    "phone_number": "+919876543210",
    "full_name": "Dr. Priya Sharma",
    "password": "demo1234"
}

DEMO_FARMS = [
    {
        "name": "Amritsar Wheat Field North",
        "crop_type": "wheat",
        "planting_date": "2026-02-15T00:00:00",
        "boundary": {
            "type": "Polygon",
            "coordinates": [[
                [75.61979133262437, 30.27158327609321],
                [75.61977758919971, 30.270479411124185],
                [75.62122064876687, 30.270479411124185],
                [75.62122752047921, 30.27157140664329],
                [75.61979133262437, 30.27158327609321]
            ]]
        }
    },
    {
        "name": "Ludhiana Rice Paddy East",
        "crop_type": "rice",
        "planting_date": "2026-03-10T00:00:00",
        "boundary": {
            "type": "Polygon",
            "coordinates": [[
                [75.62120003362983, 30.269375533743045],
                [75.62117941849394, 30.26746449086599],
                [75.62253314580184, 30.267428881018773],
                [75.62260186292411, 30.269357729167126],
                [75.62120003362983, 30.269375533743045]
            ]]
        }
    },
    # {
    #     "name": "Nashik Cotton Plot A",
    #     "crop_type": "cotton",
    #     "planting_date": "2025-12-31T00:00:00",
    #     "boundary": {
    #         "type": "Polygon",
    #         "coordinates": [[
    #             [73.7908, 19.9975],
    #             [73.7975, 19.9975],
    #             [73.7975, 20.0035],
    #             [73.7908, 20.0035],
    #             [73.7908, 19.9975],
    #         ]]
    #     }
    # },
    # {
    #     "name": "Pune Sugarcane Block 3",
    #     "crop_type": "sugarcane",
    #     "planting_date": "2025-02-20T00:00:00",
    #     "boundary": {
    #         "type": "Polygon",
    #         "coordinates": [[
    #             [73.8567, 18.5204],
    #             [73.8630, 18.5204],
    #             [73.8630, 18.5260],
    #             [73.8567, 18.5260],
    #             [73.8567, 18.5204],
    #         ]]
    #     }
    # },
    # {
    #     "name": "Patiala Corn Field West",
    #     "crop_type": "corn",
    #     "planting_date": "2025-05-15T00:00:00",
    #     "boundary": {
    #         "type": "Polygon",
    #         "coordinates": [[
    #             [76.3869, 30.3398],
    #             [76.3930, 30.3398],
    #             [76.3930, 30.3450],
    #             [76.3869, 30.3450],
    #             [76.3869, 30.3398],
    #         ]]
    #     }
    # },
    # {
    #     "name": "Jalandhar Wheat South",
    #     "crop_type": "wheat",
    #     "planting_date": "2025-11-20T00:00:00",
    #     "boundary": {
    #         "type": "Polygon",
    #         "coordinates": [[
    #             [75.5762, 31.3260],
    #             [75.5825, 31.3260],
    #             [75.5825, 31.3310],
    #             [75.5762, 31.3310],
    #             [75.5762, 31.3260],
    #         ]]
    #     }
    # },
]


def seed():
    print("🌾 AgroSense Demo Seed Script")
    print("=" * 40)

    # 1. Register user
    print(f"\n1. Registering demo user: {DEMO_USER['phone_number']}")
    r = requests.post(f"{BASE_URL}/auth/register", json=DEMO_USER)
    if r.status_code == 200:
        print(f"   ✅ User created: {DEMO_USER['full_name']}")
    elif r.status_code == 400:
        print(f"   ℹ️  User already exists, continuing...")
    else:
        print(f"   ❌ Registration failed: {r.text}")
        return

    # 2. Login
    print(f"\n2. Logging in...")
    r = requests.post(f"{BASE_URL}/auth/token", data={
        "username": DEMO_USER["phone_number"],
        "password": DEMO_USER["password"],
    })
    if r.status_code != 200:
        print(f"   ❌ Login failed: {r.text}")
        return
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"   ✅ JWT obtained")

    # 3. Get existing farms to avoid duplicates
    response_data = requests.get(f"{BASE_URL}/fields/", headers=headers).json()
    existing = response_data.get("items", [])
    existing_names = {f["name"] for f in existing}
    print(f"\n3. Found {len(existing)} existing farms")

    # 4. Create farms
    print(f"\n4. Creating demo farms...")
    created = 0
    for farm in DEMO_FARMS:
        if farm["name"] in existing_names:
            print(f"   ⏩ Skipping '{farm['name']}' (already exists)")
            continue
        r = requests.post(f"{BASE_URL}/fields/", json=farm, headers=headers)
        if r.status_code == 200:
            data = r.json()
            ndvi = data.get("latest_analysis", {})
            stats = ndvi.get("stats", {}) if ndvi else {}
            status = stats.get("status", "?")
            mean = stats.get("mean_ndvi", "?")
            print(f"   ✅ '{farm['name']}' → NDVI: {mean:.3f} ({status})" if isinstance(mean, float) else f"   ✅ '{farm['name']}' created")
            created += 1
        else:
            print(f"   ❌ Failed: '{farm['name']}': {r.text[:100]}")

    print(f"\n{'=' * 40}")
    print(f"✅ Seed complete! Created {created} new farms.")
    print(f"🌐 Open dashboard: http://localhost:5173")
    print(f"📱 Login: {DEMO_USER['phone_number']} / {DEMO_USER['password']}")


if __name__ == "__main__":
    seed()
