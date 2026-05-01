# Version: 2.0 (discord.py)

import discord
import json
from discord.ext import commands
from cogs.ticket_system import Ticket_System
from cogs.ticket_commands import Ticket_Command
import os
from dotenv import load_dotenv
import asyncio
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO)

with open("config.json", mode="r", encoding="utf-8") as config_file:
    config = json.load(config_file)

BOT_TOKEN = os.getenv("TOKEN")
GUILD_ID = config["guild_id"]

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="?", intents=intents)

@bot.event
async def on_ready():
    print(f'Bot Started | {bot.user.name}')
    await bot.tree.sync()


async def main():
    async with bot:
        await bot.add_cog(Ticket_System(bot))
        await bot.add_cog(Ticket_Command(bot))
        await bot.start(BOT_TOKEN)

asyncio.run(main())