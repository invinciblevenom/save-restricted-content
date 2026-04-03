<h1 align="center">Save Restricted Content Bot</h1>

<p align="center">
  <em>An advanced, highly optimized Telegram bot to download restricted content (photos, videos, audio, documents) from private chats or channels, featuring custom routing, batch filtering, and interactive UI.</em>
</p>
<hr>

## ✨ Features

- 📥 **Media Extraction:** Download photos, videos, audio files, and documents from restricted sources.
- 🚀 **Auto-Forward to Channels:** Option to route batch downloads directly to a target channel.
- 🔍 **Media Filtering:** Grab specific media types during batch process (e.g., only `video` or `doc`).
- ✅ **Media Group Support:** Flawlessly handles and processes multiple files sent as an album/media group.
- 🔄 **Live Progress:** Real-time progress tracking for single files and batch operations.

## 📋 Requirements

To begin using the bot, ensure you have the following:

- **Telegram Bot Token:** Get one from [@BotFather](https://t.me/BotFather).
- **API ID and Hash:** Create an application on [my.telegram.org](https://my.telegram.org) to get these.
  > ⚠️ **Warning**: This is an irreversible process; API ID and API Hash can only be deleted by deleting your Telegram account. Never share your credentials.
- **Session String:** Run `session-string.py` in your environment (e.g., Colab) and follow the prompts to generate your Pyrogram session string.

## ⚙️ Configuration

You can tweak the bot's performance by adjusting `config.py`:
- **`MAX_CONCURRENT_DOWNLOADS`**: Number of simultaneous downloads (default: `1`)
- **`MAX_CONCURRENT_UPLOADS`**: Number of simultaneous uploads (default: `1`)
- **`BATCH_SIZE`**: Number of posts to process in parallel during batch downloads (default: `1`)
- **`FLOOD_WAIT_DELAY`**: Delay in seconds between batch chunks to respect Telegram's API limits (default: `5`)

## 🚀 Deploy the Bot (Google Colab)

Follow these steps for a quick cloud deployment:

1. **Clone the repo:** `!git clone https://github.com/invinciblevenom/save-restricted-content.git`
2. **Install dependencies:** `!pip install -r /content/save-restricted-content/requirements.txt`
3. **Get Session String (Login when asked):** `!python3 /content/save-restricted-content/session-string.py`
4. **Set Environment Variables:** Add your credentials to Colab Secrets, or run this in a cell:
   ```python
   import os
   os.environ["API_ID"] = "your_api_id"
   os.environ["API_HASH"] = "your_api_hash"
   os.environ["BOT_TOKEN"] = "your_bot_token"
   os.environ["SESSION_STRING"] = "your_session_string"

 5. Start the Bot: !python3 /content/save-restricted-content/main.py


## 📖 Usage & Commands
/start – Check if the bot is alive and view basic info.

/help – Show detailed instructions and command syntax.

/dl <post_URL> (or just paste a link) – Fetch media/text from a single Telegram post.

/batch <start_link> <end_link> [filter] – Fetch a range of posts. The bot will ask if you want to send the media to the Bot Chat or a Custom Channel.

Filters available: video, doc, photo, audio, or leave blank for all.

💡 Example: /batch https://t.me/mychannel/100 https://t.me/mychannel/120 video

⚠️ Note: If routing to a custom channel, the bot must be an Administrator with 'Post Messages' rights in the target channel.

/stop – Safely cancel all active download/upload tasks.

/stats – View live system status (Uptime, Disk Space, RAM, CPU).

/logs – Download the logs.txt file for debugging.

🔒 Important: Your user session account MUST be a member of the source chat/channel you are trying to download from, or the bot will not be able to access the messages.

## 🤝 Acknowledgment and Credits
This project originally began utilizing the base code from [RestrictedContentDL](https://github.com/bisnuray/RestrictedContentDL) authored by Bisnu Ray.

While the core concept and initial foundation were derived from their work, this repository has since undergone architectural rewrites, feature additions, and logic overhauls. It is now developed and maintained independently as a hard fork.

Huge thanks to Bisnu Ray for laying down the original groundwork!

