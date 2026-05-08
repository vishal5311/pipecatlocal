import os
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv(override=True)

async def test_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    
    print(f"Testing Supabase at: {url}")
    
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    
    async with aiohttp.ClientSession() as session:
        # 1. Test connection to REST API
        try:
            async with session.get(f"{url}/rest/v1/", headers=headers) as resp:
                print(f"Base API Response: {resp.status}")
                if resp.status != 200:
                    print(await resp.text())
        except Exception as e:
            print(f"Connection Error: {e}")
            return

        # 2. Check if services table exists
        print("\nChecking 'services' table...")
        async with session.get(f"{url}/rest/v1/services?select=*", headers=headers) as resp:
            print(f"Services Status: {resp.status}")
            data = await resp.json()
            print(f"Services Data: {data}")

        # 3. Check if appointments table exists
        print("\nChecking 'appointments' table...")
        async with session.get(f"{url}/rest/v1/appointments?select=*", headers=headers) as resp:
            print(f"Appointments Status: {resp.status}")
            data = await resp.json()
            print(f"Appointments Data: {data}")

if __name__ == "__main__":
    asyncio.run(test_supabase())
