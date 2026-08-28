import os
import asyncio
from time import time
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import Message
from pyrogram.errors import PeerIdInvalid, BadRequest, FloodWait, FileReferenceExpired

from config import PyroConf
from logger import LOGGER

from helpers.utils import processMediaGroup, send_media, get_progress_text
from helpers.files import get_download_path, fileSizeLimit, get_readable_file_size, get_readable_time, cleanup_download
from helpers.msg import getChatMsgID, get_file_name, get_parsed_msg, clean_caption, extract_youtube_keyboard, apply_caption_rules

RUNNING_TASKS = set()
download_semaphore = None
upload_semaphore = None
GLOBAL_CANCEL = asyncio.Event()

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

def get_running_tasks():
    return RUNNING_TASKS

async def handle_download(bot: Client, user: Client, message: Message, post_url: str, pre_fetched_msg: Message = None, progress_msg: Message = None, batch_stats: dict = None, target_chat_id: int | str = None, target_topic_id: int = None, caption_rules: list = None):
    if GLOBAL_CANCEL.is_set():
        raise asyncio.CancelledError()
        
    if target_chat_id is None:
        target_chat_id = message.chat.id
        
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
            chat_id, message_id, _ = getChatMsgID(post_url)
            chat_message = await user.get_messages(chat_id=chat_id, message_ids=message_id)

        if not chat_message or chat_message.empty:
             if not batch_stats: await message.reply("❌ <b>Message not found or inaccessible.</b>")
             return

        if chat_message.document or chat_message.video or chat_message.audio:
            file_size = chat_message.document.file_size if chat_message.document else chat_message.video.file_size if chat_message.video else chat_message.audio.file_size
            if not await fileSizeLimit(file_size, message, "download", user.me.is_premium):
                return

        parsed_caption = await get_parsed_msg(chat_message)
        parsed_caption = clean_caption(parsed_caption)
        if caption_rules:
            parsed_caption = apply_caption_rules(parsed_caption, caption_rules)
            
        safe_keyboard = extract_youtube_keyboard(chat_message.reply_markup)
        has_downloadable_media = bool(chat_message.document or chat_message.video or chat_message.audio or chat_message.photo or chat_message.animation or chat_message.voice or chat_message.video_note or chat_message.sticker)

        if chat_message.media_group_id:
            if progress_msg and batch_stats:
                batch_stats["processed"] += 1
                try: await progress_msg.edit(get_progress_text("Media Group", "Multiple Files", batch_stats))
                except Exception: pass
            elif not progress_msg:
                progress_msg = await message.reply(get_progress_text("Media Group", "Multiple Files"))

            if not await processMediaGroup(chat_message, user, bot, message, dl_sem, progress_msg, batch_stats, target_chat_id, target_topic_id, caption_rules):
                if progress_msg:
                    try:
                        await progress_msg.edit("❌ <b>Failed to process Media Group</b>")
                        await asyncio.sleep(2)
                    except Exception: pass
            
            if not batch_stats and progress_msg:
                try: await progress_msg.delete()
                except Exception: pass
            return

        elif has_downloadable_media:
            filename = get_file_name(message_id, chat_message)
            download_path = await get_download_path(message_id, filename)

            media_obj = chat_message.document or chat_message.video or chat_message.audio or chat_message.photo or chat_message.animation or chat_message.voice or chat_message.video_note or chat_message.sticker
            pre_file_size = getattr(media_obj, "file_size", 0) if media_obj else 0
            file_size_str = get_readable_file_size(pre_file_size)

            async with dl_sem:
                if GLOBAL_CANCEL.is_set():
                    raise asyncio.CancelledError()
                    
                LOGGER(__name__).info(f"Downloading media: {filename} (Size: {file_size_str})")
                
                if progress_msg and batch_stats:
                    batch_stats["processed"] += 1
                    try: await progress_msg.edit(get_progress_text(filename, file_size_str, batch_stats))
                    except Exception: pass
                elif not progress_msg:
                    progress_msg = await message.reply(get_progress_text(filename, file_size_str))
                
                try:
                    media_path = await chat_message.download(file_name=download_path)
                except FloodWait as e:
                    wait_s = int(getattr(e, "value", 0) or 0)
                    await asyncio.sleep(wait_s + 1)
                    media_path = await chat_message.download(file_name=download_path)
                except FileReferenceExpired:
                    raise

            if not media_path or not await asyncio.to_thread(os.path.exists, media_path): return
            
            actual_size = await asyncio.to_thread(os.path.getsize, media_path)
            
            if pre_file_size > 0 and actual_size < pre_file_size:
                LOGGER(__name__).warning(f"File size mismatch. The file reference might have expired.")
                raise FileReferenceExpired()
            elif actual_size == 0:
                return
            
            media_type = "photo" if chat_message.photo else "video" if chat_message.video else "audio" if chat_message.audio else "document"
            
            async with up_sem:
                if GLOBAL_CANCEL.is_set():
                    raise asyncio.CancelledError()
                    
                upload_success = await send_media(
                    bot, message, media_path, media_type, parsed_caption, progress_msg, batch_stats, target_chat_id, target_topic_id, reply_markup=safe_keyboard, message_id=message_id
                )

            if upload_success:
                if not batch_stats and progress_msg:
                    try: await progress_msg.delete()
                    except Exception: pass
                LOGGER(__name__).info(f"Finished Processing: {post_url}")

        elif chat_message.text:
            if batch_stats:
                batch_stats["processed"] += 1
            
            parsed_text = await get_parsed_msg(chat_message)
            parsed_text = clean_caption(parsed_text)
            
            try:
                await bot.send_message(chat_id=target_chat_id, message_thread_id=target_topic_id, text=parsed_text, reply_markup=safe_keyboard, disable_web_page_preview=True, parse_mode=ParseMode.HTML)
            except BadRequest:
                await bot.send_message(chat_id=target_chat_id, message_thread_id=target_topic_id, text=chat_message.text.html or "", reply_markup=safe_keyboard, disable_web_page_preview=True, parse_mode=ParseMode.HTML)
                
            LOGGER(__name__).info(f"Finished Processing: {post_url}")
            
    except FileReferenceExpired:
        raise
    except (PeerIdInvalid, BadRequest, KeyError) as e:
        if batch_stats:
            raise e
        await message.reply("<b>Make sure the user client is part of the chat.</b>")
    except FloodWait as e:
        wait_s = int(getattr(e, "value", 0) or 0)
        if wait_s > 0: await asyncio.sleep(wait_s + 1)
    except Exception as e:
        if batch_stats:
            raise e
        await message.reply(f"**❌ {str(e)}**")
    finally:
        if media_path: await cleanup_download(media_path)
        elapsed = time() - task_start_time
        if elapsed < 2.0: await asyncio.sleep(2.0 - elapsed)

