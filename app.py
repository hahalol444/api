from fastapi import FastAPI, HTTPException
import httpx
from contextlib import asynccontextmanager
from time import time
from typing import Optional
import random

app = FastAPI()

server_cache = {}
rate_limit_timers = {}

@asynccontextmanager
async def get_client():
    async with httpx.AsyncClient() as client:
        yield client

async def get_game_servers(game_id: str, cursor: Optional[str] = None):
    headers = {
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/{random.randint(500,600)}.{random.randint(1,99)} (KHTML, like Gecko) Chrome/{random.randint(90,100)}.0.{random.randint(1000,9999)}.{random.randint(1,999)} Safari/{random.randint(500,600)}.{random.randint(1,99)}",
        "Accept": "application/json",
        "Connection": "keep-alive",
        "X-Forwarded-For": f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}",
        "CF-IPCountry": random.choice(["US", "GB", "CA", "AU", "DE", "FR"])
    }
    
    cache_key = f"{game_id}_{cursor}" if cursor else game_id
    cache_entry = server_cache.get(cache_key)
    current_time = time()
    
    rate_limit_end = rate_limit_timers.get(game_id, 0)
    if current_time < rate_limit_end:
        print(f"[Rate Limited] Using cached data for game {game_id} ({int(rate_limit_end - current_time)}s remaining)")
        if cache_entry:
            return cache_entry['data']
        raise HTTPException(status_code=429, detail="Rate limited and no cached data available")
    
    if cache_entry and (current_time - cache_entry['timestamp'] < 10):
        print(f"[Cache Hit] Returning cached data for game {game_id} ({int(10 - (current_time - cache_entry['timestamp']))}s remaining)")
        return cache_entry['data']
    
    try:
        print(f"[Fetching] Getting new server data for game {game_id}...")
        url = f"https://games.roblox.com/v1/games/{game_id}/servers/Public?limit=100"
        if cursor:
            url += f"&cursor={cursor}"
            
        async with get_client() as client:
            response = await client.get(
                url,
                headers=headers,
                timeout=5.0,
                follow_redirects=True
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    server_cache[cache_key] = {
                        'data': data,
                        'timestamp': current_time
                    }
                    print(f"[Success] Found {len(data['data'])} servers for game {game_id}")
                    return data
                print(f"[Empty] No servers found for game {game_id}")
                raise HTTPException(status_code=404, detail="No servers found for this game")
            
            if response.status_code == 404:
                print(f"[Not Found] Game {game_id} does not exist")
                raise HTTPException(status_code=404, detail="Game not found")
            
            if response.status_code == 429:
                print(f"[Rate Limited] Using cached data for game {game_id}")
                rate_limit_timers[game_id] = current_time + 5  
                
                if cache_entry:
                    return cache_entry['data']
                raise HTTPException(status_code=429, detail="Rate limited and no cached data available")
                
    except Exception as e:
        print(f"[Error] Failed to fetch game {game_id}, using cached data if available")
        
        if cache_entry:
            return cache_entry['data']
        raise HTTPException(status_code=500, detail="Unable to fetch game servers. Please try again.")

@app.get("/servers/{game_id_with_cursor:path}")
async def get_servers(game_id_with_cursor: str):
    
    if "eyJ" in game_id_with_cursor:
        
        parts = game_id_with_cursor.split("eyJ")
        game_id = parts[0]
        cursor = "eyJ" + parts[1]
    else:
        game_id = game_id_with_cursor
        cursor = None
    return await get_game_servers(game_id, cursor)
