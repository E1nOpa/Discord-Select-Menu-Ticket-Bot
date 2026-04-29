import discord
import json
import sqlite3
from discord import app_commands
from discord.ext import commands
from cogs.ticket_system import MyView, close_ticket_channel, get_rabatt, set_rabatt

with open("config.json", mode="r", encoding="utf-8") as config_file:
    config = json.load(config_file)

TICKET_CHANNEL = config["ticket_channel_id"]
RABATT_ROLE_IDS = config["rabatt_role_ids"]
EMBED_TITLE = config["embed_title"]
EMBED_DESCRIPTION = config["embed_description"]

conn = sqlite3.connect("Database.db")
cur = conn.cursor()


class Ticket_Command(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print("Bot Loaded  | ticket_commands.py ✅")

    @app_commands.command(name="ticket", description="Sendet das Ticket-Panel in den Ticket-Channel")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def ticket(self, interaction: discord.Interaction):
        channel = self.bot.get_channel(TICKET_CHANNEL)
        if channel is None:
            await interaction.response.send_message("Der Ticket-Channel wurde nicht gefunden.", ephemeral=True)
            return

        embed = discord.Embed(title=EMBED_TITLE, description=EMBED_DESCRIPTION, color=discord.Color.blue())
        await channel.send(embed=embed, view=MyView(self.bot))
        await interaction.response.send_message("Ticket-Panel wurde gesendet.", ephemeral=True)

    @app_commands.command(name="add", description="Fügt einen Nutzer zum Ticket hinzu")
    @app_commands.guild_only()
    async def add(self, interaction: discord.Interaction, member: discord.Member):
        if "ticket-" in interaction.channel.name or "dono-" in interaction.channel.name:
            await interaction.channel.set_permissions(
                member,
                send_messages=True,
                read_messages=True,
                add_reactions=False,
                embed_links=True,
                attach_files=True,
                read_message_history=True,
                external_emojis=True,
            )
            embed = discord.Embed(
                description=f"{member.mention} zu <#{interaction.channel.id}> hinzugefügt!\nNutze /remove um einen User zu entfernen.",
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(
                description="Du kannst diesen Befehl nur in einem Ticket verwenden!",
                color=discord.Color.red(),
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="remove", description="Entfernt einen Nutzer aus dem Ticket")
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, member: discord.Member):
        if "ticket-" in interaction.channel.name or "dono-" in interaction.channel.name:
            await interaction.channel.set_permissions(
                member,
                send_messages=False,
                read_messages=False,
                add_reactions=False,
                embed_links=False,
                attach_files=False,
                read_message_history=False,
                external_emojis=False,
            )
            embed = discord.Embed(
                description=f"{member.mention} vom <#{interaction.channel.id}> entfernt!",
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(
                description="Du kannst diesen Befehl nur in einem Ticket nutzen!",
                color=discord.Color.red(),
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="delete", description="Löscht das Ticket")
    @app_commands.guild_only()
    async def delete_ticket(self, interaction: discord.Interaction):
        await close_ticket_channel(self.bot, interaction)

    @app_commands.command(name="rabatt", description="Setzt den Rabatt-Wert für ?indica")
    @app_commands.guild_only()
    async def rabatt(self, interaction: discord.Interaction, prozent: int):
        user_role_ids = [role.id for role in interaction.user.roles]
        if not any(role_id in user_role_ids for role_id in RABATT_ROLE_IDS):
            embed = discord.Embed(
                description="Du hast keine Berechtigung, den Rabatt-Wert zu ändern!",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        set_rabatt(str(prozent))
        embed = discord.Embed(
            description=f"✅ Rabatt wurde auf **{prozent}%** gesetzt.\nNächste Dono-Tickets verwenden `?indica{prozent}`.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Du hast keine Berechtigung für diesen Command.", ephemeral=True)
        elif isinstance(error, app_commands.NoPrivateMessage):
            await interaction.response.send_message("Commands sind in DMs nicht erlaubt!", ephemeral=True)
        else:
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(Ticket_Command(bot))
