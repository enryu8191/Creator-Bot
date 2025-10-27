import discord
from discord.ext import commands
import re
from typing import Optional


class MessageHandler(commands.Cog):
    """Handles messages and reactions in the Yap channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.checkmark_emoji = "✅"

    async def _get_all_user_ids(self, guild: discord.Guild):
        """Helper to get all user IDs from a guild."""
        async for member in guild.fetch_members():
            yield member.id

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            # Ignore bot messages
            if message.author.bot:
                return

            # Only process messages in allowed channels (if configured)
            allowed = getattr(self.bot, 'allowed_channel_ids', None)
            if allowed is not None and message.channel.id not in allowed:
                return

            # Simple URL detection
            url_pattern = re.compile(r"https?://\S+")
            urls = url_pattern.findall(message.content)
            if not urls:
                # No URL found, delete message and warn
                try:
                    await message.delete()
                except Exception:
                    pass
                await message.channel.send(
                    f"{message.author.mention} Please post only links in this channel!",
                    delete_after=5,
                )
                return

            link = urls[0]  # Take first URL

            # Check if user already has an active session
            existing_session = await self.bot.db.get_active_session(message.author.id)
            if existing_session:
                # User already posted, delete new message and notify
                try:
                    await message.delete()
                except Exception:
                    pass
                await message.channel.send(
                    f"{message.author.mention} You can only post 1 link per session! Use `/change_link` to update.",
                    delete_after=5,
                )
                return

            # Add user to database if new
            await self.bot.db.add_user(message.author.id, message.author.display_name)

            # Delete original message and post formatted version
            try:
                await message.delete()
            except Exception:
                pass

            # Create embed for the link
            embed = discord.Embed(
                title=f"🔗 {message.author.display_name}'s Content",
                description=f"[Click here to engage]({link})",
                color=discord.Color.blue(),
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            embed.add_field(
                name="Instructions",
                value="React with ✅ after engaging with this content to show support!",
                inline=False,
            )
            embed.set_footer(text=f"Posted by {message.author.display_name}")

            # Send formatted message
            formatted_msg = await message.channel.send(embed=embed)

            # Add checkmark reaction
            try:
                await formatted_msg.add_reaction(self.checkmark_emoji)
            except Exception:
                pass

            # Save to database (store channel id for multi-channel support)
            await self.bot.db.add_session(message.author.id, link, formatted_msg.id, message.channel.id)

            # Log submission
            log_channel = self.bot.get_channel(self.bot.log_channel_id)
            if log_channel:
                log_embed = discord.Embed(
                    title="📝 New Link Submitted",
                    description=f"{message.author.mention} posted their content",
                    color=discord.Color.green(),
                )
                log_embed.add_field(name="Link", value=link, inline=False)
                await log_channel.send(embed=log_embed)
        except Exception as e:
            print(f"[on_message ERROR] {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Track when users engage with others' content by reacting with checkmark."""
        # Ignore bot reactions
        if payload.user_id == self.bot.user.id:
            return

        # Only process reactions in allowed channels (if configured)
        allowed = getattr(self.bot, 'allowed_channel_ids', None)
        if allowed is not None and payload.channel_id not in allowed:
            return

        # Only process checkmark reactions
        if str(payload.emoji) != self.checkmark_emoji:
            return

        # Get the channel and message
        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except Exception:
            return

        try:
            # Find whose content this is
            content_owner_session = None
            if message.embeds:
                # Get the original message ID
                message_id = message.id
                
                # Try to find the session by message ID more efficiently
                guild_members = [member.id async for member in channel.guild.fetch_members()]
                for user_id in guild_members:
                    session = await self.bot.db.get_active_session(user_id)
                    if session and session.get("message_id") == message_id:
                        content_owner_session = session
                        break
                        
            if not content_owner_session:
                print(f"Debug - Could not find content owner for message {message.id}")
                return

            # Don't let users react to their own content
            if payload.user_id == content_owner_session["user_id"]:
                try:
                    user = channel.guild.get_member(payload.user_id) if channel.guild else None
                    if user is None:
                        user = await self.bot.fetch_user(payload.user_id)
                    await message.remove_reaction(payload.emoji, user)
                    await channel.send(
                        f"{user.mention} You cannot engage with your own content! Please engage with others' content instead.",
                        delete_after=5
                    )
                except Exception as e:
                    print(f"Debug - Error handling self-reaction: {str(e)}")
                return
                
        except Exception as e:
            print(f"Debug - Error in content owner check: {str(e)}")
            return

        try:
            # Record the engagement and award points to the engaging user
            if not content_owner_session.get("session_id"):
                print(f"Debug - content_owner_session data: {content_owner_session}")
                return

            # Check if user has already engaged
            if await self.bot.db.has_engaged(payload.user_id, content_owner_session["session_id"]):
                try:
                    # Remove the duplicate reaction
                    user = channel.guild.get_member(payload.user_id) if channel.guild else None
                    if user is None:
                        user = await self.bot.fetch_user(payload.user_id)
                    await message.remove_reaction(payload.emoji, user)
                    await channel.send(
                        f"{user.mention} You have already engaged with this content!",
                        delete_after=5
                    )
                except Exception as e:
                    print(f"Debug - Error removing duplicate reaction: {str(e)}")
                return
                
            # Add new engagement
            if await self.bot.db.add_engagement(payload.user_id, content_owner_session["session_id"]):
                await self.bot.db.add_point(payload.user_id)
                
                # Get mention for the engaging user
                try:
                    member = channel.guild.get_member(payload.user_id) if channel.guild else None
                    engager_mention = member.mention if member else (await self.bot.fetch_user(payload.user_id)).mention
                except Exception as e:
                    print(f"Debug - Error getting user mention: {str(e)}")
                    engager_mention = f"<@{payload.user_id}>"
        except Exception as e:
            print(f"Debug - Error in engagement recording: {str(e)}")
            return

        # Update embed to show the engagement
        if message.embeds:
            embed = message.embeds[0]
            try:
                # Find existing engagements field or create new one
                engagement_index = -1
                for i, field in enumerate(embed.fields):
                    if field.name == "Engaged By":
                        engagement_index = i
                        break

                if engagement_index >= 0:
                    # Update existing field
                    current_value = embed.fields[engagement_index].value
                    new_value = f"{current_value}\n{engager_mention}"
                    embed.set_field_at(engagement_index, name="Engaged By", value=new_value, inline=False)
                else:
                    # Add new field
                    embed.add_field(name="Engaged By", value=engager_mention, inline=False)

                await message.edit(embed=embed)
            except Exception:
                pass

        # Log the engagement
        log_channel = self.bot.get_channel(self.bot.log_channel_id)
        if log_channel:
            try:
                owner = channel.guild.get_member(content_owner_session["user_id"]) if channel.guild else None
                owner_mention = owner.mention if owner else f"<@{content_owner_session['user_id']}>"
            except Exception:
                owner_mention = f"<@{content_owner_session['user_id']}>"

            log_embed = discord.Embed(
                title="✅ New Engagement",
                description=f"{engager_mention} engaged with {owner_mention}'s content",
                color=discord.Color.green(),
            )
            log_embed.add_field(name="Points Earned", value="1 point", inline=True)
            await log_channel.send(embed=log_embed)


async def setup(bot: commands.Bot):
	await bot.add_cog(MessageHandler(bot))
