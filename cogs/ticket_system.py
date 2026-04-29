import discord
import asyncio
import pytz
import json
import sqlite3
from datetime import datetime
import chat_exporter
import io
from discord.ext import commands

with open("config.json", mode="r") as config_file:
    config = json.load(config_file)

GUILD_ID          = config["guild_id"]
TICKET_CHANNEL    = config["ticket_channel_id"]
CATEGORY_ID1      = config["category_id_1"]
CATEGORY_ID2      = config["category_id_2"]
TEAM_ROLE1        = config["team_role_id_1"]
TEAM_ROLE2        = config["team_role_id_2"]
LOG_CHANNEL       = config["log_channel_id"]
TIMEZONE          = config["timezone"]
EMBED_TITLE       = config["embed_title"]
EMBED_DESCRIPTION = config["embed_description"]
MAX_TICKETS_CAT1  = config["max_tickets_cat_1"]
MAX_TICKETS_CAT2  = config["max_tickets_cat_2"]

conn = sqlite3.connect('Database.db')
cur  = conn.cursor()

# Tabellen erstellen
cur.execute("""
    CREATE TABLE IF NOT EXISTS ticket (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_name    TEXT,
        discord_id      INTEGER,
        ticket_channel  TEXT,
        ticket_created  TIMESTAMP,
        category        INTEGER
    )
""")
# Rabatt-Wert Tabelle
cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    )
""")
# Standard-Rabatt falls noch nicht vorhanden
cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rabatt', '0')")
conn.commit()


# ─── Helper ──────────────────────────────────────────────────────────────────

def convert_to_unix_timestamp(date_string: str) -> int:
    dt_obj     = datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S")
    berlin_tz  = pytz.timezone('Europe/Berlin')
    dt_obj     = berlin_tz.localize(dt_obj)
    dt_obj_utc = dt_obj.astimezone(pytz.utc)
    return int(dt_obj_utc.timestamp())

def get_rabatt() -> str:
    cur.execute("SELECT value FROM settings WHERE key='rabatt'")
    row = cur.fetchone()
    return row[0] if row else "0"

def set_rabatt(value: str):
    cur.execute("UPDATE settings SET value=? WHERE key='rabatt'", (value,))
    conn.commit()

def count_user_tickets(user_id: int, category: int) -> int:
    cur.execute(
        "SELECT COUNT(*) FROM ticket WHERE discord_id=? AND category=?",
        (user_id, category)
    )
    return cur.fetchone()[0]


# ─── Modal für Support-Ticket ─────────────────────────────────────────────────

class SupportModal(discord.ui.Modal, title="Support Ticket"):
    anliegen = discord.ui.TextInput(
        label="Was ist dein Anliegen?",
        style=discord.TextStyle.long,
        placeholder="Beschreibe dein Problem so detailliert wie möglich...",
        required=True,
        max_length=1024
    )
    clip = discord.ui.TextInput(
        label="Hast du einen Clip zu deinem Anliegen?",
        style=discord.TextStyle.short,
        placeholder="Link zu deinem Clip (optional)",
        required=False,
        max_length=512
    )

    def __init__(self, bot: commands.Bot, interaction_orig: discord.Interaction):
        super().__init__()
        self.bot              = bot
        self.interaction_orig = interaction_orig  # die ursprüngliche Select-Interaction

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        timezone      = pytz.timezone(TIMEZONE)
        creation_date = datetime.now(timezone).strftime('%Y-%m-%d %H:%M:%S')
        user_name     = interaction.user.name
        user_id       = interaction.user.id

        cur.execute(
            "INSERT INTO ticket (discord_name, discord_id, ticket_created, category) VALUES (?, ?, ?, ?)",
            (user_name, user_id, creation_date, CATEGORY_ID1)
        )
        conn.commit()
        await asyncio.sleep(1)
        cur.execute("SELECT id FROM ticket WHERE discord_id=? AND category=? ORDER BY id DESC LIMIT 1", (user_id, CATEGORY_ID1))
        ticket_number = cur.fetchone()[0]

        guild    = self.bot.get_guild(GUILD_ID)
        category = self.bot.get_channel(CATEGORY_ID1)

        ticket_channel = await guild.create_text_channel(
            f"ticket-{ticket_number}", category=category, topic=str(user_id)
        )
        await ticket_channel.set_permissions(
            guild.get_role(TEAM_ROLE1),
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

        # Willkommens-Embed
        welcome_embed = discord.Embed(
            description=f'Welcome {interaction.user.mention},\ndescribe your Problem and our Support will help you soon.',
            color=discord.Color.blue()
        )
        await ticket_channel.send(embed=welcome_embed, view=CloseButton(bot=self.bot))

        # Formular-Embed
        form_embed = discord.Embed(title="📋 Ticket Details", color=discord.Color.blue())
        form_embed.add_field(name="❓ Anliegen", value=self.anliegen.value, inline=False)
        if self.clip.value:
            form_embed.add_field(name="🎬 Clip", value=self.clip.value, inline=False)
        form_embed.set_footer(text=f"Erstellt von {interaction.user.name}")
        await ticket_channel.send(embed=form_embed)

        # Channel-ID speichern
        cur.execute("UPDATE ticket SET ticket_channel=? WHERE id=?", (ticket_channel.id, ticket_number))
        conn.commit()

        # Bestätigung
        confirm_embed = discord.Embed(
            description=f'📬 Ticket was Created! Look here --> {ticket_channel.mention}',
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)

        # Select-Menü zurücksetzen
        await asyncio.sleep(1)
        main_embed = discord.Embed(title=EMBED_TITLE, description=EMBED_DESCRIPTION, color=discord.Color.blue())
        await self.interaction_orig.message.edit(embed=main_embed, view=MyView(bot=self.bot))


# ─── Select-Menu View ─────────────────────────────────────────────────────────

class MyView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.select(
        custom_id="support",
        placeholder="Choose a Ticket option",
        options=[
            discord.SelectOption(label="Support",      description="You will get help here!", emoji="❓", value="support1"),
            discord.SelectOption(label="Dono Ticket",  description="Donation support here!", emoji="💸", value="support2"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        user_id = interaction.user.id
        value   = select.values[0]

        if value == "support1":
            # Ticket-Limit für Kategorie 1 prüfen
            ticket_count = count_user_tickets(user_id, CATEGORY_ID1)
            if ticket_count >= MAX_TICKETS_CAT1:
                embed = discord.Embed(
                    title="Ticket-Limit erreicht",
                    description=f"Du hast bereits **{ticket_count}/{MAX_TICKETS_CAT1}** Support-Tickets offen.",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                await asyncio.sleep(1)
                main_embed = discord.Embed(title=EMBED_TITLE, description=EMBED_DESCRIPTION, color=discord.Color.blue())
                await interaction.message.edit(embed=main_embed, view=MyView(bot=self.bot))
                return

            if interaction.channel.id != TICKET_CHANNEL:
                return

            # Modal öffnen – interaction wird hier consumed
            await interaction.response.send_modal(SupportModal(bot=self.bot, interaction_orig=interaction))

        elif value == "support2":
            # Ticket-Limit für Kategorie 2 prüfen
            ticket_count = count_user_tickets(user_id, CATEGORY_ID2)
            if ticket_count >= MAX_TICKETS_CAT2:
                embed = discord.Embed(
                    title="Ticket-Limit erreicht",
                    description=f"Du hast bereits **{ticket_count}/{MAX_TICKETS_CAT2}** Dono-Tickets offen.",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                await asyncio.sleep(1)
                main_embed = discord.Embed(title=EMBED_TITLE, description=EMBED_DESCRIPTION, color=discord.Color.blue())
                await interaction.message.edit(embed=main_embed, view=MyView(bot=self.bot))
                return

            if interaction.channel.id != TICKET_CHANNEL:
                return

            await interaction.response.defer(ephemeral=True)

            timezone      = pytz.timezone(TIMEZONE)
            creation_date = datetime.now(timezone).strftime('%Y-%m-%d %H:%M:%S')
            user_name     = interaction.user.name

            cur.execute(
                "INSERT INTO ticket (discord_name, discord_id, ticket_created, category) VALUES (?, ?, ?, ?)",
                (user_name, user_id, creation_date, CATEGORY_ID2)
            )
            conn.commit()
            await asyncio.sleep(1)
            cur.execute("SELECT id FROM ticket WHERE discord_id=? AND category=? ORDER BY id DESC LIMIT 1", (user_id, CATEGORY_ID2))
            ticket_number = cur.fetchone()[0]

            guild    = self.bot.get_guild(GUILD_ID)
            category = self.bot.get_channel(CATEGORY_ID2)

            ticket_channel = await guild.create_text_channel(
                f"dono-{ticket_number}", category=category, topic=str(user_id)
            )
            await ticket_channel.set_permissions(
                guild.get_role(TEAM_ROLE2),
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

            # Willkommens-Embed
            welcome_embed = discord.Embed(
                description=f'Welcome {interaction.user.mention},\nDein Dono-Ticket wurde erstellt!',
                color=discord.Color.blue()
            )
            await ticket_channel.send(embed=welcome_embed, view=CloseButton(bot=self.bot))

            # ?indica Command mit aktuellem Rabatt-Wert ausführen
            rabatt = get_rabatt()
            await ticket_channel.send(f"?indica{rabatt}")

            # Channel-ID speichern
            cur.execute("UPDATE ticket SET ticket_channel=? WHERE id=?", (ticket_channel.id, ticket_number))
            conn.commit()

            confirm_embed = discord.Embed(
                description=f'📬 Dono-Ticket was Created! Look here --> {ticket_channel.mention}',
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=confirm_embed, ephemeral=True)
            await asyncio.sleep(1)
            main_embed = discord.Embed(title=EMBED_TITLE, description=EMBED_DESCRIPTION, color=discord.Color.blue())
            await interaction.message.edit(embed=main_embed, view=MyView(bot=self.bot))


# ─── Close-Button ─────────────────────────────────────────────────────────────

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


# ─── Ticket-Options ───────────────────────────────────────────────────────────

class TicketOptions(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Delete Ticket 🎫", style=discord.ButtonStyle.red, custom_id="delete")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild     = self.bot.get_guild(GUILD_ID)
        log_ch    = self.bot.get_channel(LOG_CHANNEL)
        ticket_id = interaction.channel.id

        cur.execute("SELECT id, discord_id, ticket_created FROM ticket WHERE ticket_channel=?", (ticket_id,))
        ticket_data = cur.fetchone()
        if ticket_data is None:
            await interaction.response.send_message("Ticket not found in database.", ephemeral=True)
            return

        t_id, ticket_creator_id, ticket_created = ticket_data
        ticket_creator      = guild.get_member(ticket_creator_id)
        ticket_created_unix = convert_to_unix_timestamp(ticket_created)
        timezone            = pytz.timezone(TIMEZONE)
        ticket_closed       = datetime.now(timezone).strftime('%Y-%m-%d %H:%M:%S')
        ticket_closed_unix  = convert_to_unix_timestamp(ticket_closed)

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
        transcript_info.add_field(name="ID",             value=t_id,                            inline=True)
        transcript_info.add_field(name="Opened by",      value=ticket_creator.mention,          inline=True)
        transcript_info.add_field(name="Closed by",      value=interaction.user.mention,        inline=True)
        transcript_info.add_field(name="Ticket Created", value=f"<t:{ticket_created_unix}:f>", inline=True)
        transcript_info.add_field(name="Ticket Closed",  value=f"<t:{ticket_closed_unix}:f>",  inline=True)

        embed = discord.Embed(description='Ticket is deleting in 5 seconds.', color=0xff0000)
        await interaction.response.send_message(embed=embed)

        try:
            await ticket_creator.send(embed=transcript_info, file=make_file())
        except discord.Forbidden:
            transcript_info.add_field(name="Error", value="Ticket Creator DMs are disabled", inline=True)

        await log_ch.send(embed=transcript_info, file=make_file())
        await asyncio.sleep(3)
        await interaction.channel.delete(reason="Ticket Deleted")
        cur.execute("DELETE FROM ticket WHERE discord_id=? AND ticket_channel=?", (ticket_creator_id, ticket_id))
        conn.commit()


# ─── Cog ──────────────────────────────────────────────────────────────────────

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