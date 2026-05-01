"""
ticket_utils.py
────────────────
Datenbankverbindung, Config-Konstanten und alle reinen Helper-Funktionen.
Keine Discord-UI-Klassen hier – nur Logik.
"""

import asyncio
import io
import json
import sqlite3
import traceback
from collections import Counter
from datetime import datetime

import chat_exporter
import discord
import pytz
from discord.ext import commands

# ─── Config ───────────────────────────────────────────────────────────────────

with open("config.json", mode="r", encoding="utf-8") as _f:
    _config = json.load(_f)

GUILD_ID:          int       = _config["guild_id"]
TICKET_CHANNEL:    int       = _config["ticket_channel_id"]
LOG_CHANNEL:       int       = _config["log_channel_id"]
TIMEZONE:          str       = _config["timezone"]
EMBED_TITLE:       str       = _config["embed_title"]
EMBED_DESCRIPTION: str       = _config["embed_description"]
CATEGORIES:        list[dict] = _config["categories"]

# ─── Kategorie-Helpers ────────────────────────────────────────────────────────

def get_category(category_id: int) -> dict | None:
    """Gibt das Kategorie-Dict für eine gegebene category_id zurück."""
    return next((c for c in CATEGORIES if c["id"] == category_id), None)

def team_role_id_for_category(category_id: int) -> int | None:
    cat = get_category(category_id)
    return cat["role"] if cat else None

# ─── Datenbank ────────────────────────────────────────────────────────────────

conn = sqlite3.connect("Database.db")
cur  = conn.cursor()

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
_ticket_columns = {row[1] for row in cur.fetchall()}
if "category"       not in _ticket_columns:
    cur.execute("ALTER TABLE ticket ADD COLUMN category INTEGER")
if "ticket_channel" not in _ticket_columns:
    cur.execute("ALTER TABLE ticket ADD COLUMN ticket_channel TEXT")
if "closed"         not in _ticket_columns:
    cur.execute("ALTER TABLE ticket ADD COLUMN closed INTEGER DEFAULT 0")

cur.execute("""
    CREATE TABLE IF NOT EXISTS ticket_access (
        ticket_id  INTEGER,
        discord_id INTEGER,
        PRIMARY KEY (ticket_id, discord_id)
    )
""")
conn.commit()

# ─── DB-Funktionen ────────────────────────────────────────────────────────────
def count_user_tickets(user_id: int, category_id: int) -> int:
    cur.execute(
        "SELECT COUNT(*) FROM ticket WHERE discord_id=? AND category=? AND closed=0",
        (user_id, category_id),
    )
    return cur.fetchone()[0]

def add_ticket_access(ticket_id: int, user_id: int) -> None:
    cur.execute(
        "INSERT OR IGNORE INTO ticket_access (ticket_id, discord_id) VALUES (?, ?)",
        (ticket_id, user_id),
    )
    conn.commit()

def remove_ticket_access(ticket_id: int, user_id: int) -> None:
    cur.execute(
        "DELETE FROM ticket_access WHERE ticket_id=? AND discord_id=?",
        (ticket_id, user_id),
    )
    conn.commit()

def get_ticket_access(ticket_id: int) -> list[int]:
    cur.execute("SELECT discord_id FROM ticket_access WHERE ticket_id=?", (ticket_id,))
    return [row[0] for row in cur.fetchall()]

def get_ticket_by_channel(channel_id: int):
    cur.execute(
        "SELECT id, discord_id, category, closed FROM ticket WHERE ticket_channel=?",
        (channel_id,),
    )
    return cur.fetchone()

def create_ticket_record(user: discord.abc.User, creation_date: str, category_id: int) -> int:
    cur.execute(
        "INSERT INTO ticket (discord_name, discord_id, ticket_created, category) VALUES (?, ?, ?, ?)",
        (user.name, user.id, creation_date, category_id),
    )
    conn.commit()
    return cur.lastrowid

# ─── Discord-Helpers ──────────────────────────────────────────────────────────

def build_main_embed() -> discord.Embed:
    return discord.Embed(title=EMBED_TITLE, description=EMBED_DESCRIPTION, color=discord.Color.blue())

