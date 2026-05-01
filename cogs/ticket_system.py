import discord
import asyncio
import json
import sqlite3
import pytz
import traceback
import chat_exporter
import io

from datetime import datetime
from collections import Counter
from discord.ext import commands

from cogs.ticket_utils import (
    GUILD_ID,
    LOG_CHANNEL,
    CATEGORIES,
    get_category,
    get_ticket_by_channel,
    count_user_tickets,
    add_ticket_access,
    get_ticket_access,
    remove_ticket_access,
    build_main_embed,
    send_ephemeral_error,
    create_ticket_channel,
    require_ticket_team,
    remember_current_ticket_users,
    set_ticket_users_visibility,
    send_support_transcript_log,
)

from cogs.ui_components import (
    MyView,
    ClosedTicketOptions,
    CloseButton,
)


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class Ticket_System(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ─── Bot Ready ────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        print("Bot Loaded | ticket_system.py ✅")

        # Persistent Views registrieren
        self.bot.add_view(MyView(bot=self.bot))
        self.bot.add_view(CloseButton(bot=self.bot))
        self.bot.add_view(ClosedTicketOptions(bot=self.bot))

    # ─── User verlässt Server ────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        cur = sqlite3.connect("Database.db").cursor()

        cur.execute(
            "SELECT id, ticket_channel, category FROM ticket WHERE discord_id=? AND closed=0",
            (member.id,)
        )
        tickets = cur.fetchall()

        if not tickets:
            return

        guild = member.guild
        log_ch = self.bot.get_channel(LOG_CHANNEL)

        for ticket_id, channel_id, category_id in tickets:
            cat = get_category(category_id)

            # Auto-close prüfen
            if cat and not cat.get("auto_close_on_leave", True):
                continue

            channel = guild.get_channel(int(channel_id))
            if channel is None:
                continue

            try:
                # User speichern & Sichtbarkeit entfernen
                await remember_current_ticket_users(channel, ticket_id, member.id)
                await set_ticket_users_visibility(
                    guild, channel, ticket_id, visible=False
                )

                # Transcript nur wenn aktiviert
                if cat and cat.get("transcript", False) and log_ch is not None:
                    try:
                        await send_support_transcript_log(
                            bot=self.bot,
                            channel=channel,
                            log_channel=log_ch,
                            ticket_id=ticket_id,
                            ticket_creator=member,
                            closed_by=self.bot.user,
                        )
                    except Exception as error:
                        print("Transcript error (auto-close):", flush=True)
                        traceback.print_exception(type(error), error, error.__traceback__)

                # DB Update
                cur.execute("UPDATE ticket SET closed=1 WHERE id=?", (ticket_id,))
                cur.connection.commit()

                embed = discord.Embed(
                    description=(
                        f"🔒 Ticket wurde automatisch geschlossen, "
                        f"da **{member}** den Server verlassen hat."
                    ),
                    color=discord.Color.orange()
                )

                await channel.send(embed=embed, view=ClosedTicketOptions(bot=self.bot))

            except Exception as e:
                print("Auto-close error:", e)


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(Ticket_System(bot))