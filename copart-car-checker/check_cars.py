#!/usr/bin/env python3
"""
Copart Car Checker
Monitors Copart UK for new car listings matching specific criteria:
- Has V5 document (NOT Category A or B)
- Year: 2020-2027
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
    Fetch current car listings from Copart

    Uses the actual Copart public lots search-results API endpoint
    """
    api_url = "https://www.copart.co.uk/public/lots/search-results"

    headers = {
        "Host": "www.copart.co.uk",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Connection": "keep-alive",
        "Referer": "https://www.copart.co.uk/lotSearchResults",
        "Cache-Control": "max-age=0"
    }

    # Build search payload - exact format from Copart
    payload = {
        "query": ["*"],
        "filter": {
            "YEAR": ["lot_year:[2020 TO 2027]"],
            "PRID": [
                "damage_type_code:DAMAGECODE_MN",
                "damage_type_code:DAMAGECODE_NO"
            ],
            "TMTP": ['transmission_type:"Automatic"'],
            "V5": ["v5_document_number:* AND -sale_title_type:B AND -sale_title_type:A"],
            "ODM": ["odometer_reading_received:[0 TO 80000]"]
        },
        "sort": [
            "lot_year desc",  # Sort by year (newest first)
            "auction_date_utc asc"
        ],
        "page": 0,
        "size": 100,  # Get up to 100 results
        "start": 0,
        "watchListOnly": False,
        "freeFormSearch": False,
        "hideImages": False,
        "defaultSort": True,
        "specificRowProvided": False,
        "displayName": "",
        "searchName": "",
        "backUrl": "",
        "includeTagByField": {},
        "rawParams": {}
    }

    try:
        print(f"Attempting to fetch from Copart UK API...")
        print(f"URL: {api_url}")

        response = requests.post(api_url, json=payload, headers=headers, timeout=20)

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
                return {"data": {"results": {"content": [], "totalElements": 0}}, "error": "Invalid JSON response"}
        else:
            print(f"API request failed with status {response.status_code}")
            print(f"Response preview: {response.text[:500]}")
            return {"data": {"results": {"content": [], "totalElements": 0}}, "error": f"HTTP {response.status_code}"}

    except Exception as e:
        print(f"Error fetching from Copart: {e}")
        import traceback
        traceback.print_exc()
        return {"data": {"results": {"content": [], "totalElements": 0}}, "error": str(e)}


def extract_cars(data: Dict) -> Dict[str, Dict]:
    """Extract car details from Copart response

    Returns a dict mapping lot_id -> car_details
    """
    cars = {}

    # Handle Copart lots/search-results API response structure
    if "data" in data and "results" in data["data"]:
        results_data = data["data"]["results"]

        # Check if it has content list
        if "content" in results_data:
            for lot in results_data["content"]:
                # Use ln (lot number) as the lot ID
                lot_id = str(lot.get("ln", ""))
                if lot_id:
                    cars[lot_id] = {
                        "lot_id": lot_id,
                        "lot_url": lot.get("ldu", ""),  # Lot detail URL slug
                        "year": lot.get("lcy"),  # Lot year
                        "make": lot.get("mkn"),  # Make name
                        "model": lot.get("lm"),  # Lot model
                        "description": lot.get("ld"),  # Lot description
                        "damage": lot.get("dd"),  # Damage description
                        "odometer": lot.get("orr"),  # Odometer reading
                        "transmission": lot.get("tmtp"),  # Transmission type
                        "engine": lot.get("egn"),  # Engine
                        "fuel_type": lot.get("ft"),  # Fuel type
                        "sale_title": lot.get("ts"),  # Title status
                        "current_bid": lot.get("hb"),  # High bid
                        "auction_date": lot.get("ad"),  # Auction date
                        "location": lot.get("yn"),  # Yard name
                    }

    return cars


def extract_car_ids(data: Dict) -> Set[str]:
    """Extract car/lot IDs from Copart response"""
    cars = extract_cars(data)
    return set(cars.keys())


