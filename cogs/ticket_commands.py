import discord
import asyncio
import json
import sqlite3
import io
import pytz
import chat_exporter
from datetime import datetime
from discord import app_commands
from discord.ext import commands
from cogs.ticket_system import MyView, convert_to_unix_timestamp, get_rabatt, set_rabatt

with open("config.json", mode="r") as config_file:
    config = json.load(config_file)

TICKET_CHANNEL    = config["ticket_channel_id"]
GUILD_ID          = config["guild_id"]
LOG_CHANNEL       = config["log_channel_id"]
TIMEZONE          = config["timezone"]
EMBED_TITLE       = config["embed_title"]
EMBED_DESCRIPTION = config["embed_description"]
RABATT_ROLE_IDS   = config["rabatt_role_ids"]

conn = sqlite3.connect('Database.db')
cur  = conn.cursor()


class Ticket_Command(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print('Bot Loaded  | ticket_commands.py ✅')

    # ── /ticket ───────────────────────────────────────────────────────────────
    @app_commands.command(name="ticket", description="Send the Ticket Menu to the Ticket Channel")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def ticket(self, interaction: discord.Interaction):
        channel = self.bot.get_channel(TICKET_CHANNEL)
        embed   = discord.Embed(title=EMBED_TITLE, description=EMBED_DESCRIPTION, color=discord.Color.blue())
        await channel.send(embed=embed, view=MyView(self.bot))
        await interaction.response.send_message("Ticket Menu was sent!", ephemeral=True)

    # ── /add ──────────────────────────────────────────────────────────────────
    @app_commands.command(name="add", description="Add a Member to the Ticket")
    @app_commands.guild_only()
    async def add(self, interaction: discord.Interaction, member: discord.Member):
        if "ticket-" in interaction.channel.name or "dono-" in interaction.channel.name:
            await interaction.channel.set_permissions(
                member,
                send_messages=True, read_messages=True, add_reactions=False,
                embed_links=True, attach_files=True, read_message_history=True, external_emojis=True
            )
            embed = discord.Embed(
                description=f'Added {member.mention} to <#{interaction.channel.id}>!\nUse /remove to remove a User.',
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                description='You can only use this command in a Ticket!',
                color=discord.Color.red()
            )
        await interaction.response.send_message(embed=embed)

    # ── /remove ───────────────────────────────────────────────────────────────
    @app_commands.command(name="remove", description="Remove a Member from the Ticket")
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, member: discord.Member):
        if "ticket-" in interaction.channel.name or "dono-" in interaction.channel.name:
            await interaction.channel.set_permissions(
                member,
                send_messages=False, read_messages=False, add_reactions=False,
                embed_links=False, attach_files=False, read_message_history=False, external_emojis=False
            )
            embed = discord.Embed(
                description=f'Removed {member.mention} from <#{interaction.channel.id}>!\nUse /add to add a User.',
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                description='You can only use this command in a Ticket!',
                color=discord.Color.red()
            )
        await interaction.response.send_message(embed=embed)

    # ── /delete ───────────────────────────────────────────────────────────────
    @app_commands.command(name="delete", description="Delete the Ticket")
    @app_commands.guild_only()
    async def delete_ticket(self, interaction: discord.Interaction):
        guild     = self.bot.get_guild(GUILD_ID)
        log_ch    = self.bot.get_channel(LOG_CHANNEL)
        ticket_id = interaction.channel.id

        cur.execute("SELECT id, discord_id, ticket_created FROM ticket WHERE ticket_channel=?", (ticket_id,))
        ticket_data = cur.fetchone()
        if ticket_data is None:
            await interaction.response.send_message("This channel is not a Ticket!", ephemeral=True)
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

    # ── /rabatt ───────────────────────────────────────────────────────────────
    @app_commands.command(name="rabatt", description="Setzt den Rabatt-Wert für ?indica")
    @app_commands.guild_only()
    async def rabatt(self, interaction: discord.Interaction, prozent: int):
        # Rollen-Check
        user_role_ids = [role.id for role in interaction.user.roles]
        if not any(r in user_role_ids for r in RABATT_ROLE_IDS):
            embed = discord.Embed(
                description="Du hast keine Berechtigung, den Rabatt-Wert zu ändern!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        set_rabatt(str(prozent))
        embed = discord.Embed(
            description=f'✅ Rabatt wurde auf **{prozent}%** gesetzt.\nNächste Dono-Tickets verwenden `?indica{prozent}`.',
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    # ── Error Handler ──────────────────────────────────────────────────────────
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Du hast keine Berechtigung für diesen Command.", ephemeral=True)
        elif isinstance(error, app_commands.NoPrivateMessage):
            await interaction.response.send_message("Commands sind in DMs nicht erlaubt!", ephemeral=True)
        else:
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(Ticket_Command(bot))