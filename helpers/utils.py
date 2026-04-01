import os
import asyncio
from time import time
from asyncio.subprocess import PIPE
from asyncio import create_subprocess_exec, create_subprocess_shell, wait_for

from pyrogram.types import (
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    InputMediaAudio,
)

from pyrogram.errors import FloodWait, Timeout

from helpers.files import (
    fileSizeLimit,
    cleanup_download,
    get_readable_time,
    get_download_path,
    get_readable_file_size
)

from helpers.msg import (
    get_parsed_msg,
    get_file_name
)
from logger import LOGGER

def get_progress_text(filename, file_size="Unknown Size", batch_stats=None, warning=""):
    if not batch_stats:
        text = (
            f"> 📥 **PROCESSING FILE**\n"
            f"> ├ **File:** `{filename}`\n"
            f"> └ **Size:** `{file_size}`"
        )
        if warning:
            text += f"\n>\n> ⚠️ **{warning}**"
        return text

    current = batch_stats["processed"]
    total = batch_stats["total"]
    rem = total - current
    pct = (current / total) * 100 if total > 0 else 100
    
    text = (
        f"> 📥 **PROCESSING**\n"
        f"> ├ **File:** {filename}\n"
        f"> └ **Size:** {file_size}\n"
        f">\n"
        f"> 🚀 **PROGRESS: {pct:.1f}%**\n"
        f"> ├ 📊 **Total Links:** {total}\n"
        f"> ├ ⚡ **Current:** {current}\n"
        f"> └ ⏳ **Remaining:** {rem}"
    )
    if warning:
        text += f"\n>\n> ⚠️ **{warning}**"
    return text

async def cmd_exec(cmd, shell=False):
    if shell:
        proc = await create_subprocess_shell(cmd, stdout=PIPE, stderr=PIPE)
    else:
        proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    
    try:
        stdout, stderr = await wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        proc.kill()
        return "Timeout", "Process timed out", 1
    except Exception as e:
        proc.kill()
        return "Error", str(e), 1

    try:
        stdout = stdout.decode().strip()
    except:
        stdout = "Unable to decode the response!"
    try:
        stderr = stderr.decode().strip()
    except:
        stderr = "Unable to decode the error!"
    return stdout, stderr, proc.returncode

async def get_media_info(path):
    try:
        result = await cmd_exec([
            "ffprobe", "-hide_banner", "-loglevel", "error",
            "-print_format", "json", "-show_format", "-show_streams", path,
        ])
    except Exception as e:
        LOGGER(__name__).error(f"Get Media Info: {e}. File: {path}")
        return 0, None, None, None, None

    if result[0] and result[2] == 0:
        try:
            import json
            data = json.loads(result[0])

            fields = data.get("format", {})
            duration = round(float(fields.get("duration", 0)))

            tags = fields.get("tags", {})
            artist = tags.get("artist") or tags.get("ARTIST") or tags.get("Artist")
            title = tags.get("title") or tags.get("TITLE") or tags.get("Title")

            width = None
            height = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    width = stream.get("width")
                    height = stream.get("height")
                    break

            return duration, artist, title, width, height
        except Exception as e:
            LOGGER(__name__).error(f"Error parsing media info: {e}")
            return 0, None, None, None, None
    return 0, None, None, None, None

async def get_video_thumbnail(video_file, duration):
    os.makedirs("Assets", exist_ok=True)
    output = os.path.join("Assets", "video_thumb.jpg")

    if duration is None:
        duration = (await get_media_info(video_file))[0]
    if not duration:
        duration = 3
    
    duration //= 2

    if os.path.exists(output):
        try:
            os.remove(output)
        except:
            pass

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", str(duration), "-i", video_file,
        "-vframes", "1", "-q:v", "2",
        "-y", output,
    ]
    try:
        _, err, code = await cmd_exec(cmd)
        
        if code != 0 or not os.path.exists(output):
            LOGGER(__name__).warning(f"Thumbnail generation failed for {os.path.basename(video_file)}: {err}")
            return None
    except Exception as e:
        LOGGER(__name__).warning(f"Thumbnail generation error for {os.path.basename(video_file)}: {e}")
        return None
    return output

