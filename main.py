import os
import math
import shutil
import psutil
import asyncio
import re
from time import time
from pyrogram.enums import ParseMode
from pyrogram import Client, compose, filters
from pyrogram.errors import PeerIdInvalid, BadRequest, FloodWait, FileReferenceExpired
from pyrogram.types import Message

from helpers.utils import (
    processMediaGroup,
    send_media,
    get_progress_text
)

from helpers.files import (
    get_download_path,
    fileSizeLimit,
    get_readable_file_size,
    get_readable_time,
    cleanup_download
)

from helpers.msg import (
    getChatMsgID,
    get_file_name,
    get_parsed_msg
)

from config import PyroConf
from logger import LOGGER

bot = Client(
    "media_bot",
    api_id=PyroConf.API_ID,
    api_hash=PyroConf.API_HASH,
    bot_token=PyroConf.BOT_TOKEN,
    workers=100,
    parse_mode=ParseMode.MARKDOWN,
    max_concurrent_transmissions=PyroConf.MAX_CONCURRENT_UPLOADS, 
    sleep_threshold=60,
)

user = Client(
    "user_session",
    workers=100,
    session_string=PyroConf.SESSION_STRING,
    max_concurrent_transmissions=PyroConf.MAX_CONCURRENT_DOWNLOADS,
    sleep_threshold=60,
)

RUNNING_TASKS = set()
download_semaphore = None
upload_semaphore = None

def format_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def get_semaphores():
    global download_semaphore, upload_semaphore
    if download_semaphore is None:
        download_semaphore = asyncio.Semaphore(PyroConf.MAX_CONCURRENT_DOWNLOADS)
    if upload_semaphore is None:
        upload_semaphore = asyncio.Semaphore(PyroConf.MAX_CONCURRENT_UPLOADS)
    return download_semaphore, upload_semaphore

def track_task(coro):
    task = asyncio.create_task(coro)
    RUNNING_TASKS.add(task)
    def _remove(_):
        RUNNING_TASKS.discard(task)
    task.add_done_callback(_remove)
    return task

@bot.on_message(filters.command("start") & filters.private)
async def start(_, message: Message):
    welcome_text = (
        "🤖 **Welcome to Save Restricted Content Bot!**\n\n"
        "I can grab photos, videos, audio, and documents from any Telegram post.\n"
        "Just send me a link (paste it directly or use `/dl <link>`),\n\n"
        "ℹ️ Use `/help` to view all commands and examples.\n"
        "🔒 Make sure the user client is part of the chat.\n\n"
        "Ready? Send me a Telegram post link!"
    )
    await message.reply(welcome_text, disable_web_page_preview=True)

@bot.on_message(filters.command("help") & filters.private)
async def help_command(_, message: Message):
    help_text = (
        "💡 **Save Restricted Content Bot Help:**\n\n"
        "➤ **Single Download**\n"
        "   – Send `/dl <post_URL>` **or** just paste a Telegram post link to fetch photos, videos, audio, or documents.\n\n"
        "➤ **Batch Download**\n"
        "   – Send `/batch start_link end_link [filter]` to grab a series of posts in one go.\n"
        "   – Filters available: video, doc, photo, audio (leave empty for all).\n\n"
        "  💡Example: `/batch https://t.me/mychannel/100 https://t.me/mychannel/120 video`\n"
        "➤ **Requirements**\n"
        "   – Make sure the user client is part of the chat.\n\n"
        "➤ **If the bot hangs**\n"
        "   – Send `/stop` to cancel any pending downloads.\n\n"
        "➤ **Logs**\n"
        "   – Send `/logs` to download the bot’s log file.\n\n"
        "➤ **Stats**\n"
        "   – Send `/stats` to view current status.\n\n"
    )
    await message.reply(help_text, disable_web_page_preview=True)

