import os
import aiohttp
import asyncio
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from pydantic import BaseModel
from pathlib import Path
from typing import List, Optional
from datetime import date
from mangum import Mangum

load_dotenv(override=True)

app = FastAPI(title="Maya Salon API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase Config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PIPECAT_CLOUD_API_KEY = os.getenv("PIPECAT_CLOUD_API_KEY")
AGENT_ID = os.getenv("AGENT_ID")

# Persistent Session
class SupabaseClient:
    def __init__(self):
        self.session = None

    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def request(self, method, table, data=None, params=None, select="*"):
        if not SUPABASE_URL or "your_supabase_url" in SUPABASE_URL:
            print("ERROR: Supabase URL not configured correctly in .env")
            return None
        
        url = f"{SUPABASE_URL}/rest/v1/{table}"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        
        if params is None:
            params = {}
        if method == "GET":
            params["select"] = select

        session = await self.get_session()
        try:
            if method == "GET":
                async with session.get(url, headers=headers, params=params) as resp:
                    res_data = await resp.json()
                    if resp.status >= 400:
                        print(f"Supabase Error ({resp.status}): {res_data}")
                    return res_data
            elif method == "POST":
                async with session.post(url, headers=headers, json=data) as resp:
                    res_data = await resp.json()
                    if resp.status >= 400:
                        print(f"Supabase Error ({resp.status}): {res_data}")
                    return res_data
            elif method == "DELETE":
                async with session.delete(url, headers=headers, params=params) as resp:
                    return await resp.json()
        except Exception as e:
            print(f"Request Exception: {e}")
            return None

db = SupabaseClient()

class AppointmentCreate(BaseModel):
    client_name: str
    client_phone: str
    service_id: str
    appointment_date: str
    appointment_time: str

@app.get("/services")
async def get_services():
    data = await db.request("GET", "services")
    if not data or len(data) == 0:
        # Auto-seed if empty
        defaults = [
            {"name": "Luxury Haircut", "description": "Precision cut and style", "duration_minutes": 60, "price": 150.0},
            {"name": "Manicure & Pedicure", "description": "Full nail care", "duration_minutes": 90, "price": 120.0},
            {"name": "Facial", "description": "Deep cleansing", "duration_minutes": 75, "price": 200.0}
        ]
        print("Seeding default services...")
        for d in defaults:
            await db.request("POST", "services", data=d)
        data = await db.request("GET", "services")
    
    if not data or not isinstance(data, list):
        return [{"id": "1", "name": "Luxury Haircut", "price": 150.0}]
    return data

@app.post("/api/voice-book")
async def voice_book(details: dict = Body(...)):
    """Optimized endpoint for voice assistant to book quickly."""
    # 1. Resolve Service ID (Partial match)
    service_query = details.get("service", "").lower()
    services = await db.request("GET", "services")
    
    target_service_id = None
    if services and isinstance(services, list):
        for s in services:
            if service_query in s.get("name", "").lower() or s.get("name", "").lower() in service_query:
                target_service_id = s["id"]
                break
        if not target_service_id and services:
            target_service_id = services[0]["id"]

    # 2. Handle relative dates
    app_date = details.get("date", "").lower()
    from datetime import timedelta
    if "tomorrow" in app_date:
        app_date = str(date.today() + timedelta(days=1))
    elif "today" in app_date or not app_date:
        app_date = str(date.today())
    # Ensure it's not a weird string if it's not today/tomorrow
    elif len(app_date) < 5:
        app_date = str(date.today())

    # 3. Prepare Booking Data
    booking_data = {
        "client_name": details.get("name", "Unknown Caller"),
        "client_phone": details.get("phone", "Unknown"),
        "service_id": target_service_id,
        "appointment_date": app_date,
        "appointment_time": details.get("time", "10:00")
    }
    
    # 3. Insert
    res = await db.request("POST", "appointments", data=booking_data)
    return {"status": "success", "data": res}

@app.get("/api/voice-status/{phone}")
async def voice_status(phone: str):
    data = await db.request("GET", "appointments", params={"client_phone": f"eq.{phone}"}, select="*,services(name)")
    if not data or not isinstance(data, list):
        return {"status": "not_found"}
    return {"status": "found", "appointment": data[0]}

@app.get("/appointments")
async def get_appointments():
    data = await db.request("GET", "appointments", select="*,services(name)")
    if data is None:
        raise HTTPException(status_code=500, detail="Database connection failed. Check SUPABASE_URL and SUPABASE_KEY.")
    if not isinstance(data, list):
        return []
    return data

@app.get("/api/health")
async def health():
    return {"status": "ok", "supabase": supabase is not None}

@app.get("/")
async def root():
    html_path = Path("index.html")
    if html_path.exists():
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return {"message": "Maya Salon API is running under /api"}

@app.post("/api/start-bot")
async def start_bot():
    """Start a Pipecat Cloud agent session."""
    if not PIPECAT_CLOUD_API_KEY or not AGENT_ID:
        raise HTTPException(status_code=500, detail="Pipecat Cloud not configured")
    
    url = f"https://api.pipecat.ai/v1/agents/{AGENT_ID}/start"
    headers = {
        "Authorization": f"Bearer {PIPECAT_CLOUD_API_KEY}",
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers) as resp:
            if resp.status != 200:
                err = await resp.text()
                print(f"Pipecat Cloud Error: {err}")
                raise HTTPException(status_code=resp.status, detail="Failed to start agent")
            return await resp.json()

# Netlify Function Handler
handler = Mangum(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
