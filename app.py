from fastapi import FastAPI, HTTPException
import httpx
from contextlib import asynccontextmanager
from time import time

app = FastAPI()


server_cache = {}

@asynccontextmanager
async def get_client():
    async with httpx.AsyncClient() as client:
        yield client

async def get_game_servers(game_id: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "application/json",
        "Connection": "keep-alive"
    }
    
    
    cache_entry = server_cache.get(game_id)
    current_time = time()
    
    
    if cache_entry and (current_time - cache_entry['timestamp'] < 10):
        print(f"[Cache Hit] Returning cached data for game {game_id} ({int(10 - (current_time - cache_entry['timestamp']))}s remaining)")
        return cache_entry['data']
    try:
        print(f"[Fetching] Getting new server data for game {game_id}...")
        async with get_client() as client:
            response = await client.get(
                f"https://games.roblox.com/v1/games/{game_id}/servers/Public?limit=100",
                headers=headers,
                timeout=5.0
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    
                    server_cache[game_id] = {
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
                
                if cache_entry:
                    return cache_entry['data']
                raise HTTPException(status_code=429, detail="Rate limited and no cached data available")
                
    except (httpx.TimeoutError, httpx.RequestError, httpx.HTTPError) as e:
        print(f"[Error] Failed to fetch game {game_id}, using cached data if available")
        
        if cache_entry:
            return cache_entry['data']
        raise HTTPException(status_code=500, detail="Unable to fetch game servers. Please try again.")

@app.get("/servers/{game_id}")
async def get_servers(game_id: str):
    return await get_game_servers(game_id)