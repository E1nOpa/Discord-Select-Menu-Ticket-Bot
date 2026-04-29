import discord
import asyncio
import pytz
import json
import sqlite3
from datetime import datetime
from collections import Counter
import chat_exporter
import io
import traceback
from discord.ext import commands

with open("config.json", mode="r", encoding="utf-8") as config_file:
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
cur.execute("PRAGMA table_info(ticket)")
ticket_columns = {row[1] for row in cur.fetchall()}
if "category" not in ticket_columns:
    cur.execute("ALTER TABLE ticket ADD COLUMN category INTEGER")
if "ticket_channel" not in ticket_columns:
    cur.execute("ALTER TABLE ticket ADD COLUMN ticket_channel TEXT")

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


def build_main_embed() -> discord.Embed:
    return discord.Embed(title=EMBED_TITLE, description=EMBED_DESCRIPTION, color=discord.Color.blue())


async def send_ephemeral_error(interaction: discord.Interaction, message: str):
    embed = discord.Embed(description=message, color=discord.Color.red())
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def reset_ticket_menu(interaction: discord.Interaction, bot: commands.Bot):
    if interaction.message is None:
        return

    try:
        await interaction.message.edit(embed=build_main_embed(), view=MyView(bot=bot))
    except discord.HTTPException:
        pass


async def get_ticket_targets(
    bot: commands.Bot,
    interaction: discord.Interaction,
    category_id: int,
    team_role_id: int,
):
    guild = bot.get_guild(GUILD_ID) or interaction.guild
    if guild is None:
        await send_ephemeral_error(interaction, "Server konnte nicht gefunden werden.")
        return None, None, None

    category = guild.get_channel(category_id)
    if category is None:
        try:
            category = await bot.fetch_channel(category_id)
        except discord.HTTPException:
            category = None

    if not isinstance(category, discord.CategoryChannel):
        await send_ephemeral_error(
            interaction,
            f"Die Ticket-Kategorie `{category_id}` wurde nicht gefunden oder ist keine Kategorie.",
        )
        return None, None, None

    team_role = guild.get_role(team_role_id)
    if team_role is None:
        await send_ephemeral_error(
            interaction,
            f"Die Team-Rolle `{team_role_id}` wurde nicht gefunden. Bitte `config.json` pruefen.",
        )
        return None, None, None

    return guild, category, team_role


def create_ticket_record(user: discord.abc.User, creation_date: str, category_id: int) -> int:
    cur.execute(
        "INSERT INTO ticket (discord_name, discord_id, ticket_created, category) VALUES (?, ?, ?, ?)",
        (user.name, user.id, creation_date, category_id)
    )
    conn.commit()
    return cur.lastrowid


async def create_ticket_channel(
    *,
    bot: commands.Bot,
    interaction: discord.Interaction,
    category_id: int,
    team_role_id: int,
    channel_prefix: str,
):
    guild, category, team_role = await get_ticket_targets(bot, interaction, category_id, team_role_id)
    if guild is None:
        return None, None

    timezone = pytz.timezone(TIMEZONE)
    creation_date = datetime.now(timezone).strftime('%Y-%m-%d %H:%M:%S')
    ticket_number = create_ticket_record(interaction.user, creation_date, category_id)

    try:
        ticket_channel = await guild.create_text_channel(
            f"{channel_prefix}-{ticket_number}", category=category, topic=str(interaction.user.id)
        )
        await ticket_channel.set_permissions(
            team_role,
            send_messages=True, read_messages=True, view_channel=True, add_reactions=False,
            embed_links=True, attach_files=True, read_message_history=True, external_emojis=True
        )
        await ticket_channel.set_permissions(
            interaction.user,
            send_messages=True, read_messages=True, view_channel=True, add_reactions=False,
            embed_links=True, attach_files=True, read_message_history=True, external_emojis=True
        )
        await ticket_channel.set_permissions(
            guild.default_role,
            send_messages=False, read_messages=False, view_channel=False
        )
    except discord.Forbidden:
        cur.execute("DELETE FROM ticket WHERE id=?", (ticket_number,))
        conn.commit()
        await send_ephemeral_error(
            interaction,
            "Ich habe nicht genug Rechte, um den Ticket-Channel zu erstellen oder Rechte zu setzen.",
        )
        return None, None
    except discord.HTTPException as error:
        cur.execute("DELETE FROM ticket WHERE id=?", (ticket_number,))
        conn.commit()
        await send_ephemeral_error(interaction, f"Ticket konnte nicht erstellt werden: `{error}`")
        return None, None

    cur.execute("UPDATE ticket SET ticket_channel=? WHERE id=?", (ticket_channel.id, ticket_number))
    conn.commit()
    return ticket_channel, ticket_number