async def send_ephemeral_error(interaction: discord.Interaction, message: str) -> None:
    embed = discord.Embed(description=message, color=discord.Color.red())
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def require_ticket_team(interaction: discord.Interaction, category_id: int) -> bool:
    role_id = team_role_id_for_category(category_id)
    if role_id is None:
        await send_ephemeral_error(interaction, "Kategorie nicht gefunden.")
        return False
    member_roles = getattr(interaction.user, "roles", [])
    if any(role.id == role_id for role in member_roles):
        return True
    await send_ephemeral_error(interaction, "Du hast keine Berechtigung für dieses Ticket.")
    return False

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
            f"Die Team-Rolle `{team_role_id}` wurde nicht gefunden. Bitte `config.json` prüfen.",
        )
        return None, None, None

    return guild, category, team_role

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

    timezone      = pytz.timezone(TIMEZONE)
    creation_date = datetime.now(timezone).strftime("%Y-%m-%d %H:%M:%S")
    ticket_number = create_ticket_record(interaction.user, creation_date, category_id)

    try:
        ticket_channel = await guild.create_text_channel(
            f"{channel_prefix}-{ticket_number}",
            category=category,
            topic=str(interaction.user.id),
        )
        _perms = dict(
            send_messages=True, read_messages=True, view_channel=True,
            add_reactions=False, embed_links=True, attach_files=True,
            read_message_history=True, external_emojis=True,
        )
        await ticket_channel.set_permissions(team_role, **_perms)
        await ticket_channel.set_permissions(interaction.user, **_perms)
        await ticket_channel.set_permissions(
            guild.default_role,
            send_messages=False, read_messages=False, view_channel=False,
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
    add_ticket_access(ticket_number, interaction.user.id)
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
    counts: Counter = Counter()
    users: dict     = {}
    async for message in channel.history(limit=limit, oldest_first=False):
        author = message.author
        counts[author.id] += 1
        users[author.id]   = author

    lines = [
        f"{count} - {user_label(users[uid])}"
        for uid, count in counts.most_common()
    ]
    if not lines:
        return "Keine Nachrichten gefunden."

    value = "\n".join(lines)
    if len(value) <= 1024:
        return value

    shortened, total = [], 0
    for line in lines:
        if total + len(line) + 1 > 1000:
            break
        shortened.append(line)
        total += len(line) + 1
    shortened.append("Weitere Nutzer gekürzt.")
    return "\n".join(shortened)

async def send_support_transcript_log(
    *,
    bot: commands.Bot,
    channel: discord.TextChannel,
    log_channel: discord.TextChannel,
    ticket_id: int,
    ticket_creator,
    closed_by: discord.abc.User,
) -> None:
    transcript = await chat_exporter.export(
        channel, limit=200, tz_info=TIMEZONE, military_time=True, bot=bot
    )
    if transcript is None:
        raise RuntimeError("chat_exporter returned no transcript")

    filename = f"transcript-{channel.name}.html"
    file     = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=filename)
    transcript_users = await collect_transcript_users(channel, limit=200)

    embed = discord.Embed(
        title=f"Transcript | {channel.name}",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow(),
    )
    if ticket_creator is not None:
        embed.set_author(name=str(ticket_creator), icon_url=ticket_creator.display_avatar.url)
        embed.set_thumbnail(url=ticket_creator.display_avatar.url)

    embed.add_field(name="Ticket Owner",         value=user_label(ticket_creator), inline=False)
    embed.add_field(name="Ticket Name",          value=channel.name,               inline=False)
    embed.add_field(name="Geschlossen von",      value=user_label(closed_by),      inline=False)
    embed.add_field(name="Transcript",           value="Wird hochgeladen...",       inline=False)
    embed.add_field(name="Nutzer im Transcript", value=transcript_users,           inline=False)
    embed.set_footer(text=f"Ticket ID: {ticket_id}")

    message = await log_channel.send(embed=embed, file=file)
    if message.attachments:
        transcript_url = message.attachments[0].url
        embed.set_field_at(3, name="Transcript", value=f"[Anschauen]({transcript_url})", inline=False)
        await message.edit(embed=embed)

async def remember_current_ticket_users(
    channel: discord.TextChannel,
    ticket_id: int,
    owner_id: int,
) -> None:
    add_ticket_access(ticket_id, owner_id)
    for target, overwrite in channel.overwrites.items():
        if isinstance(target, discord.Member) and (
            overwrite.view_channel is True or overwrite.read_messages is True
        ):
            add_ticket_access(ticket_id, target.id)

async def set_ticket_users_visibility(
    guild: discord.Guild,
    channel: discord.TextChannel,
    ticket_id: int,
    visible: bool,
    exclude_role_ids: list[int] | None = None,
) -> None:
    """Setzt die Sichtbarkeit für alle Ticket-User, außer Team-Rollen."""
    all_team_role_ids = {c["role"] for c in CATEGORIES}
    if exclude_role_ids:
        all_team_role_ids.update(exclude_role_ids)

    for user_id in get_ticket_access(ticket_id):
        member = guild.get_member(user_id)
        if member is None:
            continue
        if any(role.id in all_team_role_ids for role in member.roles):
            continue
        await channel.set_permissions(
            member,
            view_channel=visible,
            read_messages=visible,
            send_messages=visible,
            add_reactions=False,
            embed_links=visible,
            attach_files=visible,
            read_message_history=visible,
            external_emojis=visible,
        )

