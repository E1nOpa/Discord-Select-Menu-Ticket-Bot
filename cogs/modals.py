import discord
from discord.ext import commands
import traceback
import asyncio
from cogs.ticket_utils import (
    send_ephemeral_error,
    create_ticket_channel,
)

from cogs.ui_components import (
    CloseButton,
    reset_ticket_menu,
)
from cogs.api import get_fivem_data

# ─── Modals ───────────────────────────────────────────────────────────────────
# Neues Modal hinzufügen:
#   1. Klasse hier definieren (erbt von BaseTicketModal)
#   2. Im MODAL_REGISTRY unten eintragen: "MeinName": MeinModal
#   3. In config.json bei der Kategorie: "modal": "MeinName"

class BaseTicketModal(discord.ui.Modal):
    """Basisklasse für alle Ticket-Modals."""
    def __init__(self, bot: commands.Bot, interaction_orig: discord.Interaction, category: dict):
        super().__init__()
        self.bot              = bot
        self.interaction_orig = interaction_orig
        self.category         = category

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"{self.__class__.__name__} error:", flush=True)
        traceback.print_exception(type(error), error, error.__traceback__)
        await send_ephemeral_error(interaction, "Beim Erstellen des Tickets ist ein Fehler aufgetreten.")

    async def _open_ticket(self, interaction: discord.Interaction):
        """Erstellt den Ticket-Channel. Gibt (channel, number) zurück."""
        return await create_ticket_channel(
            bot=self.bot,
            interaction=interaction,
            category_id=self.category["id"],
            team_role_id=self.category["role"],
            channel_prefix=self.category["prefix"],
        )

    async def _finish(self, interaction: discord.Interaction, ticket_channel):
        """Sendet Bestätigung und setzt das Menü zurück."""
        confirm_embed = discord.Embed(
            description=f'📬 Dein Ticket wurde erstellt! --> {ticket_channel.mention}',
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)
        await asyncio.sleep(1)
        await reset_ticket_menu(self.interaction_orig, self.bot)

    async def _send_welcome(self, ticket_channel, interaction):
        data = await get_fivem_data(interaction.user.id)
        desc = f'Willkommen {interaction.user.mention},\nEin Teammitglied wird sich hier melden.\n\n'

        if data:
            status_icon = "🟢" if data.get("online") else "🔴"
            status_text = "Online" if data.get("online") else "Offline (Datenbank)"

            desc += f"{status_icon} **Spieler Status:** {status_text}\n"
            desc += f"👤 **Name:** {data.get('name', 'Unbekannt')}\n"

            if data.get("online"):
                desc += f"🆔 **Server ID:** {data['serverId']}\n"

            steam_id = data.get('steam')
            if steam_id and steam_id != "Keine Steam-ID gefunden":
                desc += f"🔗 **Steam:** `{steam_id}`"
            else:
                desc += f"🔗 **Steam:** *Nicht verknüpft*"
        else:
            desc += "⚠️ **Fehler:** Spieler-Daten konnten nicht geladen werden."

        embed = discord.Embed(
            description=desc,
            color=discord.Color.blue()
        )
        await ticket_channel.send(embed=embed)

class SupportModal(BaseTicketModal, title="Support Ticket"):
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

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket_channel, _ = await self._open_ticket(interaction)
        if ticket_channel is None:
            return

        await self._send_welcome(ticket_channel, interaction)

        form_embed = discord.Embed(title="📋 Ticket Details", color=discord.Color.blue())
        form_embed.add_field(name="❓ Anliegen", value=self.anliegen.value, inline=False)
        if self.clip.value:
            form_embed.add_field(name="🎬 Clip", value=self.clip.value, inline=False)
        form_embed.set_footer(text=f"Erstellt von {interaction.user.name}")
        await ticket_channel.send(embed=form_embed, view=CloseButton(bot=self.bot))

        await self._finish(interaction, ticket_channel)

