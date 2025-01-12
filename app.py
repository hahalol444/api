from fastapi import FastAPI, HTTPException
import httpx
from contextlib import asynccontextmanager
from time import time
from typing import Optional, List, Dict
import random
from fp.fp import FreeProxy
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging

app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

server_cache: Dict[str, dict] = {}
rate_limit_timers: Dict[str, float] = {}
proxy_list: List[str] = []
last_proxy_refresh = 0
PROXY_REFRESH_INTERVAL = 300
MAX_PROXIES = 5
proxy_performance: Dict[str, dict] = {}
client_pool: Dict[str, httpx.AsyncClient] = {}
executor = ThreadPoolExecutor(max_workers=5)

def check_proxy(proxy: str) -> bool:
    try:
        with httpx.Client(
            proxies={"all://": proxy},
            verify=False,
            timeout=1.0
        ) as client:
            resp = client.get("https://games.roblox.com")
            return resp.status_code == 200
    except:
        return False

async def refresh_proxy_list():
    global proxy_list, last_proxy_refresh, client_pool
    current_time = time()
    
    if current_time - last_proxy_refresh < PROXY_REFRESH_INTERVAL and len(proxy_list) >= 2:
        return
        
    logger.info("[Proxy] Refreshing proxy list...")
    
    try:
        new_proxies = set()
        
        for _ in range(MAX_PROXIES * 1.5):
            try:
                proxy = FreeProxy(https=True, timeout=0.5).get()
                if proxy:
                    new_proxies.add(proxy)
                if len(new_proxies) >= MAX_PROXIES:
                    break
            except:
                continue
        
        loop = asyncio.get_event_loop()
        proxy_checks = [
            loop.run_in_executor(executor, check_proxy, proxy)
            for proxy in new_proxies
        ]
        results = await asyncio.gather(*proxy_checks)
        
        working_proxies = [
            proxy for proxy, is_working in zip(new_proxies, results)
            if is_working
        ][:MAX_PROXIES]
        
        proxy_list = working_proxies
        
        for client in client_pool.values():
            await client.aclose()
        
        client_pool = {
            proxy: httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(retries=1),
                proxies={"all://": proxy},
                verify=False,
                timeout=3.0,
                limits=httpx.Limits(max_keepalive_connections=3, max_connections=5)
            )
            for proxy in working_proxies
        }
        
        last_proxy_refresh = current_time
        logger.info(f"[Proxy] Found {len(proxy_list)} working proxies")
        
    except Exception as e:
        logger.error(f"[Proxy] Error refreshing proxies: {str(e)}")
        if not proxy_list:
            proxy_list = [""]

@asynccontextmanager
async def get_client():
    await refresh_proxy_list()
    
    if not proxy_list or not client_pool:
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(retries=1),
            timeout=3.0,
            limits=httpx.Limits(max_keepalive_connections=3, max_connections=5)
        ) as client:
            yield client
        return
    
    proxy = random.choice(proxy_list)
    client = client_pool.get(proxy)
    
    if client:
        try:
            yield client
        except Exception as e:
            try:
                proxy_list.remove(proxy)
                await client.aclose()
                del client_pool[proxy]
            except:
                pass
            raise e
    else:
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(retries=1),
            timeout=3.0
        ) as client:
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
        logger.info(f"[Rate Limited] Using cached data for game {game_id} ({int(rate_limit_end - current_time)}s remaining)")
        if cache_entry:
            return cache_entry['data']
        raise HTTPException(status_code=429, detail="Rate limited and no cached data available")
    
    if cache_entry and (current_time - cache_entry['timestamp'] < 10):
        logger.info(f"[Cache Hit] Returning cached data for game {game_id} ({int(10 - (current_time - cache_entry['timestamp']))}s remaining)")
        return cache_entry['data']
    
    try:
        logger.info(f"[Fetching] Getting new server data for game {game_id}...")
        url = f"https://games.roblox.com/v1/games/{game_id}/servers/Public?limit=100"
        if cursor:
            url += f"&cursor={cursor}"
            
        async with get_client() as client:
            response = await client.get(
                url,
                headers=headers,
                timeout=3.0,
                follow_redirects=True
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    server_cache[cache_key] = {
                        'data': data,
                        'timestamp': current_time
                    }
                    logger.info(f"[Success] Found {len(data['data'])} servers for game {game_id}")
                    return data
                logger.warning(f"[Empty] No servers found for game {game_id}")
                raise HTTPException(status_code=404, detail="No servers found for this game")
            
            if response.status_code == 404:
                logger.warning(f"[Not Found] Game {game_id} does not exist")
                raise HTTPException(status_code=404, detail="Game not found")
            
            if response.status_code == 429:
                logger.warning(f"[Rate Limited] Using cached data for game {game_id}")
                rate_limit_timers[game_id] = current_time + 5  
                
                if cache_entry:
                    return cache_entry['data']
                raise HTTPException(status_code=429, detail="Rate limited and no cached data available")
                
    except Exception as e:
        logger.error(f"[Error] Failed to fetch game {game_id}: {str(e)}")
        
        if cache_entry:
            return cache_entry['data']
        raise HTTPException(status_code=500, detail="Unable to fetch game servers. Please try again.")

@app.get("/servers/{game_id_with_cursor:path}")
async def get_servers(game_id_with_cursor: str):
    try:
        if "eyJ" in game_id_with_cursor:
            parts = game_id_with_cursor.split("eyJ")
            game_id = parts[0]
            cursor = "eyJ" + parts[1]
        else:
            game_id = game_id_with_cursor
            cursor = None
        return await get_game_servers(game_id, cursor)
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