async def handle_download(bot: Client, message: Message, post_url: str, pre_fetched_msg: Message = None, fetch_time: float = None, progress_msg: Message = None, batch_stats: dict = None):
    task_start_time = time()
    if "?" in post_url:
        post_url = post_url.split("?", 1)[0]

    media_path = None 
    dl_sem, up_sem = get_semaphores()

    try:
        if pre_fetched_msg:
            chat_message = pre_fetched_msg
            message_id = chat_message.id
        else:
            chat_id, message_id = getChatMsgID(post_url)
            chat_message = await user.get_messages(chat_id=chat_id, message_ids=message_id)

        if not chat_message or chat_message.empty:
             await message.reply("**❌ Message not found or inaccessible.**")
             return

        if chat_message.document or chat_message.video or chat_message.audio:
            file_size = (
                chat_message.document.file_size
                if chat_message.document
                else chat_message.video.file_size
                if chat_message.video
                else chat_message.audio.file_size
            )
            if not await fileSizeLimit(
                file_size, message, "download", user.me.is_premium
            ):
                return

        parsed_caption = await get_parsed_msg(
            chat_message.caption or "", chat_message.caption_entities
        )

        has_downloadable_media = (
            chat_message.document or chat_message.video or 
            chat_message.audio or chat_message.photo or 
            chat_message.animation or chat_message.voice or 
            chat_message.video_note or chat_message.sticker
        )

        if chat_message.media_group_id:
            if progress_msg and batch_stats:
                batch_stats["processed"] += 1
                try:
                    await progress_msg.edit(get_progress_text("Media Group", "Multiple Files", batch_stats))
                except Exception:
                    pass
            elif not progress_msg:
                progress_msg = await message.reply(get_progress_text("Media Group", "Multiple Files"))

            if not await processMediaGroup(chat_message, bot, message, dl_sem, progress_msg, batch_stats):
                if progress_msg:
                    try:
                        await progress_msg.edit("❌ **Failed to process Media Group**")
                        await asyncio.sleep(2)
                    except Exception:
                        pass
            
            if not batch_stats and progress_msg:
                try:
                    await progress_msg.delete()
                except Exception:
                    pass
            return

        elif has_downloadable_media:
            filename = get_file_name(message_id, chat_message)
            download_path = get_download_path(message_id, filename)

            media_obj = (
                chat_message.document or chat_message.video or 
                chat_message.audio or chat_message.photo or 
                chat_message.animation or chat_message.voice or 
                chat_message.video_note or chat_message.sticker
            )
            pre_file_size = getattr(media_obj, "file_size", 0) if media_obj else 0
            file_size_str = format_size(pre_file_size)
            
            LOGGER(__name__).info(f"Downloading media: {filename} (Size: {file_size_str})")

            async with dl_sem:
                if pre_fetched_msg and fetch_time and (time() - fetch_time) > 7200:
                    try:
                        chat_id, msg_id = getChatMsgID(post_url)
                        fresh_msg = await user.get_messages(chat_id=chat_id, message_ids=msg_id)
                        if fresh_msg and not fresh_msg.empty:
                            chat_message = fresh_msg
                            fetch_time = time()
                    except Exception as e:
                        LOGGER(__name__).warning(f"Failed to refresh stale reference for {filename}: {e}")

                if progress_msg and batch_stats:
                    batch_stats["processed"] += 1
                    try:
                        await progress_msg.edit(get_progress_text(filename, file_size_str, batch_stats))
                    except Exception:
                        pass
                elif not progress_msg:
                    progress_msg = await message.reply(get_progress_text(filename, file_size_str))
                
                max_retries = 3
                retry_count = 1
                
                while retry_count <= max_retries:
                    try:
                        media_path = await chat_message.download(
                            file_name=download_path
                        )
                        
                        if media_path and os.path.exists(media_path):
                            actual_size = os.path.getsize(media_path)

                            if pre_file_size > 0 and actual_size < pre_file_size:
                                LOGGER(__name__).warning(f"Download Incomplete: {post_url}. Refetching message...")
                                
                                os.remove(media_path)
                                media_path = None
                                
                                try:
                                    chat_id, msg_id = getChatMsgID(post_url)
                                    chat_message = await user.get_messages(chat_id=chat_id, message_ids=msg_id)
                                except Exception as refetch_err:
                                    LOGGER(__name__).error(f"Failed to refetch message for {filename}: {refetch_err}")
                                
                                retry_count += 1
                                continue

                        break
                    except FloodWait as e:
                        wait_s = int(getattr(e, "value", 0) or 0)
                        wait_msg = get_readable_time(wait_s)
                        LOGGER(__name__).warning(f"FloodWait while downloading media: {wait_s}s")
                        if progress_msg:
                            try:
                                await progress_msg.edit(get_progress_text(filename, file_size_str, batch_stats, f"⏳ Rate Limited: Pausing for {wait_msg}..."))
                            except Exception:
                                pass
                        await asyncio.sleep(wait_s + 1)
                        continue 
                    except FileReferenceExpired:
                        LOGGER(__name__).warning(f"File reference expired for {filename}. Refetching message...")
                        try:
                            chat_id, msg_id = getChatMsgID(post_url)
                            chat_message = await user.get_messages(chat_id=chat_id, message_ids=msg_id)
                        except Exception as refetch_err:
                            LOGGER(__name__).error(f"Failed to refetch message for {filename}: {refetch_err}")
                        
                        retry_count += 1
                        continue
                    except Exception as e:
                        LOGGER(__name__).error(f"Download Error: {e}")
                        if retry_count < max_retries:
                             await asyncio.sleep(2)
                             retry_count += 1
                             continue
                        break

            if not media_path or not os.path.exists(media_path):
                if progress_msg:
                    try:
                        await progress_msg.edit(f"❌ **Failed to process {filename}**")
                        await asyncio.sleep(2)
                    except Exception:
                        pass
                return

            file_size = os.path.getsize(media_path)
            if file_size == 0:
                if progress_msg:
                    try:
                        await progress_msg.edit(f"❌ **Failed to process {filename}**")
                        await asyncio.sleep(2)
                    except Exception:
                        pass
                return
            
            media_type = (
                "photo"
                if chat_message.photo
                else "video"
                if chat_message.video
                else "audio"
                if chat_message.audio
                else "document"
            )
            
            async with up_sem:
                upload_success = await send_media(
                    bot,
                    message,
                    media_path,
                    media_type,
                    parsed_caption,
                    progress_msg,
                    batch_stats
                )

            if upload_success:
                if not batch_stats and progress_msg:
                    try:
                        await progress_msg.delete()
                    except Exception:
                        pass
                LOGGER(__name__).info(f"Finished Processing: {post_url}")

        elif chat_message.text:
            if batch_stats:
                batch_stats["processed"] += 1
                try:
                    await progress_msg.edit(get_progress_text("Text Message", "N/A", batch_stats))
                except Exception:
                    pass
            await message.reply(
                chat_message.text.html, 
                parse_mode=ParseMode.HTML, 
                disable_web_page_preview=True
            )
            LOGGER(__name__).info(f"Finished Processing: {post_url}")
        else:
            if batch_stats:
                batch_stats["processed"] += 1
            await message.reply("**No downloadable media or text found in the post URL.**")

    except (PeerIdInvalid, BadRequest, KeyError):
        await message.reply("**Make sure the user client is part of the chat.**")
    except FloodWait as e:
        wait_s = int(getattr(e, "value", 0) or 0)
        LOGGER(__name__).warning(f"FloodWait in handle_download: {wait_s}s")
        if wait_s > 0:
            await asyncio.sleep(wait_s + 1)
        return
    except Exception as e:
        error_message = f"**❌ {str(e)}**"
        await message.reply(error_message)
        LOGGER(__name__).error(f"Error handling {post_url}: {e}")
    finally:
        if media_path:
            cleanup_download(media_path)
        
        elapsed = time() - task_start_time
        if elapsed < 2.0:
            await asyncio.sleep(2.0 - elapsed)

