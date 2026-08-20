"""Discord helpers shared by web-link modules."""

from __future__ import annotations

import discord


class DeletableView(discord.ui.View):
    """View with a link button and a permission-aware delete button."""

    def __init__(self, url: str, source_author_id: int) -> None:
        super().__init__(timeout=None)
        self.source_author_id = source_author_id
        self.add_item(discord.ui.Button(label="Open", style=discord.ButtonStyle.link, url=url))

    def can_delete(self, user: discord.abc.User) -> bool:
        if user.id == self.source_author_id:
            return True
        return isinstance(user, discord.Member) and user.guild_permissions.manage_messages

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, custom_id="web-link:delete")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not self.can_delete(interaction.user):
            await interaction.response.send_message(
                "Only the original poster or a member with Manage Messages can delete this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        if interaction.message:
            await interaction.message.delete()