async def execute_batch(bot: Client, user: Client, original_msg: Message, job: dict):
    start_chat, target_chat = job["start_chat"], job["target_chat"]
    target_topic = job.get("target_topic")
    start_id, end_id = job["start_id"], job["end_id"]
    filters_selected = job.get("filter_type", ["all"])
    prefix = job.get("prefix", "")
    caption_rules = job.get("caption_rules", [])

    try: await user.get_chat(start_chat)
    except Exception: pass

    loading = await original_msg.reply(f"📥 <b>Started Batch Processing...</b>")
    LOGGER(__name__).info(f"Batch Process Started | Range: {start_id} to {end_id}")
    try: await loading.pin(disable_notification=True, both_sides=True)
    except Exception: pass

    downloaded = skipped = failed = 0
    processed_media_groups = set()
    
    batch_stats = {"total": (end_id - start_id) + 1, "processed": 0}

    current_id = start_id
    
    while current_id <= end_id:
        if GLOBAL_CANCEL.is_set():
            raise asyncio.CancelledError()
            
        chunk_end = min(current_id + 199, end_id)
        chunk_ids = list(range(current_id, chunk_end + 1))
        
        try:
            messages = await user.get_messages(chat_id=start_chat, message_ids=chunk_ids)
            if not isinstance(messages, list): messages = [messages]
        except Exception:
            failed += len(chunk_ids)
            batch_stats["processed"] += len(chunk_ids)
            current_id = chunk_end + 1
            continue
            
        ref_expired = False

        for chat_msg in messages:
            if GLOBAL_CANCEL.is_set():
                raise asyncio.CancelledError()
                
            if not chat_msg or chat_msg.empty:
                skipped += 1
                batch_stats["processed"] += 1
                continue
            
            if chat_msg.media_group_id:
                if chat_msg.media_group_id in processed_media_groups:
                    skipped += 1
                    batch_stats["processed"] += 1
                    continue
                processed_media_groups.add(chat_msg.media_group_id)

            if not (chat_msg.media_group_id or chat_msg.media or chat_msg.text or chat_msg.caption):
                skipped += 1
                batch_stats["processed"] += 1
                continue
                
            if "all" not in filters_selected:
                if not any([
                    ("video" in filters_selected and chat_msg.video),
                    ("doc" in filters_selected and chat_msg.document),
                    ("audio" in filters_selected and chat_msg.audio),
                    ("photo" in filters_selected and chat_msg.photo)
                ]):
                    skipped += 1
                    batch_stats["processed"] += 1
                    continue

            url = f"{prefix}/{chat_msg.id}"
            task = track_task(handle_download(bot, user, original_msg, url, chat_msg, loading, batch_stats, target_chat, target_topic, caption_rules))
            
            try:
                await task
                downloaded += 1
            except asyncio.CancelledError:
                try: await loading.unpin()
                except Exception: pass
                await loading.delete()
                return await original_msg.reply(
                    "<blockquote>❗ <b>Batch Process Canceled!</b></blockquote>\n"
                    "━━━━━━━━━━━━━━━━━━━\n"
                    f"📥 <b>Downloaded</b>: {downloaded} post(s)\n"
                    f"⏭️ <b>Skipped</b>: {skipped} (filtered)\n"
                    f"❌ <b>Failed</b>: {failed} error(s)",
                    parse_mode=ParseMode.HTML
                )
            except FileReferenceExpired:
                ref_expired = True
                current_id = chat_msg.id
                LOGGER(__name__).info(f"File reference expired at ID {current_id}. Refreshing chunk dynamically.")
                await asyncio.sleep(2)
                break
            except Exception as e:
                if "FileReferenceExpired" in str(e):
                    ref_expired = True
                    current_id = chat_msg.id
                    LOGGER(__name__).info(f"File reference expired at ID {current_id}. Refreshing chunk dynamically.")
                    await asyncio.sleep(2)
                    break
                failed += 1

            await asyncio.sleep(PyroConf.FLOOD_WAIT_DELAY)

        if ref_expired:
            continue

        current_id = chunk_end + 1

    try: await loading.unpin()
    except Exception: pass
    await loading.delete()
    LOGGER(__name__).info(f"Batch Process Completed | Total: {downloaded} | Skipped: {skipped} | Failed: {failed}")
    
    await original_msg.reply(
        "<blockquote>✅ <b>Batch Process Completed!</b></blockquote>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📥 <b>Total</b>: {downloaded} post(s)\n"
        f"⏭️ <b>Skipped</b>: {skipped} (filtered)\n"
        f"❌ <b>Failed</b>: {failed} error(s)",
        parse_mode=ParseMode.HTML
    )

