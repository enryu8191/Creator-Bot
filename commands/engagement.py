import discord
from discord import app_commands
from discord.ext import commands
import re
from typing import Optional


class EngagementCommands(commands.Cog):
    """Cog that provides engagement-related slash commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="status", description="Check your engagement status")
    async def status(self, interaction: discord.Interaction):
        """Display user's current engagement status with numeric progress and pending list."""
        user_id = interaction.user.id

        # Get user's active session
        session = await self.bot.db.get_active_session(user_id)
        if not session:
            embed = discord.Embed(
                title="📊 Engagement Status",
                description="You haven't submitted a link yet for this session.",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Build numeric status: engaged_count / total_others
        latest_map = await self.bot.db.get_latest_sessions_map()
        # Everyone who currently has an active/latest session
        all_user_ids = set(latest_map.keys())
        # Others (exclude self)
        other_user_ids = sorted(uid for uid in all_user_ids if uid != user_id)
        total_required = len(other_user_ids)

        engagers = await self.bot.db.get_engagers_for_session(session["session_id"])
        engaged_set = set(engagers)
        engaged_count = len(engaged_set.intersection(all_user_ids - {user_id}))

        # Compute who hasn't engaged with your tweet (among other active users)
        pending_ids = [uid for uid in other_user_ids if uid not in engaged_set]

        # Prepare embed
        embed = discord.Embed(
            title="📊 Engagement Status",
            color=discord.Color.green() if engaged_count >= total_required and total_required > 0 else discord.Color.yellow(),
        )
        embed.add_field(name="Your Link", value=session["link"], inline=False)
        embed.add_field(name="Status", value=f"{engaged_count}/{total_required}", inline=True)

        # Resolve mentions for pending users
        if total_required > 0:
            if pending_ids:
                mentions = []
                for uid in pending_ids:
                    user = self.bot.get_user(uid)
                    mentions.append(user.mention if user else f"<@{uid}>")
                pending_value = "\n".join(mentions)
            else:
                pending_value = "Everyone has engaged with your post. 🎉"
            embed.add_field(name="Creators have yet to react", value=pending_value, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="Display engagement leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        """Show top engagers"""
        leaders = await self.bot.db.get_leaderboard(limit=10)
        if not leaders:
            embed = discord.Embed(
                title="🏆 Engagement Leaderboard",
                description="No engagement data yet. Start engaging to appear here!",
                color=discord.Color.blue(),
            )
            await interaction.response.send_message(embed=embed)
            return

        # Build leaderboard embed
        embed = discord.Embed(
            title="🏆 Engagement Leaderboard",
            description="Top creators by engagement points",
            color=discord.Color.gold(),
        )
        medals = ["🥇", "🥈", "🥉"]
        leaderboard_text = ""
        for idx, (user_id, username, points) in enumerate(leaders, 1):
            medal = medals[idx - 1] if idx <= 3 else f"`#{idx}`"
            leaderboard_text += f"{medal} **{username}** - {points} point{'s' if points != 1 else ''}\n"

        embed.description = leaderboard_text
        embed.set_footer(text="Keep engaging to climb the ranks!")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="change_link", description="Update your submitted link")
    @app_commands.describe(new_link="The new URL to replace your previous submission")
    async def change_link(self, interaction: discord.Interaction, new_link: str):
        """Allow users to change their link with notification"""
        user_id = interaction.user.id

        # Simple URL validation
        url_pattern = re.compile(r"^https?://\S+$")
        if not url_pattern.match(new_link):
            await interaction.response.send_message(
                "❌ Invalid URL format. Please provide a valid link starting with http:// or https://",
                ephemeral=True,
            )
            return

        # Get current session
        session = await self.bot.db.get_active_session(user_id)
        if not session:
            await interaction.response.send_message(
                "❌ You don't have an active session. Post a link in the Yap channel first.",
                ephemeral=True,
            )
            return

        # Update the message in the original channel of the session
        channel = self.bot.get_channel(session.get("channel_id")) if session.get("channel_id") else None
        if channel is None:
            await interaction.response.send_message(
                "❌ Could not locate the original channel for your submission. Please repost your link.",
                ephemeral=True,
            )
            return

        try:
            message = await channel.fetch_message(session["message_id"])

            # Create updated embed
            embed = discord.Embed(
                title=f"🔗 {interaction.user.display_name}'s Content",
                description=f"[Click here to engage]({new_link})",
                color=discord.Color.blue(),
            )
            embed.add_field(name="Status", value="⚠️ **LINK UPDATED**", inline=False)
            embed.set_footer(text="React with ✅ after engaging!")
            await message.edit(embed=embed)

            # Log the change
            log_channel = self.bot.get_channel(self.bot.log_channel_id)
            if log_channel:
                log_embed = discord.Embed(
                    title="🔄 Link Updated",
                    description=f"{interaction.user.mention} changed their link",
                    color=discord.Color.orange(),
                )
                log_embed.add_field(name="Old Link", value=session["link"], inline=False)
                log_embed.add_field(name="New Link", value=new_link, inline=False)
                await log_channel.send(embed=log_embed)

            # Update database
            await self.bot.db.conn.execute(
                """
                UPDATE sessions
                SET link = ?
                WHERE session_id = ?
                """,
                (new_link, session["session_id"]),
            )
            await self.bot.db.conn.commit()

            await interaction.response.send_message(
                "✅ Link updated successfully! Others have been notified.", ephemeral=True
            )

        except discord.NotFound:
            await interaction.response.send_message(
                "❌ Could not find your original message. Please repost your link.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(EngagementCommands(bot))