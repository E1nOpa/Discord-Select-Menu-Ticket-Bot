"""
ui_components.py
────────────────
Alle persistenten Discord-UI-Klassen (Views / Buttons / Select-Menus).

Importiert Logik ausschließlich aus ticket_utils – nie umgekehrt.
"""

import asyncio
import traceback

import discord
from discord.ext import commands

from cogs.ticket_utils import (
    CATEGORIES,
    TICKET_CHANNEL,
    build_main_embed,
    close_only_ticket_channel,
    count_user_tickets,
    create_ticket_channel,
    delete_ticket_channel,
    reopen_ticket_channel,
    send_ephemeral_error,
)


# ─── Hilfs-Funktion ───────────────────────────────────────────────────────────

async def reset_ticket_menu(interaction: discord.Interaction, bot: commands.Bot) -> None:
    from cogs.ui_components import MyView
    """Setzt das Ticket-Select-Menü auf den Ausgangszustand zurück."""
    if interaction.message is None:
        return
    try:
        await interaction.message.edit(embed=build_main_embed(), view=MyView(bot=bot))
    except discord.HTTPException:
        pass


# ─── Views ────────────────────────────────────────────────────────────────────

class ConfirmCloseView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=30)
        self.bot = bot

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        print("ConfirmCloseView error:", flush=True)
        traceback.print_exception(type(error), error, error.__traceback__)
        await send_ephemeral_error(interaction, "Fehler bei der Bestätigung.")

    @discord.ui.button(label="Schließen", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await close_only_ticket_channel(self.bot, interaction)

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Vorgang abgebrochen.", embed=None, view=None)


class CloseButton(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        print("CloseButton interaction error:", flush=True)
        traceback.print_exception(type(error), error, error.__traceback__)
        await send_ephemeral_error(interaction, "Beim Schließen des Tickets ist ein Fehler aufgetreten.")

    @discord.ui.button(label="Ticket schließen", style=discord.ButtonStyle.blurple, custom_id="close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="Ticket schließen?",
            description="Bist du sicher, dass du dieses Ticket schließen möchtest?",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(
            embed=embed, view=ConfirmCloseView(bot=self.bot), ephemeral=True
        )


class ClosedTicketOptions(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        print("ClosedTicketOptions interaction error:", flush=True)
        traceback.print_exception(type(error), error, error.__traceback__)
        await send_ephemeral_error(
            interaction, "Beim Verarbeiten des geschlossenen Tickets ist ein Fehler aufgetreten."
        )

    @discord.ui.button(label="Öffnen", style=discord.ButtonStyle.green, custom_id="reopen")
    async def reopen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await reopen_ticket_channel(self.bot, interaction)

    @discord.ui.button(label="Löschen", style=discord.ButtonStyle.red, custom_id="delete")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await delete_ticket_channel(self.bot, interaction)


class MyView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        print("MyView interaction error:", flush=True)
        traceback.print_exception(type(error), error, error.__traceback__)
        await send_ephemeral_error(
            interaction, "Beim Verarbeiten der Ticket-Auswahl ist ein Fehler aufgetreten."
        )

    @discord.ui.select(
        custom_id="support",
        placeholder="Wähle aus was für ein Ticket du erstellen möchtest",
        options=[
            discord.SelectOption(
                label=cat["select_label"],
                description=cat.get("select_description", ""),
                emoji=cat.get("select_emoji"),
                # Index als value – garantiert eindeutig, auch wenn IDs doppelt vorkommen
                value=str(i),
            )
            for i, cat in enumerate(CATEGORIES)
        ],
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        print(
            f"Ticket select used by {interaction.user} in channel "
            f"{getattr(interaction.channel, 'id', None)} with values {select.values}",
            flush=True,
        )

        if interaction.channel is None or interaction.channel.id != TICKET_CHANNEL:
            await interaction.response.send_message(
                "Bitte nutze das Ticket-Menu im vorgesehenen Ticket-Channel.",
                ephemeral=True,
            )
            return

        selected_index = int(select.values[0])
        if selected_index >= len(CATEGORIES):
            await send_ephemeral_error(interaction, "Ungültige Auswahl.")
            return
        cat = CATEGORIES[selected_index]

        ticket_count = count_user_tickets(interaction.user.id, cat["id"])
        if ticket_count >= cat["limit"]:
            embed = discord.Embed(
                title="Ticket-Limit erreicht",
                description=f"Du hast bereits **{ticket_count}/{cat['limit']}** {cat['name']}-Tickets offen.",
                color=0xFF0000,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            await asyncio.sleep(1)
            await reset_ticket_menu(interaction, self.bot)
            return

        # Modal aus Registry laden ("modal": "SupportModal" in config.json)
        # Fehlendes / unbekanntes Modal → Ticket direkt erstellen
        from cogs.modals import MODAL_REGISTRY  # lazy import verhindert zirkulären Import

        modal_name = cat.get("modal")
        modal_cls  = MODAL_REGISTRY.get(modal_name) if modal_name else None

        if modal_cls is not None:
            await interaction.response.send_modal(
                modal_cls(bot=self.bot, interaction_orig=interaction, category=cat)
            )
        else:
            await interaction.response.defer(ephemeral=True)
            ticket_channel, _ = await create_ticket_channel(
                bot=self.bot,
                interaction=interaction,
                category_id=cat["id"],
                team_role_id=cat["role"],
                channel_prefix=cat["prefix"],
            )
            if ticket_channel is None:
                return

            welcome_embed = discord.Embed(
                description=f'Willkommen {interaction.user.mention},\nDein {cat["name"]}-Ticket wurde erstellt!',
                color=discord.Color.blue(),
            )
            await ticket_channel.send(embed=welcome_embed, view=CloseButton(bot=self.bot))

            confirm_embed = discord.Embed(
                description=f'📬 {cat["name"]}-Ticket wurde erstellt! --> {ticket_channel.mention}',
                color=discord.Color.green(),
            )
            await interaction.followup.send(embed=confirm_embed, ephemeral=True)
            await asyncio.sleep(1)
            await reset_ticket_menu(interaction, self.bot)