async def execute_autoforward(bot: Client, user: Client, original_msg: Message, job: dict):
    start_chat, target_chat = job["start_chat"], job["target_chat"]
    target_topic = job.get("target_topic")
    start_id, end_id = job["start_id"], job["end_id"]
    caption_rules = job.get("caption_rules", [])
    
    try:
        chat_info = await user.get_chat(start_chat)
        if getattr(chat_info, "has_protected_content", False):
            return await original_msg.reply("❌ <b>Source chat is restricted!</b>\n`/autoforward` only works for unrestricted chats. Please use `/batch` instead.")
    except Exception: pass 
    
    loading = await original_msg.reply(f"📥 <b>Started Auto-Forwarding...</b>")
    LOGGER(__name__).info(f"Auto-Forward Process Started | Range: {start_id} to {end_id}")
    copied = skipped = failed = 0
    all_ids = list(range(start_id, end_id + 1))
    
    for i in range(0, len(all_ids), 200):
        if GLOBAL_CANCEL.is_set():
            break
            
        chunk_ids = all_ids[i:i + 200]
        try:
            messages = await user.get_messages(chat_id=start_chat, message_ids=chunk_ids)
            if not isinstance(messages, list): messages = [messages]
        except Exception:
            failed += len(chunk_ids)
            continue
            
        for chat_msg in messages:
            if GLOBAL_CANCEL.is_set():
                break
                
            if not chat_msg or chat_msg.empty:
                skipped += 1
                continue
                
            try:
                raw_text = chat_msg.caption or chat_msg.text or ""
                
                if raw_text:
                    custom_caption = await get_parsed_msg(chat_msg)
                    custom_caption = clean_caption(custom_caption)
                    custom_caption = apply_caption_rules(custom_caption, caption_rules)
                else:
                    custom_caption = ""
                
                kwargs = {
                    "chat_id": target_chat, 
                    "from_chat_id": start_chat, 
                    "message_id": chat_msg.id,
                    "message_thread_id": target_topic
                }
                
                if custom_caption: 
                    kwargs["caption"] = custom_caption
                    kwargs["parse_mode"] = ParseMode.HTML
                
                await user.copy_message(**kwargs)
                copied += 1
                await asyncio.sleep(1.5) 
            except FloodWait as e:
                wait_s = int(getattr(e, "value", 0) or 0)
                await asyncio.sleep(wait_s + 1)
                failed += 1 
            except Exception as e:
                LOGGER(__name__).error(f"Auto-forward failed for {chat_msg.id}: {e}")
                failed += 1
                
        await asyncio.sleep(PyroConf.FLOOD_WAIT_DELAY) 
        
    await loading.delete()
    LOGGER(__name__).info(f"Auto-Forward Completed | Total: {copied} | Skipped: {skipped} | Failed: {failed}")
    await original_msg.reply(
        "<blockquote>✅ <b>Auto-Forward Completed!</b></blockquote>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📥 <b>Total</b>: {copied} post(s)\n"
        f"⏭️ <b>Skipped</b>: {skipped}\n"
        f"❌ <b>Failed</b>: {failed}",
        parse_mode=ParseMode.HTML
    )