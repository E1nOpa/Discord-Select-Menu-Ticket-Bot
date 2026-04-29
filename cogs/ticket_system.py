import discord
import asyncio
import pytz
import json
import sqlite3
from datetime import datetime
import chat_exporter
import io
from discord.ext import commands
from discord import app_commands

with open("config.json", mode="r") as config_file:
    config = json.load(config_file)

GUILD_ID        = config["guild_id"]
TICKET_CHANNEL  = config["ticket_channel_id"]
CATEGORY_ID1    = config["category_id_1"]
CATEGORY_ID2    = config["category_id_2"]
TEAM_ROLE1      = config["team_role_id_1"]
TEAM_ROLE2      = config["team_role_id_2"]
LOG_CHANNEL     = config["log_channel_id"]
TIMEZONE        = config["timezone"]
EMBED_TITLE     = config["embed_title"]
EMBED_DESCRIPTION = config["embed_description"]

conn = sqlite3.connect('Database.db')
cur  = conn.cursor()
cur.execute("""
    CREATE TABLE IF NOT EXISTS ticket (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_name    TEXT,
        discord_id      INTEGER,
        ticket_channel  TEXT,
        ticket_created  TIMESTAMP
    )
""")
conn.commit()


# ─── Helper: Unix-Timestamp ──────────────────────────────────────────────────

def convert_to_unix_timestamp(date_string: str) -> int:
    dt_obj     = datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S")
    berlin_tz  = pytz.timezone('Europe/Berlin')
    dt_obj     = berlin_tz.localize(dt_obj)
    dt_obj_utc = dt_obj.astimezone(pytz.utc)
    return int(dt_obj_utc.timestamp())


# ─── Select-Menu View ────────────────────────────────────────────────────────

