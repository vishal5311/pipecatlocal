import requests
import json

BASE_URL = "http://localhost:8000"

def test_api():
    print(f"Testing API at {BASE_URL}")
    
    # 1. Test Root
    print("\n--- Testing GET / ---")
    try:
        resp = requests.get(f"{BASE_URL}/")
        print(f"Status: {resp.status_code}")
        print(f"Content Type: {resp.headers.get('Content-Type')}")
    except Exception as e:
        print(f"Error: {e}")

    # 2. Test GET /services
    print("\n--- Testing GET /services ---")
    try:
        resp = requests.get(f"{BASE_URL}/services")
        print(f"Status: {resp.status_code}")
        services = resp.json()
        print(f"Services Found: {len(services)}")
        print(f"Sample: {services[0] if services else 'None'}")
    except Exception as e:
        print(f"Error: {e}")

    # 3. Test POST /api/voice-book
    print("\n--- Testing POST /api/voice-book ---")
    booking_data = {
        "name": "Test User",
        "phone": "1234567890",
        "service": "haircut",
        "date": "tomorrow",
        "time": "14:00"
    }
    try:
        resp = requests.post(f"{BASE_URL}/api/voice-book", json=booking_data)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.json()}")
    except Exception as e:
        print(f"Error: {e}")

    # 4. Test GET /api/voice-status/{phone}
    print("\n--- Testing GET /api/voice-status/1234567890 ---")
    try:
        resp = requests.get(f"{BASE_URL}/api/voice-status/1234567890")
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.json()}")
    except Exception as e:
        print(f"Error: {e}")

    # 5. Test GET /appointments
    print("\n--- Testing GET /appointments ---")
    try:
        resp = requests.get(f"{BASE_URL}/appointments")
        print(f"Status: {resp.status_code}")
        appointments = resp.json()
        print(f"Appointments Found: {len(appointments)}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_api()
