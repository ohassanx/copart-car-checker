#!/usr/bin/env python3
"""
Copart Car Checker
Monitors Copart UK for new car listings matching specific criteria:
- Category: U (Undamaged/Unrecorded)
- Year: 2020-2027
- Has V5 document
- Damage: Minor or None
- Transmission: Automatic
- Mileage: 0-80,000 miles
- All makes and models
"""
import os
import json
import requests
from typing import Optional, Set, Dict, List
from pathlib import Path

BOT_TOKEN: Optional[str] = None
CHAT_ID: Optional[str] = None

# File to store previously seen car IDs
STATE_FILE = Path(__file__).parent / "seen_cars.json"

# Copart search URL (for all vehicles)
SEARCH_URL = "https://www.copart.co.uk/vehicles"

# Search criteria - Category U only, all makes/models
SEARCH_PARAMS = {
    "searchCriteria": json.dumps({
        "query": ["*"],
        "filter": {
            "TITL": ["sale_title_type:U"],  # Category U only
            "YEAR": ["lot_year:[2020 TO 2027]"],
            "V5": ["v5_document_number:*"],
            "PRID": ["damage_type_code:DAMAGECODE_MN", "damage_type_code:DAMAGECODE_NO"],
            "TMTP": ["transmission_type:\"Automatic\""],
            "ODM": ["odometer_reading_received:[0 TO 80000]"]
        },
        "searchName": "",
        "watchListOnly": False,
        "freeFormSearch": False
    })
}


def startup():
    """Load environment variables"""
    global BOT_TOKEN, CHAT_ID
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    CHAT_ID = os.environ.get("CHAT_ID")
    if not BOT_TOKEN or not CHAT_ID:
        raise ValueError("BOT_TOKEN and CHAT_ID environment variables must be set.")


def notify(msg: str):
    """Send Telegram notification"""
    startup()

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = None
    try:
        response = requests.post(url, json={"chat_id": CHAT_ID, "text": msg}, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data}")
        print("✓ Notification sent successfully")
    except Exception as e:
        print("Failed to send Telegram message:", e)
        if response is not None:
            print("Telegram response status:", response.status_code)
            print("Telegram response body:", response.text)
        raise