class MyView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.select(
        custom_id="support",
        placeholder="Choose a Ticket option",
        options=[
            discord.SelectOption(label="Support1", description="You will get help here!", emoji="❓", value="support1"),
            discord.SelectOption(label="Support2", description="Ask questions here!",     emoji="📛", value="support2"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.defer(ephemeral=True)

        timezone      = pytz.timezone(TIMEZONE)
        creation_date = datetime.now(timezone).strftime('%Y-%m-%d %H:%M:%S')
        user_name     = interaction.user.name
        user_id       = interaction.user.id

        # Prüfen ob User schon ein Ticket hat
        cur.execute("SELECT discord_id FROM ticket WHERE discord_id=?", (user_id,))
        if cur.fetchone() is not None:
            embed = discord.Embed(title="You already have an open Ticket", color=0xff0000)
            await interaction.followup.send(embed=embed, ephemeral=True)
            # Select-Menu zurücksetzen
            embed_main = discord.Embed(title=EMBED_TITLE, description=EMBED_DESCRIPTION, color=discord.Color.blue())
            await interaction.message.edit(embed=embed_main, view=MyView(bot=self.bot))
            return

        if interaction.channel.id != TICKET_CHANNEL:
            return

        value    = select.values[0]
        guild    = self.bot.get_guild(GUILD_ID)
        cat_id   = CATEGORY_ID1 if value == "support1" else CATEGORY_ID2
        role_id  = TEAM_ROLE1   if value == "support1" else TEAM_ROLE2
        welcome  = (
            f'Welcome {interaction.user.mention},\ndescribe your Problem and our Support will help you soon.'
            if value == "support1" else
            f'Welcome {interaction.user.mention},\nhow can I help you?'
        )

        # Datenbankzeile anlegen, Ticket-Nummer holen
        cur.execute(
            "INSERT INTO ticket (discord_name, discord_id, ticket_created) VALUES (?, ?, ?)",
            (user_name, user_id, creation_date)
        )
        conn.commit()
        await asyncio.sleep(1)
        cur.execute("SELECT id FROM ticket WHERE discord_id=?", (user_id,))
        ticket_number = cur.fetchone()[0]

        # Channel erstellen
        category       = self.bot.get_channel(cat_id)
        ticket_channel = await guild.create_text_channel(
            f"ticket-{ticket_number}", category=category, topic=str(interaction.user.id)
        )

        # Berechtigungen setzen
        await ticket_channel.set_permissions(
            guild.get_role(role_id),
            send_messages=True, read_messages=True, add_reactions=False,
            embed_links=True, attach_files=True, read_message_history=True, external_emojis=True
        )
        await ticket_channel.set_permissions(
            interaction.user,
            send_messages=True, read_messages=True, add_reactions=False,
            embed_links=True, attach_files=True, read_message_history=True, external_emojis=True
        )
        await ticket_channel.set_permissions(
            guild.default_role,
            send_messages=False, read_messages=False, view_channel=False
        )

        # Willkommensnachricht im Ticket
        embed = discord.Embed(description=welcome, color=discord.Color.blue())
        await ticket_channel.send(embed=embed, view=CloseButton(bot=self.bot))

        # Channel-ID in DB speichern
        cur.execute("UPDATE ticket SET ticket_channel = ? WHERE id = ?", (ticket_channel.id, ticket_number))
        conn.commit()

        # Bestätigung an User
        embed = discord.Embed(
            description=f'📬 Ticket was Created! Look here --> {ticket_channel.mention}',
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        # Select-Menu zurücksetzen
        await asyncio.sleep(1)
        embed_main = discord.Embed(title=EMBED_TITLE, description=EMBED_DESCRIPTION, color=discord.Color.blue())
        await interaction.message.edit(embed=embed_main, view=MyView(bot=self.bot))


# ─── Close-Button ────────────────────────────────────────────────────────────

class CloseButton(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Delete Ticket 🎫", style=discord.ButtonStyle.blurple, custom_id="close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="Delete Ticket 🎫",
            description="Are you sure you want to delete this Ticket?",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, view=TicketOptions(bot=self.bot))


# ─── Ticket-Options (Confirm Delete) ─────────────────────────────────────────

class TicketOptions(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Delete Ticket 🎫", style=discord.ButtonStyle.red, custom_id="delete")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild      = self.bot.get_guild(GUILD_ID)
        log_ch     = self.bot.get_channel(LOG_CHANNEL)
        ticket_id  = interaction.channel.id

        cur.execute("SELECT id, discord_id, ticket_created FROM ticket WHERE ticket_channel=?", (ticket_id,))
        ticket_data = cur.fetchone()
        if ticket_data is None:
            await interaction.response.send_message("Ticket not found in database.", ephemeral=True)
            return

        t_id, ticket_creator_id, ticket_created = ticket_data
        ticket_creator       = guild.get_member(ticket_creator_id)
        ticket_created_unix  = convert_to_unix_timestamp(ticket_created)
        timezone             = pytz.timezone(TIMEZONE)
        ticket_closed        = datetime.now(timezone).strftime('%Y-%m-%d %H:%M:%S')
        ticket_closed_unix   = convert_to_unix_timestamp(ticket_closed)

        # Transcript erstellen
        transcript = await chat_exporter.export(
            interaction.channel, limit=200, tz_info=TIMEZONE, military_time=True, bot=self.bot
        )
        make_file = lambda: discord.File(
            io.BytesIO(transcript.encode()),
            filename=f"transcript-{interaction.channel.name}.html"
        )

        transcript_info = discord.Embed(
            title=f"Ticket Deleted | {interaction.channel.name}",
            color=discord.Color.blue()
        )
        transcript_info.add_field(name="ID",             value=t_id,                              inline=True)
        transcript_info.add_field(name="Opened by",      value=ticket_creator.mention,            inline=True)
        transcript_info.add_field(name="Closed by",      value=interaction.user.mention,          inline=True)
        transcript_info.add_field(name="Ticket Created", value=f"<t:{ticket_created_unix}:f>",   inline=True)
        transcript_info.add_field(name="Ticket Closed",  value=f"<t:{ticket_closed_unix}:f>",    inline=True)

        embed = discord.Embed(description='Ticket is deleting in 5 seconds.', color=0xff0000)
        await interaction.response.send_message(embed=embed)

        try:
            await ticket_creator.send(embed=transcript_info, file=make_file())
        except discord.Forbidden:
            transcript_info.add_field(name="Error", value="Ticket Creator DMs are disabled", inline=True)

        await log_ch.send(embed=transcript_info, file=make_file())
        await asyncio.sleep(3)
        await interaction.channel.delete(reason="Ticket Deleted")
        cur.execute("DELETE FROM ticket WHERE discord_id=?", (ticket_creator_id,))
        conn.commit()


# ─── Cog ─────────────────────────────────────────────────────────────────────

class Ticket_System(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print('Bot Loaded  | ticket_system.py ✅')
        self.bot.add_view(MyView(bot=self.bot))
        self.bot.add_view(CloseButton(bot=self.bot))
        self.bot.add_view(TicketOptions(bot=self.bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(Ticket_System(bot))