# ─── Ticket-Aktionen ──────────────────────────────────────────────────────────
# Diese Funktionen werden von Cog-Commands UND UI-Buttons genutzt.
# Sie importieren ui_components lazy (innerhalb der Funktion), um
# den zirkulären Import ui_components → ticket_utils → ui_components zu vermeiden.

async def close_only_ticket_channel(bot: commands.Bot, interaction: discord.Interaction) -> None:
    from cogs.ui_components import ClosedTicketOptions  # lazy import

    guild  = bot.get_guild(GUILD_ID) or interaction.guild
    log_ch = bot.get_channel(LOG_CHANNEL)
    ticket_data = get_ticket_by_channel(interaction.channel.id)
    if ticket_data is None:
        await send_ephemeral_error(interaction, "Dieser Channel ist kein Ticket.")
        return

    ticket_id, owner_id, category_id, closed = ticket_data
    is_owner = interaction.user.id == owner_id
    if not is_owner and not await require_ticket_team(interaction, category_id):
        return

    if closed:
        await send_ephemeral_error(interaction, "Dieses Ticket ist bereits geschlossen.")
        return

    await interaction.response.defer()
    await remember_current_ticket_users(interaction.channel, ticket_id, owner_id)
    if guild is not None:
        await set_ticket_users_visibility(guild, interaction.channel, ticket_id, visible=False)

    cat = get_category(category_id)
    transcript_saved_text = "Kein Transcript für diese Ticket-Kategorie."
    if cat and cat.get("transcript", False) and log_ch is not None:
        ticket_creator = await get_ticket_creator(bot, guild, owner_id) if guild else None
        try:
            await send_support_transcript_log(
                bot=bot,
                channel=interaction.channel,
                log_channel=log_ch,
                ticket_id=ticket_id,
                ticket_creator=ticket_creator,
                closed_by=interaction.user,
            )
            transcript_saved_text = f"Transcript gespeichert in: {log_ch.mention}"
        except Exception as error:
            print("Transcript log error:", flush=True)
            traceback.print_exception(type(error), error, error.__traceback__)
            transcript_saved_text = "Transcript konnte nicht gespeichert werden."

    cur.execute("UPDATE ticket SET closed=1 WHERE id=?", (ticket_id,))
    conn.commit()

    embed = discord.Embed(
        description=(
            f"Ticket wurde von {interaction.user.mention} geschlossen.\n\n{transcript_saved_text}"
        ),
        color=discord.Color.orange(),
    )
    await interaction.followup.send(embed=embed, view=ClosedTicketOptions(bot=bot))


async def reopen_ticket_channel(bot: commands.Bot, interaction: discord.Interaction) -> None:
    guild = bot.get_guild(GUILD_ID) or interaction.guild
    ticket_data = get_ticket_by_channel(interaction.channel.id)
    if ticket_data is None:
        await send_ephemeral_error(interaction, "Dieser Channel ist kein Ticket.")
        return

    ticket_id, owner_id, category_id, closed = ticket_data
    if not await require_ticket_team(interaction, category_id):
        return
    if not closed:
        await send_ephemeral_error(interaction, "Dieses Ticket ist bereits offen.")
        return

    await interaction.response.defer()
    if guild is not None:
        await set_ticket_users_visibility(guild, interaction.channel, ticket_id, visible=True)

    cur.execute("UPDATE ticket SET closed=0 WHERE id=?", (ticket_id,))
    conn.commit()

    embed = discord.Embed(
        description=f"Ticket wurde von {interaction.user.mention} wieder geöffnet.",
        color=discord.Color.green(),
    )
    await interaction.followup.send(embed=embed)


async def delete_ticket_channel(bot: commands.Bot, interaction: discord.Interaction) -> None:
    ticket_data = get_ticket_by_channel(interaction.channel.id)
    if ticket_data is None:
        await send_ephemeral_error(interaction, "Dieser Channel ist kein Ticket.")
        return

    ticket_id, owner_id, category_id, closed = ticket_data
    if not await require_ticket_team(interaction, category_id):
        return
    if not closed:
        await send_ephemeral_error(interaction, "Dieses Ticket ist nicht geschlossen.")
        return

    embed = discord.Embed(description="Ticket wird in 5 Sekunden gelöscht.", color=discord.Color.red())
    await interaction.response.send_message(embed=embed)
    await asyncio.sleep(5)
    await interaction.channel.delete(reason="Ticket gelöscht")
    cur.execute("DELETE FROM ticket_access WHERE ticket_id=?", (ticket_id,))
    cur.execute("DELETE FROM ticket WHERE id=?", (ticket_id,))
    conn.commit()