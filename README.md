<h1 align="center">Save Restricted Content Bot</h1>

<p align="center">
  <em>An advanced Telegram bot script to download restricted content such as photos, videos, audio files, or documents from Telegram private chats or channels. This bot can also copy text messages from Telegram posts.</em>
</p>
<hr>

## Features

- 📥 Download media (photos, videos, audio, documents).
- ✅ Supports downloading from both single media posts and media groups.
- 🔄 Progress bar showing real-time downloading progress.
- ✍️ Copy text messages or captions from Telegram posts.

## Requirements

To begin using bot, ensure you already have following:

- A Telegram bot token (you can get one from [@BotFather](https://t.me/BotFather) on Telegram)
- API ID and Hash: You can get these by creating an application on [my.telegram.org](https://my.telegram.org) 

> **Warning**: This is irreversible process, API ID and Hash can only be deleted by deleting your Telegram account. Never share your credentials.

- To Get `SESSION_STRING` run `session-string.py` in Colab and follow instructions. 

> **Note**: All dependencies will be installed during Colab setup.


## Configuration

Performance settings (change in `config.py`):
   - **`MAX_CONCURRENT_DOWNLOADS`**: Number of simultaneous downloads (default: 3)
   - **`MAX_CONCURRENT_UPLOADS`**: Number of simultaneous uploads (default: 2)
   - **`BATCH_SIZE`**: Number of posts to process in parallel during batch downloads (default: 5)
   - **`FLOOD_WAIT_DELAY`**: Delay in seconds between batch groups to avoid flood limits (default: 10)

## Deploy the Bot

Follow below steps for deployment:
- Clone the repo: `!git clone https://github.com/invinciblevenom/save-restricted-content.git`
- Install all dependencies: `!pip install -r /content/save-restricted-content/requirements.txt`
- Get Session String. Login when asked: `!python3 /content/save-restricted-content/session-string.py`
- You can save API_ID, API_HASH, BOT_TOKEN and SESSION_STRING in Colab Secrets or simply run this in a cell after filling values

  
  `import os`

  
  `os.environ["API_ID"] = ""`

  
  `os.environ["API_HASH"] = ""`

  
  `os.environ["BOT_TOKEN"] = ""`

  
  `os.environ["SESSION_STRING"] = ""`

- Start the Bot: `!python3 /content/save-restricted-content/main.py`


## Usage

- **`/start`** – Welcomes you and gives a brief introduction.  
- **`/help`** – Shows detailed instructions and examples.  
- **`/dl <post_URL>`** or simply paste a Telegram post link – Fetch photos, videos, audio, or documents from that post.  
- **`/batch <start_link> <end_link>`** – Batch-download a range of posts in one go.  

  > 💡 Example: `/batch https://t.me/mychannel/100 https://t.me/mychannel/120`  
- **`/stop`** – Stop all pending downloads if the bot hangs.  
- **`/logs`** – Download the bot’s logs file.  
- **`/stats`** – View current status (uptime, disk, memory, network, CPU, etc.).  

> **Note:** Make sure that your user session is a member of the source chat or channel before downloading.

## Original Author

- Name: Bisnu Ray
- GitHub: [https://github.com/bisnuray/RestrictedContentDL](https://github.com/bisnuray/RestrictedContentDL)

