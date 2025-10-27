# Discord Creator Engagement Bot

A Discord bot that manages creator engagement sessions with link submissions and reaction tracking.

## Features

- Multi-channel support for link submissions
- Engagement tracking with checkmark reactions
- Admin commands for session management
- Status tracking with engagement counts
- Database persistence with SQLite

## Setup

1. Create a Discord application and bot at https://discord.com/developers/applications
2. Set up environment variables (see Environment Variables section)
3. Install dependencies: `pip install -r requirements.txt`
4. Run the bot: `python bot.py`

## Environment Variables

Required:
- `DISCORD_TOKEN` - Your Discord bot token
- `GUILD_ID` - Your Discord server ID
- `LOG_CHANNEL_ID` - Channel ID for bot logs
- `REPORT_CHANNEL_ID` - Channel ID for engagement reports

Optional:
- `ALLOWED_CHANNEL_IDS` - Comma-separated list of allowed posting channels
- `YAP_CHANNEL_ID` - Legacy single channel support

## Commands

### User Commands
- `/status` - Check your engagement status
- `/leaderboard` - View engagement leaderboard
- `/change_link` - Update your submitted link

### Admin Commands (Administrator permission required)
- `/check_engagement` - See who hasn't engaged yet
- `/reset_session` - Clear all engagement data
- `/set_yap_channel` - Configure allowed posting channels
- `/set_log` - Set log channel
- `/set_report` - Set report channel

## Deployment

This bot is designed to run on platforms like Render, Heroku, or Railway.

For Render:
1. Connect your GitHub repository
2. Set service type to "Web Service"
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `python bot.py`
5. Add environment variables in Render dashboard