async def send_media(
    bot, message, media_path, media_type, caption, progress_msg=None, batch_stats=None
):
    try:
        file_size = os.path.getsize(media_path)
    except OSError as e:
        LOGGER(__name__).error(f"File not found or inaccessible: {e}")
        return False

    if not await fileSizeLimit(file_size, message, "upload"):
        return False
        
    filename = os.path.basename(media_path)
    file_size_str = get_readable_file_size(file_size) if file_size else "Unknown Size"

    async def _send_once():
        if media_type == "photo":
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=media_path,
                caption=caption or ""
            )
        elif media_type == "video":
            duration, _, _, width, height = await get_media_info(media_path)
            if not duration: duration = 0
            if not width or not height: width, height = 640, 480
            thumb = await get_video_thumbnail(media_path, duration)
            await bot.send_video(
                chat_id=message.chat.id,
                video=media_path,
                duration=duration,
                width=width,
                height=height,
                thumb=thumb,
                caption=caption or "",
                supports_streaming=True
            )
        elif media_type == "audio":
            duration, artist, title, _, _ = await get_media_info(media_path)
            await bot.send_audio(
                chat_id=message.chat.id,
                audio=media_path,
                duration=duration,
                performer=artist,
                title=title,
                caption=caption or ""
            )
        elif media_type == "document":
            await bot.send_document(
                chat_id=message.chat.id,
                document=media_path,
                caption=caption or ""
            )

    max_retries = 3
    retry_count = 1

    while retry_count <= max_retries:
        try:
            await _send_once()
            return True
        except FloodWait as e:
            wait_s = int(getattr(e, "value", 0) or 0)
            wait_msg = get_readable_time(wait_s)
            LOGGER(__name__).warning(f"FloodWait: Sleeping {wait_msg}")
            if progress_msg:
                try:
                    await progress_msg.edit(get_progress_text(filename, file_size_str, batch_stats, f"Rate Limited: Pausing for {wait_msg}..."))
                except Exception:
                    pass
            await asyncio.sleep(wait_s + 1)
            continue
            
        except (Timeout, TimeoutError):
            LOGGER(__name__).warning(f"TimeoutError: Request timed out. Retrying ({retry_count}/{max_retries})")
            if progress_msg:
                try:
                    await progress_msg.edit(get_progress_text(filename, file_size_str, batch_stats, f"Network Issue: Retrying {retry_count}/{max_retries}..."))
                except Exception:
                    pass
            await asyncio.sleep(5)
            retry_count += 1
            continue
            
        except Exception as e:
            LOGGER(__name__).error(f"Upload failed: {e} (Attempt {retry_count}/{max_retries})")
            if retry_count < max_retries:
                if progress_msg:
                    try:
                        await progress_msg.edit(get_progress_text(filename, file_size_str, batch_stats, f"Network Issue: Retrying {retry_count}/{max_retries}..."))
                    except Exception:
                        pass
                await asyncio.sleep(3)
                retry_count += 1
                continue
            else:
                return False
    
    return False