@bot.on_message(filters.command("dl") & filters.private)
async def download_media(bot: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("**Provide a post URL after the /dl command.**")
        return

    post_url = message.command[1]
    await track_task(handle_download(bot, message, post_url))

@bot.on_message(filters.command("batch") & filters.private)
async def download_range(bot: Client, message: Message):
    args = message.text.split()

    if len(args) < 3 or not all(arg.startswith("https://t.me/") for arg in args[1:3]):
        await message.reply(
            "🚀 **Batch Download**\n"
            "`/batch start_link end_link [filter]`\n\n"
            "💡 **Examples:**\n"
            "`/batch https://t.me/mychannel/100 https://t.me/mychannel/120` (Left blank for All)\n\n"
            "`/batch https://t.me/mychannel/100 https://t.me/mychannel/120 video` (Only Videos)\n\n"
            "`/batch https://t.me/mychannel/100 https://t.me/mychannel/120 doc` (Only Documents)"
        )
        return

    filter_type = args[3].lower() if len(args) > 3 else "all"

    try:
        start_chat, start_id = getChatMsgID(args[1])
        end_chat,   end_id   = getChatMsgID(args[2])
    except Exception as e:
        return await message.reply(f"**❌ Error parsing links:\n{e}**")

    if start_chat != end_chat:
        return await message.reply("**❌ Both links must be from the same channel.**")
    if start_id > end_id:
        return await message.reply("**❌ Invalid range: start ID cannot exceed end ID.**")

    try:
        await user.get_chat(start_chat)
    except Exception:
        pass

    prefix = args[1].rsplit("/", 1)[0]
    loading = await message.reply(f"📥 **Started Batch Processing...**")
    try:
        await loading.pin(disable_notification=True, both_sides=True)
    except Exception:
        pass

    downloaded = skipped = failed = 0
    batch_tasks = []
    BATCH_SIZE = PyroConf.BATCH_SIZE
    processed_media_groups = set()
    
    all_ids = list(range(start_id, end_id + 1))
    chunk_size = 200
    
    total_links = len(all_ids)
    batch_stats = {"total": total_links, "processed": 0}

    for i in range(0, len(all_ids), chunk_size):
        chunk_ids = all_ids[i:i + chunk_size]
        try:
            chunk_fetch_time = time()
            messages = await user.get_messages(chat_id=start_chat, message_ids=chunk_ids)
            if not isinstance(messages, list):
                messages = [messages]
        except Exception as e:
            LOGGER(__name__).error(f"Error fetching chunk: {e}")
            failed += len(chunk_ids)
            batch_stats["processed"] += len(chunk_ids)
            continue
            
        for chat_msg in messages:
            if not chat_msg or chat_msg.empty:
                skipped += 1
                batch_stats["processed"] += 1
                continue
            
            msg_id = chat_msg.id
            url = f"{prefix}/{msg_id}"
            
            if chat_msg.media_group_id:
                if chat_msg.media_group_id in processed_media_groups:
                    skipped += 1
                    batch_stats["processed"] += 1
                    continue
                processed_media_groups.add(chat_msg.media_group_id)

            has_media = bool(chat_msg.media_group_id or chat_msg.media)
            has_text  = bool(chat_msg.text or chat_msg.caption)
            if not (has_media or has_text):
                skipped += 1
                batch_stats["processed"] += 1
                continue
                
            if filter_type != "all":
                if filter_type == "video" and not chat_msg.video:
                    skipped += 1
                    batch_stats["processed"] += 1
                    continue
                elif filter_type == "doc" and not chat_msg.document:
                    skipped += 1
                    batch_stats["processed"] += 1
                    continue
                elif filter_type == "audio" and not chat_msg.audio:
                    skipped += 1
                    batch_stats["processed"] += 1
                    continue
                elif filter_type == "photo" and not chat_msg.photo:
                    skipped += 1
                    batch_stats["processed"] += 1
                    continue

            task = track_task(handle_download(
                bot, message, url, 
                pre_fetched_msg=chat_msg, 
                fetch_time=chunk_fetch_time,
                progress_msg=loading,
                batch_stats=batch_stats
            ))
            batch_tasks.append(task)
            
            if len(batch_tasks) >= BATCH_SIZE:
                results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, asyncio.CancelledError):
                        try:
                            await loading.unpin()
                        except Exception:
                            pass
                        await loading.delete()
                        return await message.reply(
                            f"**❌ Batch canceled** after downloading `{downloaded}` posts."
                        )
                    elif isinstance(result, Exception):
                        failed += 1
                        LOGGER(__name__).error(f"Error: {result}")
                    else:
                        downloaded += 1

                batch_tasks.clear()
                await asyncio.sleep(PyroConf.FLOOD_WAIT_DELAY)

    if batch_tasks:
        results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                failed += 1
            else:
                downloaded += 1

    try:
        await loading.unpin()
    except Exception:
        pass
    await loading.delete()
    await message.reply(
        "**✅ Batch Process Completed!**\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📥 **Downloaded** : {downloaded} post(s)\n"
        f"⏭️ **Skipped** : {skipped} (no content or filtered)\n"
        f"❌ **Failed** : {failed} error(s)"
    )

