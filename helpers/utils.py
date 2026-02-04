import os
import asyncio
from time import time
from asyncio.subprocess import PIPE
from asyncio import create_subprocess_exec, create_subprocess_shell, wait_for

from pyleaves import Leaves
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
    get_download_path
)

from helpers.msg import (
    get_parsed_msg,
    get_file_name
)
from logger import LOGGER

PROGRESS_BAR = """
Percentage: {percentage:.2f}% | {current}/{total}
Speed: {speed}/s
Estimated Time Left: {est_time}
"""

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

def progressArgs(action: str, progress_message, start_time, filename: str = None):
    if filename:
        clean_filename = filename.replace(".", ".\u200b") 
        action = f"{action}\nFile: {clean_filename}"
    return (action, progress_message, start_time, PROGRESS_BAR, "■", "□")

async def send_media(
    bot, message, media_path, media_type, caption, progress_message, start_time
):
    try:
        file_size = os.path.getsize(media_path)
    except OSError as e:
        LOGGER(__name__).error(f"File not found or inaccessible: {e}")
        return False

    if not await fileSizeLimit(file_size, message, "upload"):
        return False

    filename = os.path.basename(media_path)
    LOGGER(__name__).info(f"Uploading media: {filename} ({media_type})")
    progress_args = progressArgs("📥 Uploading", progress_message, start_time, filename)

    async def _send_once():
        if media_type == "photo":
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=media_path,
                caption=caption or "",
                progress=Leaves.progress_for_pyrogram,
                progress_args=progress_args,
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
                supports_streaming=True,
                progress=Leaves.progress_for_pyrogram,
                progress_args=progress_args,
            )
        elif media_type == "audio":
            duration, artist, title, _, _ = await get_media_info(media_path)
            await bot.send_audio(
                chat_id=message.chat.id,
                audio=media_path,
                duration=duration,
                performer=artist,
                title=title,
                caption=caption or "",
                progress=Leaves.progress_for_pyrogram,
                progress_args=progress_args,
            )
        elif media_type == "document":
            await bot.send_document(
                chat_id=message.chat.id,
                document=media_path,
                caption=caption or "",
                progress=Leaves.progress_for_pyrogram,
                progress_args=progress_args,
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
            try:
                await progress_message.edit(f"⏳ **Telegram is throttling...**\nSleeping for `{wait_msg}`.")
            except:
                pass
            await asyncio.sleep(wait_s + 1)
            continue
            
        except (Timeout, TimeoutError):
            LOGGER(__name__).warning(f"TimeoutError: Request timed out. Retrying ({retry_count}/{max_retries})")
            try:
                await progress_message.edit(f"⚠️ **Network Timeout.**\nRetrying `{retry_count}/{max_retries}`...")
            except:
                pass
            await asyncio.sleep(5)
            retry_count += 1
            continue
            
        except Exception as e:
            LOGGER(__name__).error(f"Upload failed: {e} (Attempt {retry_count}/{max_retries})")
            if retry_count < max_retries:
                try:
                    await progress_message.edit(f"⚠️ **Upload Error.**\nRetrying `{retry_count}/{max_retries-1}` in 3s...")
                except:
                    pass
                await asyncio.sleep(3)
                retry_count += 1
                continue
            else:
                try:
                    await progress_message.edit(f"❌ **Upload Failed.**\nMax retries reached. Error: {str(e)}")
                except:
                    pass
                return False
    
    return False

async def download_single_media(msg, progress_message, start_time, semaphore):
    filename = get_file_name(msg.id, msg)
    
    download_path = get_download_path(msg.id, filename)
    
    max_retries = 3
    retry_count = 1

    while retry_count <= max_retries:
        try:
            async with semaphore:
                media_path = await msg.download(
                    file_name=download_path,
                    progress=Leaves.progress_for_pyrogram,
                    progress_args=progressArgs(
                        "📥 Downloading", progress_message, start_time, filename
                    ),
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
            try:
                await progress_message.edit(f"⏳ **FloodWait:** Sleeping `{wait_msg}`...")
            except:
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

async def processMediaGroup(chat_message, bot, message, semaphore):
    media_group_messages = await chat_message.get_media_group()
    valid_media = []
    temp_paths = []
    invalid_paths = []

    start_time = time()
    progress_message = await message.reply("📥 Downloading media group...")
    LOGGER(__name__).info(
        f"Downloading media group with {len(media_group_messages)} items..."
    )

    download_tasks = []
    for msg in media_group_messages:
        if msg.photo or msg.video or msg.document or msg.audio:
            download_tasks.append(download_single_media(msg, progress_message, start_time, semaphore))

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
                await progress_message.delete()
                sent_success = True
                break
            except FloodWait as e:
                wait_s = int(getattr(e, "value", 0) or 0)
                wait_msg = get_readable_time(wait_s)
                LOGGER(__name__).warning(f"FloodWait sending group: Sleeping {wait_msg}")
                try:
                    await progress_message.edit(f"⏳ **FloodWait:** Sleeping `{wait_msg}` before sending album...")
                except:
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

            await progress_message.delete()

        for path in temp_paths + invalid_paths:
            cleanup_download(path)
        return True

    await progress_message.delete()
    await message.reply("❌ No valid media found in the media group.")
    for path in invalid_paths:
        cleanup_download(path)
    return False