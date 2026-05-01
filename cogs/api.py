import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()
API_URL = os.getenv("API_URL")
API_TOKEN = os.getenv("API_TOKEN")

async def get_fivem_data(discord_id: int):
    url = f"{API_URL}/e1nopa_system/player/{discord_id}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"authorization": API_TOKEN},
                timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:

                if resp.status == 200:
                    return await resp.json()
                else:
                    print(f"FiveM API Error: Status {resp.status} - {await resp.text()}")

    except Exception as e:
        print("FiveM API Error:", e)

    return None