def load_seen_cars() -> Set[str]:
    """Load previously seen car IDs from state file"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                return set(data.get("car_ids", []))
        except Exception as e:
            print(f"Warning: Could not load state file: {e}")
            return set()
    return set()


def save_seen_cars(car_ids: Set[str]):
    """Save seen car IDs to state file"""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump({"car_ids": list(car_ids)}, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save state file: {e}")


def fetch_copart_cars() -> Dict:
    """
    Fetch current Category U car listings from Copart

    Uses the actual Copart public vehicleFinder API endpoint
    """
    api_url = "https://www.copart.co.uk/public/vehicleFinder/search"

    headers = {
        "Host": "www.copart.co.uk",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Connection": "keep-alive",
        "Referer": "https://www.copart.co.uk/lotSearchResults",
        "Cache-Control": "max-age=0"
    }

    # Build search payload in DataTables format
    # Filter for Category U, Year 2020-2027, Has V5, Automatic, Minor/No damage, 0-80k miles
    misc_filter = "#TITL:sale_title_type:U #LotYear:[2020 TO 2027] #V5:v5_document_number:* #TMTP:transmission_type:Automatic (#PRID:damage_type_code:DAMAGECODE_MN OR #PRID:damage_type_code:DAMAGECODE_NO) #ODM:odometer_reading:[0 TO 80000]"

    payload = {
        "draw": "1",
        "start": "0",
        "length": "100",  # Get up to 100 results
        "page": "1",
        "size": "100",
        "query": "*",
        "sort": "auction_date_type desc,auction_date_utc asc",
        "filter": {
            "MISC": misc_filter
        }
    }

    try:
        print(f"Attempting to fetch from Copart UK API...")
        print(f"URL: {api_url}")

        # Convert payload to form-urlencoded format
        import urllib.parse
        form_data = {
            "draw": payload["draw"],
            "start": payload["start"],
            "length": payload["length"],
            "page": payload["page"],
            "size": payload["size"],
            "query": payload["query"],
            "sort": payload["sort"],
            "filter[MISC]": misc_filter
        }

        response = requests.post(api_url, data=form_data, headers=headers, timeout=20)

        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            try:
                data = response.json()
                print(f"✓ Success! Got response from Copart API")

                # Extract result summary
                total = data.get("data", {}).get("results", {}).get("totalElements", 0)
                print(f"Total matching cars: {total}")

                return data
            except json.JSONDecodeError:
                print(f"Response is not valid JSON")
                print(f"Response preview: {response.text[:500]}")
                return {"cars": [], "total": 0, "error": "Invalid JSON response"}
        else:
            print(f"API request failed with status {response.status_code}")
            print(f"Response preview: {response.text[:500]}")
            return {"cars": [], "total": 0, "error": f"HTTP {response.status_code}"}

    except Exception as e:
        print(f"Error fetching from Copart: {e}")
        import traceback
        traceback.print_exc()
        return {"cars": [], "total": 0, "error": str(e)}


def extract_car_ids(data: Dict) -> Set[str]:
    """Extract car/lot IDs from Copart response"""
    car_ids = set()

    # Handle Copart vehicleFinder API response structure
    if "data" in data and "results" in data["data"]:
        results_data = data["data"]["results"]

        # Check if it has content list
        if "content" in results_data:
            for lot in results_data["content"]:
                # Use lotNumberStr or ln as the lot ID
                lot_id = str(lot.get("lotNumberStr", lot.get("ln", "")))
                if lot_id:
                    car_ids.add(lot_id)
    # Fallback: Try different response structures
    elif "lots" in data:
        for lot in data["lots"]:
            car_ids.add(str(lot.get("lotNumberStr", lot.get("ln", ""))))
    elif "results" in data:
        for result in data["results"]:
            car_ids.add(str(result.get("lotNumber", result.get("id", ""))))
    elif "cars" in data:
        for car in data["cars"]:
            car_ids.add(str(car.get("id", car.get("lot_id", ""))))

    return {cid for cid in car_ids if cid}  # Remove empty strings


def format_car_notification(new_cars: Set[str], total_count: int) -> str:
    """Format notification message for new cars"""
    if len(new_cars) == 1:
        msg = f"🚗 New Copart Alert!\n\n1 new car matching your criteria on Copart UK.\n"
    else:
        msg = f"🚗 New Copart Alert!\n\n{len(new_cars)} new cars matching your criteria on Copart UK.\n"

    msg += f"\nTotal listings: {total_count}"
    msg += f"\n\nCriteria:"
    msg += f"\n• Category: U (Undamaged/Unrecorded)"
    msg += f"\n• Year: 2020-2027"
    msg += f"\n• Transmission: Automatic"
    msg += f"\n• Mileage: 0-80,000 miles"
    msg += f"\n• Damage: Minor or None"
    msg += f"\n• Has V5 document"
    msg += f"\n• All makes & models"
    msg += f"\n\nView: {SEARCH_URL}"

    return msg


def main():
    """Main execution function"""
    print("="*60)
    print("COPART CAR CHECKER (CATEGORY U)")
    print("="*60)

    # Load previously seen cars
    seen_cars = load_seen_cars()
    print(f"Previously seen cars: {len(seen_cars)}")

    # Fetch current listings
    data = fetch_copart_cars()
    current_cars = extract_car_ids(data)

    # Get total count from response
    total_count = 0
    if "data" in data and "results" in data["data"]:
        total_count = data["data"]["results"].get("totalElements", len(current_cars))
    else:
        total_count = data.get("total", len(current_cars))

    print(f"Current cars found: {len(current_cars)}")
    print(f"Total count: {total_count}")

    # Detect new cars
    new_cars = current_cars - seen_cars

    if new_cars:
        print(f"\n🎉 Found {len(new_cars)} new car(s)!")
        print(f"New car IDs: {sorted(new_cars)}")

        # Send notification
        try:
            message = format_car_notification(new_cars, total_count)
            notify(message)
        except Exception as e:
            print(f"Failed to send notification: {e}")
    else:
        print("\nℹ No new cars found")

    # Update seen cars
    if current_cars:
        save_seen_cars(current_cars)
        print(f"\n✓ State updated with {len(current_cars)} car(s)")

    print("="*60)

    return {
        "ok": True,
        "new_cars_count": len(new_cars),
        "total_count": total_count,
        "previously_seen": len(seen_cars),
        "currently_seen": len(current_cars)
    }


if __name__ == "__main__":
    result = main()
    print(f"\nResult: {json.dumps(result, indent=2)}")
