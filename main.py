# Version: 2.0 (discord.py)

import discord
import json
from discord.ext import commands, tasks
from cogs.ticket_system import Ticket_System
from cogs.ticket_commands import Ticket_Command

with open("config.json", mode="r") as config_file:
    config = json.load(config_file)

BOT_TOKEN = config["token"]
GUILD_ID = config["guild_id"]
CATEGORY_ID1 = config["category_id_1"]
CATEGORY_ID2 = config["category_id_2"]

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Bot Started | {bot.user.name}')
    # Slash Commands beim Discord registrieren
    await bot.tree.sync()
    richpresence.start()

@tasks.loop(minutes=1)
async def richpresence():
    guild = bot.get_guild(GUILD_ID)
    category1 = discord.utils.get(guild.categories, id=int(CATEGORY_ID1))
    category2 = discord.utils.get(guild.categories, id=int(CATEGORY_ID2))
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f'Tickets | {len(category1.channels) + len(category2.channels)}'
        )
    )

async def main():
    async with bot:
        await bot.add_cog(Ticket_System(bot))
        await bot.add_cog(Ticket_Command(bot))
        await bot.start(BOT_TOKEN)

import asyncio
asyncio.run(main())