class fmModal(BaseTicketModal, title="Fraktions Anliegen"):
    anliegen = discord.ui.TextInput(
        label="Beschreibe dein Anliegen",
        style=discord.TextStyle.long,
        placeholder="Beschreibe dein Anliegen so detailiert wie möglich...",
        required=True,
        max_length=1024
    )
    clip = discord.ui.TextInput(
        label="Hast du einen Clip?",
        style=discord.TextStyle.short,
        placeholder="Link zum Clip (Optional)",
        required=False,
        max_length=512
    )
    fraktion = discord.ui.TextInput(
        label="Um welche Fraktion geht es?",
        style=discord.TextStyle.short,
        placeholder="Name der Fraktion",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket_channel, _ = await self._open_ticket(interaction)
        if ticket_channel is None:
            return

        await self._send_welcome(ticket_channel, interaction)

        embed = discord.Embed(title="📋 Ticket Details", color=discord.Color.blue())
        embed.add_field(name="❓ Anliegen", value=self.anliegen.value, inline=False)
        embed.add_field(name="👥 Fraktion", value=self.fraktion.value, inline=False)
        if self.clip.value:
            embed.add_field(name="🎬 Clip", value=self.clip.value, inline=False)

        embed.set_footer(text=f"Erstellt von {interaction.user.name}")
        await ticket_channel.send(embed=embed, view=CloseButton(bot=self.bot))

        await self._finish(interaction, ticket_channel)


class cmModal(BaseTicketModal, title="Community Anliegen"):
    anliegen = discord.ui.TextInput(
        label="Beschreibe dein Anliegen",
        style=discord.TextStyle.long,
        placeholder="Hast du Feedback oder möchtest du ein Event planen?",
        required=True,
        max_length=1024
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket_channel, _ = await self._open_ticket(interaction)
        if ticket_channel is None:
            return
        await self._send_welcome(ticket_channel, interaction)

        embed = discord.Embed(title="📋 Ticket Details", color=discord.Color.blue())
        embed.add_field(name="🚀 Anliegen", value=self.anliegen.value, inline=False)

        embed.set_footer(text=f"Erstellt von {interaction.user.name}")
        await ticket_channel.send(embed=embed, view=CloseButton(bot=self.bot))

        await self._finish(interaction, ticket_channel)


class BewerbungModal(BaseTicketModal, title="Teambewerbung"):
    position = discord.ui.TextInput(
        label="Auf welche Position willst du dich bewerben?",
        style=discord.TextStyle.short,
        required=True,
        max_length=100
    )
    link = discord.ui.TextInput(
        label="Link zur Bewerbung",
        style=discord.TextStyle.short,
        placeholder="Google Doc o.ä (optional)",
        required=False,
        max_length=512
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket_channel, _ = await self._open_ticket(interaction)
        if ticket_channel is None:
            return
        await self._send_welcome(ticket_channel, interaction)

        embed = discord.Embed(title="📋 Bewerbung", color=discord.Color.blue())
        embed.add_field(name="💼 Position", value=self.position.value, inline=False)
        if self.link.value:
            embed.add_field(name="🔗 Bewerbung", value=self.link.value, inline=False)

        embed.set_footer(text=f"Erstellt von {interaction.user.name}")
        await ticket_channel.send(embed=embed, view=CloseButton(bot=self.bot))

        await self._finish(interaction, ticket_channel)


class BeschwerdeModal(BaseTicketModal, title="Beschwerde / Feedback"):
    typ = discord.ui.TextInput(
        label="Beschwerde oder Feedback?",
        style=discord.TextStyle.short,
        required=True,
        max_length=100
    )
    mitglied = discord.ui.TextInput(
        label="Um welches Teammitglied geht es?",
        style=discord.TextStyle.short,
        placeholder="z.B. AL | Marcel",
        required=True,
        max_length=100
    )
    beschreibung = discord.ui.TextInput(
        label="Weitere Beschreibung",
        style=discord.TextStyle.long,
        placeholder="Bitte beschreibe ausführlich, alle Infos bleiben vertraulich",
        required=True,
        max_length=1024
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket_channel, _ = await self._open_ticket(interaction)
        if ticket_channel is None:
            return
        await self._send_welcome(ticket_channel, interaction)

        embed = discord.Embed(title="📋 Beschwerde / Feedback", color=discord.Color.red())
        embed.add_field(name="📌 Typ", value=self.typ.value, inline=False)
        embed.add_field(name="👤 Teammitglied", value=self.mitglied.value, inline=False)
        embed.add_field(name="📝 Beschreibung", value=self.beschreibung.value, inline=False)

        embed.set_footer(text=f"Erstellt von {interaction.user.name}")
        await ticket_channel.send(embed=embed, view=CloseButton(bot=self.bot))

        await self._finish(interaction, ticket_channel)


class CheatingModal(BaseTicketModal, title="Cheating Verdacht"):
    user = discord.ui.TextInput(
        label="Um welchen User handelt es sich?",
        style=discord.TextStyle.short,
        required=True,
        max_length=100
    )
    clip = discord.ui.TextInput(
        label="Hast du einen Clip?",
        style=discord.TextStyle.short,
        placeholder="Link zum Clip (Optional)",
        required=False,
        max_length=512
    )
    grund = discord.ui.TextInput(
        label="Warum ist die Situation verdächtig?",
        style=discord.TextStyle.long,
        placeholder="Bitte beschreibe so ausführlich wie möglich...",
        required=True,
        max_length=1024
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket_channel, _ = await self._open_ticket(interaction)
        if ticket_channel is None:
            return
        await self._send_welcome(ticket_channel, interaction)

        embed = discord.Embed(title="📋 Cheating Verdacht", color=discord.Color.red())
        embed.add_field(name="👤 User", value=self.user.value, inline=False)
        embed.add_field(name="📝 Begründung", value=self.grund.value, inline=False)
        if self.clip.value:
            embed.add_field(name="🎬 Clip", value=self.clip.value, inline=False)

        embed.set_footer(text=f"Erstellt von {interaction.user.name}")
        await ticket_channel.send(embed=embed, view=CloseButton(bot=self.bot))

        await self._finish(interaction, ticket_channel)


class CraneModal(BaseTicketModal, title="Crane Immobilien"):
    immo_id = discord.ui.TextInput(
        label="Immo-ID",
        style=discord.TextStyle.short,
        placeholder="/getid an der Immo",
        required=True,
        max_length=50
    )
    anfrage = discord.ui.TextInput(
        label="Beschreibe deine Anfrage",
        style=discord.TextStyle.long,
        required=True,
        max_length=1024
    )
    interieur = discord.ui.TextInput(
        label="Gewünschtes Interieur?",
        style=discord.TextStyle.short,
        placeholder="Siehe Katalog (optional)",
        required=False,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket_channel, _ = await self._open_ticket(interaction)
        if ticket_channel is None:
            return
        await self._send_welcome(ticket_channel, interaction)

        embed = discord.Embed(title="📋 Immobilien Anfrage", color=discord.Color.blue())
        embed.add_field(name="🏠 Immo-ID", value=self.immo_id.value, inline=False)
        embed.add_field(name="📝 Anfrage", value=self.anfrage.value, inline=False)
        if self.interieur.value:
            embed.add_field(name="🛋️ Interieur", value=self.interieur.value, inline=False)

        embed.set_footer(text=f"Erstellt von {interaction.user.name}")
        await ticket_channel.send(embed=embed, view=CloseButton(bot=self.bot))

        await self._finish(interaction, ticket_channel)

class BugModal(BaseTicketModal, title="Bug Report"):
    system = discord.ui.TextInput(
        label="Betroffenes System",
        style=discord.TextStyle.short,
        placeholder="z. B. Inventar, Fahrzeuge, HUD, etc.",
        required=True,
        max_length=100
    )

    bug = discord.ui.TextInput(
        label="Beschreibung des Bugs",
        style=discord.TextStyle.long,
        placeholder="Beschreibe den Bug so genau wie möglich",
        required=True,
        max_length=1024
    )

    reproduce = discord.ui.TextInput(
        label="Reproduktionsschritte",
        style=discord.TextStyle.long,
        placeholder="1. ...\n2. ...\n3. ...",
        required=False,
        max_length=1024
    )

    expected = discord.ui.TextInput(
        label="Erwartetes Verhalten",
        style=discord.TextStyle.long,
        placeholder="Was hätte eigentlich passieren sollen?",
        required=True,
        max_length=1024
    )

    extra = discord.ui.TextInput(
        label="Zusätzliche Infos (optional)",
        style=discord.TextStyle.short,
        placeholder="Screenshots, Zeitpunkt, Clip etc.",
        required=False,
        max_length=300
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        ticket_channel, _ = await self._open_ticket(interaction)
        if ticket_channel is None:
            return

        await self._send_welcome(ticket_channel, interaction)

        embed = discord.Embed(
            title="🐞 Bug Report",
            color=discord.Color.red()
        )

        embed.add_field(name="🖥️ System", value=self.system.value, inline=False)
        embed.add_field(name="🐛 Bug", value=self.bug.value, inline=False)
        embed.add_field(name="🔁 Reproduktion", value=self.reproduce.value, inline=False)
        embed.add_field(name="✅ Erwartet", value=self.expected.value, inline=False)

        if self.extra.value:
            embed.add_field(name="➕ Extras", value=self.extra.value, inline=False)

        embed.set_footer(text=f"Gemeldet von {interaction.user.name}")

        await ticket_channel.send(
            embed=embed,
            view=CloseButton(bot=self.bot)
        )

        await self._finish(interaction, ticket_channel)


# ─── Modal-Registry ───────────────────────────────────────────────────────────
# Hier alle verfügbaren Modals eintragen.
# Config-Beispiel: "modal": "SupportModal"

MODAL_REGISTRY: dict[str, type[BaseTicketModal]] = {
    "SupportModal": SupportModal,
    "fmModal": fmModal,
    "cmModal": cmModal,
    "BewerbungModal": BewerbungModal,
    "BeschwerdeModal": BeschwerdeModal,
    "CheatingModal": CheatingModal,
    "CraneModal": CraneModal,
    "BugModal": BugModal,
}