@bot.on_message(filters.private & ~filters.command(["start", "help", "dl", "stats", "logs", "stop"]))
async def handle_any_message(bot: Client, message: Message):
    if message.text and re.search(r"t\.me\/", message.text):
        await track_task(handle_download(bot, message, message.text))

@bot.on_message(filters.command("stats") & filters.private)
async def stats(_, message: Message):
    currentTime = get_readable_time(time() - PyroConf.BOT_START_TIME)
    total, used, free = shutil.disk_usage(".")
    total = get_readable_file_size(total)
    used = get_readable_file_size(used)
    free = get_readable_file_size(free)
    sent = get_readable_file_size(psutil.net_io_counters().bytes_sent)
    recv = get_readable_file_size(psutil.net_io_counters().bytes_recv)
    cpuUsage = psutil.cpu_percent(interval=0.5)
    memory = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    process = psutil.Process(os.getpid())

    stats = (
        "**Bot's Live and Running Successfully.**\n\n"
        f"**➜ Bot Uptime:** {currentTime}\n"
        f"**➜ Free Disk Space:** {free}\n"
        f"**➜ Total Disk Space:** {total}\n"
        f"**➜ Memory Usage:** {round(process.memory_info()[0] / 1024**2)} MiB\n\n"
        f"**➜ Uploaded:** {sent}\n"
        f"**➜ Downloaded:** {recv}\n\n"
        f"**➜ CPU:** {cpuUsage}% | "
        f"**➜ RAM:** {memory}% | "
        f"**➜ DISK:** {disk}%"
    )
    await message.reply(stats)

@bot.on_message(filters.command("logs") & filters.private)
async def logs(_, message: Message):
    if os.path.exists("logs.txt"):
        await message.reply_document(document="logs.txt", caption="**Logs**")
    else:
        await message.reply("**Not exists**")

@bot.on_message(filters.command("stop") & filters.private)
async def cancel_all_tasks(_, message: Message):
    cancelled = 0
    for task in list(RUNNING_TASKS):
        if not task.done():
            task.cancel()
            cancelled += 1
    await message.reply(f"**Cancelled {cancelled} running task(s).**")

if __name__ == "__main__":
    LOGGER(__name__).info("Bot Started!")
    try:
        compose([bot, user])
    except KeyboardInterrupt:
        pass
    except Exception as e:
        LOGGER(__name__).error(f"Bot Crashed: {e}")
    finally:
        LOGGER(__name__).info("Bot Stopped.")