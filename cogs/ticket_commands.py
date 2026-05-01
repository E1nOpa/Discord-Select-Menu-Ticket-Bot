import discord
import json
from discord import app_commands
from discord.ext import commands

from cogs.ticket_utils import (
    TICKET_CHANNEL,
    build_main_embed,
    get_ticket_by_channel,
    require_ticket_team,
    add_ticket_access,
    remove_ticket_access,
    close_only_ticket_channel,
    reopen_ticket_channel,
    delete_ticket_channel,
)

from cogs.ui_components import MyView


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

with open("config.json", mode="r", encoding="utf-8") as f:
    config = json.load(f)

EMBED_TITLE       = config["embed_title"]
EMBED_DESCRIPTION = config["embed_description"]


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class Ticket_Command(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print("Bot Loaded | ticket_commands.py ✅")

    # ─── Ticket Panel senden ────────────────────────────────────────────────
    @app_commands.command(
        name="ticket",
        description="Sendet das Ticket-Panel in den Ticket-Channel"
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def ticket(self, interaction: discord.Interaction):

        channel = self.bot.get_channel(TICKET_CHANNEL)
        if channel is None:
            await interaction.response.send_message(
                "Der Ticket-Channel wurde nicht gefunden.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=EMBED_TITLE,
            description=EMBED_DESCRIPTION,
            color=discord.Color.blue()
        )

        await channel.send(embed=embed, view=MyView(self.bot))

        await interaction.response.send_message(
            "Ticket-Panel wurde gesendet.",
            ephemeral=True
        )

    # ─── Add User ────────────────────────────────────────────────────────────
    @app_commands.command(name="add", description="Fügt einen Nutzer zum Ticket hinzu")
    @app_commands.guild_only()
    async def add(self, interaction: discord.Interaction, member: discord.Member):

        ticket_data = get_ticket_by_channel(interaction.channel.id)
        if ticket_data is None:
            await interaction.response.send_message(
                "Nur in Tickets nutzbar!",
                ephemeral=True
            )
            return

        ticket_id, _, category_id, _ = ticket_data

        if not await require_ticket_team(interaction, category_id):
            return

        await interaction.channel.set_permissions(
            member,
            send_messages=True,
            read_messages=True,
            view_channel=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
            external_emojis=True,
        )

        add_ticket_access(ticket_id, member.id)

        embed = discord.Embed(
            description=f"{member.mention} wurde hinzugefügt.",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed)

    # ─── Remove User ─────────────────────────────────────────────────────────
    @app_commands.command(name="remove", description="Entfernt einen Nutzer aus dem Ticket")
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, member: discord.Member):

        ticket_data = get_ticket_by_channel(interaction.channel.id)
        if ticket_data is None:
            await interaction.response.send_message(
                "Nur in Tickets nutzbar!",
                ephemeral=True
            )
            return

        ticket_id, _, category_id, _ = ticket_data

        if not await require_ticket_team(interaction, category_id):
            return

        await interaction.channel.set_permissions(member, overwrite=None)
        remove_ticket_access(ticket_id, member.id)

        embed = discord.Embed(
            description=f"{member.mention} wurde entfernt.",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed)

    # ─── Ticket Aktionen ─────────────────────────────────────────────────────
    @app_commands.command(name="close", description="Schließt das Ticket")
    @app_commands.guild_only()
    async def close(self, interaction: discord.Interaction):
        await close_only_ticket_channel(self.bot, interaction)

    @app_commands.command(name="reopen", description="Öffnet ein Ticket wieder")
    @app_commands.guild_only()
    async def reopen(self, interaction: discord.Interaction):
        await reopen_ticket_channel(self.bot, interaction)

    @app_commands.command(name="delete", description="Löscht das Ticket")
    @app_commands.guild_only()
    async def delete(self, interaction: discord.Interaction):
        await delete_ticket_channel(self.bot, interaction)

    # ─── Error Handler ───────────────────────────────────────────────────────
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):

        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "Keine Berechtigung.",
                ephemeral=True
            )

        elif isinstance(error, app_commands.NoPrivateMessage):
            await interaction.response.send_message(
                "Nicht in DMs nutzbar.",
                ephemeral=True
            )

        else:
            raise error


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(Ticket_Command(bot))