async def get_ticket_creator(bot: commands.Bot, guild: discord.Guild, user_id: int):
    member = guild.get_member(user_id)
    if member is not None:
        return member

    try:
        return await bot.fetch_user(user_id)
    except discord.HTTPException:
        return None


def user_label(user) -> str:
    if user is None:
        return "Unbekannt"

    mention = getattr(user, "mention", str(user))
    return f"{mention} - {user}"


async def collect_transcript_users(channel: discord.TextChannel, limit: int = 200) -> str:
    counts = Counter()
    users = {}

    async for message in channel.history(limit=limit, oldest_first=False):
        author = message.author
        counts[author.id] += 1
        users[author.id] = author

    lines = [
        f"{count} - {user_label(users[user_id])}"
        for user_id, count in counts.most_common()
    ]
    if not lines:
        return "Keine Nachrichten gefunden."

    value = "\n".join(lines)
    if len(value) <= 1024:
        return value

    shortened = []
    total = 0
    for line in lines:
        if total + len(line) + 1 > 1000:
            break
        shortened.append(line)
        total += len(line) + 1
    shortened.append("Weitere Nutzer gekuerzt.")
    return "\n".join(shortened)


async def send_support_transcript_log(
    *,
    bot: commands.Bot,
    channel: discord.TextChannel,
    log_channel: discord.TextChannel,
    ticket_id: int,
    ticket_creator,
    closed_by: discord.abc.User,
):
    transcript = await chat_exporter.export(
        channel, limit=200, tz_info=TIMEZONE, military_time=True, bot=bot
    )
    if transcript is None:
        raise RuntimeError("chat_exporter returned no transcript")

    filename = f"transcript-{channel.name}.html"
    file = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=filename)
    transcript_users = await collect_transcript_users(channel, limit=200)

    embed = discord.Embed(
        title=f"Transcript | {channel.name}",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow(),
    )
    if ticket_creator is not None:
        embed.set_author(name=str(ticket_creator), icon_url=ticket_creator.display_avatar.url)
        embed.set_thumbnail(url=ticket_creator.display_avatar.url)

    embed.add_field(name="Ticket Owner", value=user_label(ticket_creator), inline=False)
    embed.add_field(name="Ticket Name", value=channel.name, inline=False)
    embed.add_field(name="Geschlossen von", value=user_label(closed_by), inline=False)
    embed.add_field(name="Transcript", value="Wird hochgeladen...", inline=False)
    embed.add_field(name="Nutzer im Transcript", value=transcript_users, inline=False)
    embed.set_footer(text=f"Ticket ID: {ticket_id}")

    message = await log_channel.send(embed=embed, file=file)
    if message.attachments:
        transcript_url = message.attachments[0].url
        embed.set_field_at(3, name="Transcript", value=f"[Anschauen]({transcript_url})", inline=False)
        await message.edit(embed=embed)