def format_car_notification(new_car_ids: Set[str], all_cars: Dict[str, Dict], total_count: int) -> List[str]:
    """Format notification message for new cars

    Returns a list of messages (split if too long for Telegram's 4096 char limit)
    """
    messages = []

    if len(new_car_ids) == 0:
        return messages

    # Header
    header = f"🚗 New Copart Alert!\n\n{len(new_car_ids)} new car(s) matching your criteria:\n"
    header += f"\n{'='*40}\n"

    current_msg = header
    car_count = 0

    # Sort car IDs by year (newest first), then by lot_id
    def get_sort_key(lot_id):
        car = all_cars.get(lot_id, {})
        year = car.get("year", 0) or 0  # Handle None
        return (-year, lot_id)  # Negative year for descending order

    for lot_id in sorted(new_car_ids, key=get_sort_key):
        car = all_cars.get(lot_id, {})

        # Format car details
        car_info = f"\n"

        # Main details
        year = car.get("year", "N/A")
        make = car.get("make", "Unknown")
        model = car.get("model", "Unknown")
        car_info += f"📍 {year} {make} {model}\n"

        # Additional details
        damage = car.get("damage", "N/A")
        if damage:
            car_info += f"   Damage: {damage}\n"

        odometer = car.get("odometer")
        if odometer:
            car_info += f"   Mileage: {odometer:,} miles\n"

        transmission = car.get("transmission", "")
        if transmission:
            car_info += f"   Transmission: {transmission}\n"

        current_bid = car.get("current_bid")
        if current_bid:
            car_info += f"   Current Bid: £{current_bid:,}\n"

        location = car.get("location", "")
        if location:
            car_info += f"   Location: {location}\n"

        # Direct link using proper Copart URL format: /lot/{ln}/{ldu}
        lot_url = car.get("lot_url", "")
        if lot_url:
            car_info += f"   🔗 https://www.copart.co.uk/lot/{lot_id}/{lot_url}\n"
        else:
            # Fallback to simple lot number URL
            car_info += f"   🔗 https://www.copart.co.uk/lot/{lot_id}\n"
        car_info += f"\n{'='*40}\n"

        # Check if adding this car would exceed Telegram's limit (4096 chars)
        if len(current_msg + car_info) > 4000:
            # Save current message and start a new one
            messages.append(current_msg)
            current_msg = f"🚗 Continued ({car_count + 1}/{len(new_car_ids)})...\n\n"
            current_msg += car_info
        else:
            current_msg += car_info

        car_count += 1

    # Add footer to last message
    footer = f"\nTotal listings: {total_count}\n"
    footer += f"\n📋 Search Criteria:\n"
    footer += f"• Has V5 (NOT Cat A or B)\n"
    footer += f"• Year: 2020-2027\n"
    footer += f"• Transmission: Automatic\n"
    footer += f"• Mileage: 0-80,000 miles\n"
    footer += f"• Damage: Minor or None\n"

    if len(current_msg + footer) > 4000:
        messages.append(current_msg)
        messages.append(footer)
    else:
        current_msg += footer
        messages.append(current_msg)

    return messages


def main():
    """Main execution function"""
    print("="*60)
    print("COPART CAR CHECKER (CATEGORY U)")
    print("="*60)

    # Load previously seen cars (for duplicate prevention)
    seen_cars = load_seen_cars()
    print(f"Previously seen cars: {len(seen_cars)}")

    # Fetch current listings from Copart API
    data = fetch_copart_cars()
    all_cars = extract_cars(data)
    current_cars = set(all_cars.keys())

    # Get total count from response
    total_count = 0
    if "data" in data and "results" in data["data"]:
        total_count = data["data"]["results"].get("totalElements", len(current_cars))
    else:
        total_count = data.get("total", len(current_cars))

    print(f"Current cars found: {len(current_cars)}")
    print(f"Total count: {total_count}")

    # Detect NEW cars only (current cars that we haven't seen before)
    # This prevents sending duplicate notifications
    new_cars = current_cars - seen_cars

    if new_cars:
        print(f"\n🎉 Found {len(new_cars)} new car(s)!")
        print(f"New car IDs: {sorted(new_cars)}")

        # Send notification(s) ONLY for new cars (sorted by year, newest first)
        try:
            messages = format_car_notification(new_cars, all_cars, total_count)
            for i, message in enumerate(messages):
                print(f"\nSending notification {i+1}/{len(messages)}...")
                notify(message)
        except Exception as e:
            print(f"Failed to send notification: {e}")
    else:
        print("\nℹ No new cars found (no duplicates sent)")

    # Save all current cars to state file
    # Next time we run, these will be "seen" and won't trigger notifications
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