async def download_single_media(msg, semaphore, fetch_time=None, progress_msg=None, batch_stats=None):
    filename = get_file_name(msg.id, msg)
    
    download_path = get_download_path(msg.id, filename)
    
    max_retries = 3
    retry_count = 1

    while retry_count <= max_retries:
        try:
            async with semaphore:
                if fetch_time and (time() - fetch_time) > 7200:
                    try:
                        fresh_msg = await msg._client.get_messages(chat_id=msg.chat.id, message_ids=msg.id)
                        if fresh_msg and not fresh_msg.empty:
                            msg = fresh_msg
                            fetch_time = time()
                    except Exception:
                        pass

                media_path = await msg.download(
                    file_name=download_path
                )

            parsed_caption = await get_parsed_msg(
                msg.caption or "", msg.caption_entities
            )

            if msg.photo:
                return ("success", media_path, InputMediaPhoto(media=media_path, caption=parsed_caption))
            elif msg.video:
                return ("success", media_path, InputMediaVideo(media=media_path, caption=parsed_caption))
            elif msg.document:
                return ("success", media_path, InputMediaDocument(media=media_path, caption=parsed_caption))
            elif msg.audio:
                return ("success", media_path, InputMediaAudio(media=media_path, caption=parsed_caption))

        except FloodWait as e:
            wait_s = int(getattr(e, "value", 0) or 0)
            wait_msg = get_readable_time(wait_s)
            LOGGER(__name__).warning(f"FloodWait downloading: Sleeping {wait_msg}")
            
            if progress_msg:
                media_obj = msg.document or msg.video or msg.audio or msg.photo or msg.animation or msg.voice or msg.video_note or msg.sticker
                pre_file_size = getattr(media_obj, "file_size", 0) if media_obj else 0
                file_size_str = get_readable_file_size(pre_file_size)
                try:
                    await progress_msg.edit(get_progress_text(filename, file_size_str, batch_stats, f"Rate Limited: Pausing for {wait_msg}..."))
                except Exception:
                    pass
            await asyncio.sleep(wait_s + 1)
            continue
        except Exception as e:
            LOGGER(__name__).info(f"Error downloading: {e} (Attempt {retry_count})")
            if retry_count < max_retries:
                await asyncio.sleep(2)
                retry_count += 1
                continue
            return ("error", None, None)

    return ("skip", None, None)

async def processMediaGroup(chat_message, bot, message, semaphore, progress_msg=None, batch_stats=None):
    media_group_messages = await chat_message.get_media_group()
    valid_media = []
    temp_paths = []
    invalid_paths = []

    group_fetch_time = time()
    LOGGER(__name__).info(
        f"Downloading media group with {len(media_group_messages)} items..."
    )

    download_tasks = []
    for msg in media_group_messages:
        if msg.photo or msg.video or msg.document or msg.audio:
            download_tasks.append(download_single_media(msg, semaphore, group_fetch_time, progress_msg, batch_stats))

    results = await asyncio.gather(*download_tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            LOGGER(__name__).error(f"Download task failed: {result}")
            continue

        status, media_path, media_obj = result
        if status == "success" and media_path and media_obj:
            temp_paths.append(media_path)
            valid_media.append(media_obj)
        elif status == "error" and media_path:
            invalid_paths.append(media_path)

    LOGGER(__name__).info(f"Valid media count: {len(valid_media)}")

    if valid_media:
        sent_success = False
        max_retries = 3
        retry_count = 1

        while retry_count <= max_retries:
            try:
                await bot.send_media_group(chat_id=message.chat.id, media=valid_media)
                sent_success = True
                break
            except FloodWait as e:
                wait_s = int(getattr(e, "value", 0) or 0)
                wait_msg = get_readable_time(wait_s)
                LOGGER(__name__).warning(f"FloodWait sending group: Sleeping {wait_msg}")
                if progress_msg:
                    try:
                        await progress_msg.edit(get_progress_text("Media Group", "Multiple Files", batch_stats, f"Rate Limited: Pausing for {wait_msg}..."))
                    except Exception:
                        pass
                await asyncio.sleep(wait_s + 1)
                continue
            except Exception as e:
                LOGGER(__name__).error(f"Media group send failed: {e}")
                if retry_count < max_retries:
                    retry_count += 1
                    await asyncio.sleep(2)
                    continue
                break
        
        if not sent_success:
            await message.reply(
                "**❌ Failed to send media group, trying individual uploads**"
            )
            for media in valid_media:
                try:
                    if isinstance(media, InputMediaPhoto):
                        await bot.send_photo(chat_id=message.chat.id, photo=media.media, caption=media.caption)
                    elif isinstance(media, InputMediaVideo):
                        await bot.send_video(chat_id=message.chat.id, video=media.media, caption=media.caption)
                    elif isinstance(media, InputMediaDocument):
                        await bot.send_document(chat_id=message.chat.id, document=media.media, caption=media.caption)
                    elif isinstance(media, InputMediaAudio):
                        await bot.send_audio(chat_id=message.chat.id, audio=media.media, caption=media.caption)
                except Exception as e:
                    await message.reply(f"Failed to upload individual media: {e}")

        for path in temp_paths + invalid_paths:
            cleanup_download(path)
        return True

    for path in invalid_paths:
        cleanup_download(path)
    return False