async def close_ticket_channel(bot: commands.Bot, interaction: discord.Interaction):
    guild = bot.get_guild(GUILD_ID) or interaction.guild
    log_ch = bot.get_channel(LOG_CHANNEL)
    ticket_id = interaction.channel.id

    cur.execute("SELECT id, discord_id, category FROM ticket WHERE ticket_channel=?", (ticket_id,))
    ticket_data = cur.fetchone()
    if ticket_data is None:
        await interaction.response.send_message("Dieser Channel ist kein Ticket.", ephemeral=True)
        return

    t_id, ticket_creator_id, category_id = ticket_data
    ticket_creator = await get_ticket_creator(bot, guild, ticket_creator_id) if guild else None

    embed = discord.Embed(description="Ticket wird in 5 Sekunden geloescht.", color=0xff0000)
    await interaction.response.send_message(embed=embed)

    is_support_ticket = category_id == CATEGORY_ID1 or interaction.channel.name.startswith("ticket-")
    if is_support_ticket and log_ch is not None:
        try:
            await send_support_transcript_log(
                bot=bot,
                channel=interaction.channel,
                log_channel=log_ch,
                ticket_id=t_id,
                ticket_creator=ticket_creator,
                closed_by=interaction.user,
            )
        except Exception as error:
            print("Transcript log error:", flush=True)
            traceback.print_exception(type(error), error, error.__traceback__)
            await log_ch.send(f"Transcript fuer `{interaction.channel.name}` konnte nicht erstellt werden.")

    await asyncio.sleep(5)
    await interaction.channel.delete(reason="Ticket geloescht")
    cur.execute("DELETE FROM ticket WHERE discord_id=? AND ticket_channel=?", (ticket_creator_id, ticket_id))
    conn.commit()


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

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print("SupportModal error:", flush=True)
        traceback.print_exception(type(error), error, error.__traceback__)
        await send_ephemeral_error(interaction, "Beim Erstellen des Support-Tickets ist ein Fehler aufgetreten.")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        ticket_channel, ticket_number = await create_ticket_channel(
            bot=self.bot,
            interaction=interaction,
            category_id=CATEGORY_ID1,
            team_role_id=TEAM_ROLE1,
            channel_prefix="ticket",
        )
        if ticket_channel is None:
            return

        # Willkommens-Embed
        welcome_embed = discord.Embed(
            description=f'Willkommen {interaction.user.mention},\nin kürze wird sich ein Teammitglied um dein Anliegen kümmern.',
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
            description=f'📬 Dein Ticket wurde erstellt! --> {ticket_channel.mention}',
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)

        # Select-Menü zurücksetzen
        await asyncio.sleep(1)
        await reset_ticket_menu(self.interaction_orig, self.bot)


# ─── Select-Menu View ─────────────────────────────────────────────────────────

class MyView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        print("MyView interaction error:", flush=True)
        traceback.print_exception(type(error), error, error.__traceback__)
        await send_ephemeral_error(interaction, "Beim Verarbeiten der Ticket-Auswahl ist ein Fehler aufgetreten.")

    @discord.ui.select(
        custom_id="support",
        placeholder="Wähle aus was für ein Ticket du erstellen möchtest",
        options=[
            discord.SelectOption(label="Support Ticket",      description="Wir helfen gerne bei allen möglichen Anliegen!", emoji="❓", value="support1"),
            discord.SelectOption(label="Dono Ticket",  description="Unterstütze dieses Projekt!", emoji="💸", value="support2"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        print(
            f"Ticket select used by {interaction.user} in channel {getattr(interaction.channel, 'id', None)} with values {select.values}",
            flush=True,
        )
        user_id = interaction.user.id
        value   = select.values[0]

        if interaction.channel is None or interaction.channel.id != TICKET_CHANNEL:
            await interaction.response.send_message(
                "Bitte nutze das Ticket-Menue im vorgesehenen Ticket-Channel.",
                ephemeral=True
            )
            return

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
                await reset_ticket_menu(interaction, self.bot)
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
                await reset_ticket_menu(interaction, self.bot)
                return

            if interaction.channel.id != TICKET_CHANNEL:
                return

            await interaction.response.defer(ephemeral=True)

            ticket_channel, ticket_number = await create_ticket_channel(
                bot=self.bot,
                interaction=interaction,
                category_id=CATEGORY_ID2,
                team_role_id=TEAM_ROLE2,
                channel_prefix="dono",
            )
            if ticket_channel is None:
                return

            # Willkommens-Embed
            welcome_embed = discord.Embed(
                description=f'Willkommen {interaction.user.mention},\nDein Dono-Ticket wurde erstellt!',
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
                description=f'📬 Dono-Ticket wurde erstellt! --> {ticket_channel.mention}',
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=confirm_embed, ephemeral=True)
            await asyncio.sleep(1)
            await reset_ticket_menu(interaction, self.bot)


# ─── Close-Button ─────────────────────────────────────────────────────────────

class CloseButton(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        print("CloseButton interaction error:", flush=True)
        traceback.print_exception(type(error), error, error.__traceback__)
        await send_ephemeral_error(interaction, "Beim Schliessen des Tickets ist ein Fehler aufgetreten.")

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

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        print("TicketOptions interaction error:", flush=True)
        traceback.print_exception(type(error), error, error.__traceback__)
        await send_ephemeral_error(interaction, "Beim Loeschen des Tickets ist ein Fehler aufgetreten.")

    @discord.ui.button(label="Delete Ticket 🎫", style=discord.ButtonStyle.red, custom_id="delete")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await close_ticket_channel(self.bot, interaction)
        return


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
