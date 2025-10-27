import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Tuple, Optional


class ConfirmResetView(discord.ui.View):
	"""Confirmation view used to reset all session data."""

	def __init__(self, bot: commands.Bot):
		super().__init__(timeout=30)
		self.bot = bot

	@discord.ui.button(label="Confirm Reset", style=discord.ButtonStyle.danger)
	async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		# Only allow administrators to confirm
		if not interaction.user.guild_permissions.administrator:
			await interaction.response.send_message("You don't have permission to do that.", ephemeral=True)
			return

		await interaction.response.defer(ephemeral=True)

		# Reset all sessions in DB
		await self.bot.db.reset_all_sessions()

		# Optionally clear allowed channels (best-effort, but do NOT unlock)
		channels_cleared = 0
		allowed = getattr(self.bot, 'allowed_channel_ids', None)
		if allowed:
			for cid in list(allowed):
				ch = self.bot.get_channel(cid)
				if ch is None:
					continue
				try:
					await ch.purge(limit=100)
					channels_cleared += 1
				except Exception as e:
					print(f"Error resetting channel {cid}: {str(e)}")

		# Log the reset
		log_channel = self.bot.get_channel(self.bot.log_channel_id)
		if log_channel:
			embed = discord.Embed(
				title="🔄 Session Reset",
				description=f"All engagement data cleared by {interaction.user.mention}",
				color=discord.Color.blue(),
			)
			await log_channel.send(embed=embed)

		await interaction.edit_original_response(content="✅ Session reset complete! Ready for a new engagement round.", embed=None, view=None)

	@discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
	async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		await interaction.response.edit_message(content="❌ Reset cancelled.", embed=None, view=None)


class AdminCommands(commands.Cog):
	"""Cog providing administrative commands for engagement management."""

	def __init__(self, bot: commands.Bot):
		self.bot = bot

	@app_commands.command(name="check_engagement", description="Check who hasn't engaged")
	@app_commands.default_permissions(administrator=True)
	@app_commands.checks.has_permissions(administrator=True)
	async def check_engagement(self, interaction: discord.Interaction):
		"""Manually check for users who haven't completed engagement"""
		await interaction.response.defer(ephemeral=True)

		# Get non-engaged users
		non_engaged: List[Tuple[int, str]] = await self.bot.db.get_non_engaged_users()
		if not non_engaged:
			embed = discord.Embed(
				title="✅ All Clear!",
				description="All creators have completed their engagement!",
				color=discord.Color.green(),
			)
			await interaction.followup.send(embed=embed, ephemeral=True)
			return

		# Build report
		report_channel = self.bot.get_channel(self.bot.report_channel_id)
		if report_channel is None:
			await interaction.followup.send("❌ Report channel not found. Check configuration.", ephemeral=True)
			return

		embed = discord.Embed(
			title="⚠️ Engagement Report",
			description="The following creators still need to engage with others' content:",
			color=discord.Color.red(),
		)

		user_mentions: List[str] = []
		for user_id, username in non_engaged:
			user = self.bot.get_user(user_id)
			if user:
				user_mentions.append(user.mention)
			else:
				user_mentions.append(f"Unknown User ({user_id})")

		if user_mentions:
			embed.add_field(
				name="Action Required", 
				value="\n".join(user_mentions), 
				inline=False
			)
			embed.add_field(
				name="Instructions", 
				value="To complete engagement:\n"
					  "1. View another creator's content\n"
					  "2. React with ✅ on their post\n"
					  "Note: You must engage with content posted AFTER your own submission.", 
				inline=False
			)

		await report_channel.send(embed=embed)
		await interaction.followup.send(f"✅ Report sent to {report_channel.mention}", ephemeral=True)

	@app_commands.command(name="reset_session", description="Reset all engagement data (Admin only)")
	@app_commands.default_permissions(administrator=True)
	@app_commands.checks.has_permissions(administrator=True)
	async def reset_session(self, interaction: discord.Interaction):
		"""Clear all session data for a fresh start"""
		view = ConfirmResetView(self.bot)
		embed = discord.Embed(
			title="⚠️ Confirm Session Reset",
			description="This will delete ALL current engagement data. Are you sure?",
			color=discord.Color.red(),
		)
		await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

	@app_commands.command(name="set_yap_channel", description="Set or add the current channel as an allowed post channel")
	@app_commands.default_permissions(administrator=True)
	@app_commands.describe(add="If true, add this channel to the allowed list, otherwise replace the list with only this channel")
	@app_commands.checks.has_permissions(administrator=True)
	async def set_yap_channel(self, interaction: discord.Interaction, add: bool = False):
		"""Configure allowed channels for posting/reacting"""
		await interaction.response.defer(ephemeral=True)
		channel_id = interaction.channel_id
		current = getattr(self.bot, 'allowed_channel_ids', None)
		if add:
			new_set = set(current) if current else set()
			new_set.add(channel_id)
		else:
			new_set = {channel_id}
		# Persist and apply
		await self.bot.db.set_allowed_channel_ids(new_set)
		self.bot.allowed_channel_ids = new_set
		name = interaction.channel.mention if isinstance(interaction.channel, discord.abc.GuildChannel) else str(channel_id)
		verb = "added to" if add else "set as"
		await interaction.followup.send(f"✅ {name} {verb} allowed channels.", ephemeral=True)

	@app_commands.command(name="set_log", description="Set the log channel (default: current channel)")
	@app_commands.default_permissions(administrator=True)
	@app_commands.checks.has_permissions(administrator=True)
	async def set_log(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
		await interaction.response.defer(ephemeral=True)
		ch = channel or interaction.channel
		await self.bot.db.set_config('log_channel_id', str(ch.id))
		self.bot.log_channel_id = ch.id
		await interaction.followup.send(f"✅ Log channel set to {ch.mention}", ephemeral=True)

	@app_commands.command(name="set_report", description="Set the report channel (default: current channel)")
	@app_commands.default_permissions(administrator=True)
	@app_commands.checks.has_permissions(administrator=True)
	async def set_report(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
		await interaction.response.defer(ephemeral=True)
		ch = channel or interaction.channel
		await self.bot.db.set_config('report_channel_id', str(ch.id))
		self.bot.report_channel_id = ch.id
		await interaction.followup.send(f"✅ Report channel set to {ch.mention}", ephemeral=True)


async def setup(bot: commands.Bot):
	await bot.add_cog(AdminCommands(bot))