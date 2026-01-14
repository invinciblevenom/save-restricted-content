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

WIP

## Configuration

Performance settings (change in `config.py`):
   - **`MAX_CONCURRENT_DOWNLOADS`**: Number of simultaneous downloads (default: 3)
   - **`BATCH_SIZE`**: Number of posts to process in parallel during batch downloads (default: 10)
   - **`FLOOD_WAIT_DELAY`**: Delay in seconds between batch groups to avoid flood limits (default: 3)

## Deploy the Bot

WIP

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

