import os
import shutil
import psutil
import asyncio
import re
from time import time
from pyrogram.enums import ParseMode
from pyrogram import Client, compose, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import PyroConf
from logger import LOGGER

from helpers.files import get_readable_file_size, get_readable_time
from helpers.msg import getChatMsgID, get_parsed_msg, apply_caption_rules
from helpers.jobs import execute_batch, execute_autoforward, handle_download, track_task, get_running_tasks, GLOBAL_CANCEL
from helpers.keyboards import get_start_keyboard, get_caption_keyboard, get_filter_keyboard

bot = Client(
    "media_bot",
    api_id=PyroConf.API_ID,
    api_hash=PyroConf.API_HASH,
    bot_token=PyroConf.BOT_TOKEN,
    workers=100,
    parse_mode=ParseMode.HTML,
    max_concurrent_transmissions=PyroConf.MAX_CONCURRENT_TRANSMISSIONS, 
    sleep_threshold=60,
)

user = Client(
    "user_session",
    workers=100,
    session_string=PyroConf.SESSION_STRING,
    max_concurrent_transmissions=PyroConf.MAX_CONCURRENT_TRANSMISSIONS,
    sleep_threshold=60,
)

BATCH_JOBS = {}
WAITING_FOR_DEST = {}
WAITING_FOR_CAPTION_RULE = {}
LINK_CACHE = {} 
FILTER_STATE = {}

async def trigger_caption_setup(bot: Client, user: Client, message: Message, job: dict, requester_id: int = None):
    sample_caption = ""
    for msg_id in range(job["start_id"], min(job["start_id"] + 5, job["end_id"] + 1)):
        try:
            msg_obj = await user.get_messages(chat_id=job["start_chat"], message_ids=msg_id)
            if msg_obj and not getattr(msg_obj, "empty", True):
                raw_text = msg_obj.caption or msg_obj.text
                if raw_text and len(raw_text.strip()) > 50 and '\n' in raw_text:
                    sample_caption = await get_parsed_msg(msg_obj)
                    break
        except Exception:
            continue

    job["caption_rules"] = []
    
    if sample_caption:
        user_id = requester_id or (message.from_user.id if hasattr(message, "from_user") and message.from_user else message.chat.id)
        job["sample_caption"] = sample_caption 
        WAITING_FOR_CAPTION_RULE[user_id] = job
        job["original_message_id"] = message.id 
        
        preview_caption = apply_caption_rules(sample_caption, job["caption_rules"])
        display_cap = preview_caption if preview_caption else "[Caption is empty]"
        
        text = (
            f"<b>Caption Preview:</b>\n\n<code>{display_cap}</code>\n\n"
            "🔄 To clean up a caption, reply to this message with the exact text you'd like to remove!\n\n"
            f"<blockquote>🎯 <b>Active Rules:</b> 0 applied</blockquote>"
        )
        
        msg = await message.reply(text, reply_markup=get_caption_keyboard(message.id), parse_mode=ParseMode.HTML)
        job["menu_message_id"] = msg.id
    else:
        job["caption_rules"] = ["keep"]
        if job["job_type"] == "batch":
            await track_task(execute_batch(bot, user, job["original_message"], job))
        else:
            await track_task(execute_autoforward(bot, user, job["original_message"], job))

@bot.on_message(filters.command("start") & filters.private)
async def start(_, message: Message):
    welcome_text = (
        "🤖 <b>Welcome to Save Restricted Bot!</b>\n\n"
        "I can help you download media from restricted channels and set up auto-forwarding. 🚀\n\n"
        "⚙️ <b>How to use:</b>\n"
        "• Just paste any Telegram post link directly in this chat to get started.\n"
        "• Use <code>/help</code> to see advanced commands.\n\n"
        "⚠️ Make sure your user client is already a member of the target chat."
    )
    await message.reply(welcome_text, disable_web_page_preview=True, parse_mode=ParseMode.HTML)

@bot.on_message(filters.command("help") & filters.private)
async def help_command(_, message: Message):
    help_text = (
        "💡 <b>Bot Commands</b>\n\n"
        "📥 <b>Single Posts</b>\n"
        "• Paste any restricted post link directly in the chat.\n\n"
        "📦 <b>Batch Downloads</b>\n"
        "• Type <code>/batch &lt;start_url&gt;</code> to initiate a batch download.\n\n"
        "⚡ <b>Auto-Forwarding</b>\n"
        "• Type <code>/autoforward &lt;from_chat_link&gt;</code> to initiate autoforward process.\n\n"
        "⚙️ <b>System Controls</b>\n"
        "• <code>/stop</code> - Cancel active tasks\n"
        "• <code>/stats</code> - Check bot performance\n"
        "• <code>/logs</code> - View system logs\n\n"
        "🔒 <b>Requirement:</b> You must be a member of the source chat."
    )
    await message.reply(help_text, disable_web_page_preview=True, parse_mode=ParseMode.HTML)

@bot.on_message(filters.command("batch") & filters.private)
async def batch_command(bot: Client, message: Message):
    args = message.text.split()
    if len(args) < 2 or not args[1].startswith("https://t.me/"):
        return await message.reply("🚀 <b>Batch Download</b>\n\n<blockquote><code>/batch start_link</code></blockquote>", parse_mode=ParseMode.HTML)
    LINK_CACHE[message.from_user.id] = args[1]
    await message.reply("🔗 Send the <b>ending post link</b> to establish the range.", parse_mode=ParseMode.HTML)
    WAITING_FOR_DEST[message.from_user.id] = {"action": "wait_batch_end"}

@bot.on_callback_query(filters.regex(r"^menu_(single|batch|auto)$"))
async def main_menu_callback(bot: Client, callback_query: CallbackQuery):
    action = callback_query.matches[0].group(1)
    user_id = callback_query.from_user.id
    
    if user_id not in LINK_CACHE:
        return await callback_query.answer("Session expired. Please send the link again.", show_alert=True)
    
    link = LINK_CACHE[user_id]
    await callback_query.message.delete()
    
    if action == "single":
        await track_task(handle_download(bot, user, callback_query.message, link))
        LINK_CACHE.pop(user_id, None)
        
    elif action == "batch":
        WAITING_FOR_DEST[user_id] = {"action": "wait_batch_end"}
        await callback_query.message.reply("🔗 Send the <b>ending post link</b> to establish the range.", parse_mode=ParseMode.HTML)
        
    elif action == "auto":
        WAITING_FOR_DEST[user_id] = {"action": "wait_auto_end"}
        await callback_query.message.reply("🔗 Send the <b>ending post link</b> to establish the range.", parse_mode=ParseMode.HTML)

@bot.on_callback_query(filters.regex(r"^filter_([a-z]+)_(\d+)$"))
async def filter_menu_callback(bot: Client, callback_query: CallbackQuery):
    selection = callback_query.matches[0].group(1)
    msg_id = int(callback_query.matches[0].group(2))
    
    if msg_id not in BATCH_JOBS:
        return await callback_query.answer("Session expired.", show_alert=True)
        
    job = BATCH_JOBS[msg_id]
    current_filters = FILTER_STATE.get(msg_id, [])
    
    if selection == "all":
        job["filter_type"] = ["all"]
        FILTER_STATE.pop(msg_id, None)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Bot Chat", callback_data=f"batch_bot_{msg_id}"),
             InlineKeyboardButton("Channel/Topic", callback_data=f"batch_chan_{msg_id}")]
        ])
        return await callback_query.message.edit_text("Where do you want to forward media?", reply_markup=keyboard)
        
    if selection == "done":
        job["filter_type"] = current_filters if current_filters else ["all"]
        FILTER_STATE.pop(msg_id, None)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Bot Chat", callback_data=f"batch_bot_{msg_id}"),
             InlineKeyboardButton("Channel/Topic", callback_data=f"batch_chan_{msg_id}")]
        ])
        return await callback_query.message.edit_text("Where do you want to forward media?", reply_markup=keyboard)
        
    if "all" in current_filters: 
        current_filters.remove("all")
        
    if selection in current_filters:
        current_filters.remove(selection)
    else:
        current_filters.append(selection)
        
    if len(current_filters) >= 4:
        current_filters = []
            
    FILTER_STATE[msg_id] = current_filters
    await callback_query.message.edit_reply_markup(reply_markup=get_filter_keyboard(current_filters, msg_id))

@bot.on_callback_query(filters.regex(r"^batch_(bot|chan)_(\d+)$"))
async def batch_destination_callback(bot: Client, callback_query: CallbackQuery):
    action, msg_id = callback_query.matches[0].groups()
    msg_id = int(msg_id)

    if msg_id not in BATCH_JOBS:
        return await callback_query.answer("Batch process has expired.", show_alert=True)

    job = BATCH_JOBS.pop(msg_id)
    await callback_query.message.delete()

    if action == "bot":
        job["target_chat"] = callback_query.message.chat.id
        job["target_topic"] = None
        await trigger_caption_setup(bot, user, callback_query.message, job, requester_id=callback_query.from_user.id)
    elif action == "chan":
        WAITING_FOR_DEST[callback_query.from_user.id] = job
        await job["original_message"].reply("🔗 Send a post link from the target channel/topic.")

@bot.on_message(filters.command(["autoforward"]) & filters.private)
async def auto_forward_init(bot: Client, message: Message):
    args = message.text.split()
    if len(args) < 2 or not args[1].startswith("https://t.me/"):
        return await message.reply("🚀 <b>Auto-Forward</b>\n\n<blockquote><code>/autoforward &lt;start_link&gt;</code></blockquote>", parse_mode=ParseMode.HTML)
    LINK_CACHE[message.from_user.id] = args[1]
    WAITING_FOR_DEST[message.from_user.id] = {"action": "wait_auto_end"}
    await message.reply("🔗 Send the <b>ending post link</b> to establish the range.", parse_mode=ParseMode.HTML)

@bot.on_callback_query(filters.regex(r"^cap_(rmlast|done)_(\d+)$"))
async def caption_rule_callback(bot: Client, callback_query: CallbackQuery):
    action, msg_id = callback_query.matches[0].groups()
    user_id = callback_query.from_user.id
    
    if user_id not in WAITING_FOR_CAPTION_RULE:
        return await callback_query.answer("Session expired or invalid.", show_alert=True)
    
    job = WAITING_FOR_CAPTION_RULE[user_id]
    
    if action == "done":
        WAITING_FOR_CAPTION_RULE.pop(user_id)
        await callback_query.message.delete()
        if job["job_type"] == "batch":
            await track_task(execute_batch(bot, user, job["original_message"], job))
        else:
            await track_task(execute_autoforward(bot, user, job["original_message"], job))
        return
        
    if action == "rmlast":
        job["caption_rules"].append("rm_last")
        await callback_query.answer("✅ Rule Added!", show_alert=False)
    
    rules_count = len(job["caption_rules"])
    preview_caption = apply_caption_rules(job['sample_caption'], job["caption_rules"])
    display_cap = preview_caption if preview_caption else "[Caption is empty]"
    
    text = (
        f"<b>Caption Preview:</b>\n\n<code>{display_cap}</code>\n\n"
        "🔄 To clean up a caption, reply to this message with the exact text you'd like to remove!\n\n"
        f"<blockquote>🎯 <b>Active Rules:</b> {rules_count} applied</blockquote>"
    )
    
    try:
        await callback_query.message.edit_text(text, reply_markup=get_caption_keyboard(job['original_message_id']), parse_mode=ParseMode.HTML)
    except Exception: pass

@bot.on_message(filters.private & filters.text & ~filters.command(["start", "help", "stats", "logs", "stop", "autoforward", "batch"]))
async def handle_any_message(bot: Client, message: Message):
    user_id = message.from_user.id

    if user_id in WAITING_FOR_DEST:
        job = WAITING_FOR_DEST.pop(user_id)
        
        if "action" in job:
            start_link = LINK_CACHE.get(user_id)
            end_link = message.text
            
            try:
                start_chat, start_id, _ = getChatMsgID(start_link)
                end_chat, end_id, _ = getChatMsgID(end_link)
            except Exception as e:
                return await message.reply(f"<b>❌ Error parsing links:\n{e}</b>", parse_mode=ParseMode.HTML)
                
            if start_chat != end_chat: return await message.reply("<b>❌ Both links must be from the same channel.</b>", parse_mode=ParseMode.HTML)
            if start_id > end_id: return await message.reply("<b>❌ Invalid range.</b>", parse_mode=ParseMode.HTML)
            
            if job["action"] == "wait_batch_end":
                BATCH_JOBS[message.id] = {
                    "start_chat": start_chat,
                    "start_id": start_id,
                    "end_id": end_id,
                    "prefix": start_link.rsplit("/", 1)[0],
                    "job_type": "batch",
                    "original_message": message
                }
                FILTER_STATE[message.id] = []
                await message.reply("🎬 <b>Select media types to download:</b>", reply_markup=get_filter_keyboard([], message.id), parse_mode=ParseMode.HTML)
                
            elif job["action"] == "wait_auto_end":
                auto_job = {
                    "start_chat": start_chat,
                    "start_id": start_id,
                    "end_id": end_id,
                    "job_type": "autoforward",
                    "original_message": message
                }
                WAITING_FOR_DEST[message.from_user.id] = auto_job
                await message.reply("🔗 Send a post link from the target channel/topic.")
            return

        try:
            target_chat_id, target_msg_id, target_topic_id = getChatMsgID(message.text)
            job["target_chat"] = target_chat_id
            job["target_topic"] = target_topic_id 
            await trigger_caption_setup(bot, user, message, job)
        except Exception as e:
            await message.reply(f"<b>❌ Error parsing target link:\n{e}</b>", parse_mode=ParseMode.HTML)
        return
    
    if user_id in WAITING_FOR_CAPTION_RULE:
        job = WAITING_FOR_CAPTION_RULE[user_id]
        
        new_rule = f"remove_text:{message.text}"
        if new_rule in job["caption_rules"]:
            await message.reply("⚠️ This text is already in the removal list!")
            return
            
        job["caption_rules"].append(new_rule)

        rules_count = len(job["caption_rules"])
        preview_caption = apply_caption_rules(job['sample_caption'], job["caption_rules"])
        display_cap = preview_caption if preview_caption else "[Caption is empty]"
        
        text = (
            f"<b>Caption Preview:</b>\n\n<code>{display_cap}</code>\n\n"
            "🔄 To clean up a caption, reply to this message with the exact text you'd like to remove!\n\n"
            f"<blockquote>🎯 <b>Active Rules:</b> {rules_count} applied</blockquote>"
        )
        
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id, 
                message_id=job["menu_message_id"], 
                text=text, 
                reply_markup=get_caption_keyboard(job['original_message_id']),
                parse_mode=ParseMode.HTML
            )
        except Exception: pass
        
        await message.reply("✅ <b>Text rule added.</b> You can add more text to remove, or click <b>Start</b> on the menu.", parse_mode=ParseMode.HTML)
        return

    if re.search(r"t\.me\/", message.text):
        LINK_CACHE[user_id] = message.text
        await message.reply("⚙️ <b>How do you want to proceed?</b>", reply_markup=get_start_keyboard(), parse_mode=ParseMode.HTML)

@bot.on_message(filters.command("stats") & filters.private)
async def stats(_, message: Message):
    currentTime = get_readable_time(time() - PyroConf.BOT_START_TIME)
    def get_sys_stats():
        t, u, f = shutil.disk_usage(".")
        return (
            get_readable_file_size(t), get_readable_file_size(f),
            get_readable_file_size(psutil.net_io_counters().bytes_sent),
            get_readable_file_size(psutil.net_io_counters().bytes_recv),
            psutil.cpu_percent(interval=0.5), psutil.virtual_memory().percent,
            psutil.disk_usage("/").percent, round(psutil.Process(os.getpid()).memory_info()[0] / 1024**2)
        )

    total, free, sent, recv, cpuUsage, memory, disk, proc_mem = await asyncio.to_thread(get_sys_stats)
    
    await message.reply(
        "<b>Bot's Live and Running Successfully.</b>\n\n"
        f"<b>Uptime:</b> {currentTime} | <b>Mem:</b> {proc_mem} MiB\n"
        f"<b>Free Disk:</b> {free} of {total}\n"
        f"<b>Traffic:</b> 🔼 {sent} | 🔽 {recv}\n"
        f"<b>System:</b> CPU: {cpuUsage}% | RAM: {memory}% | DISK: {disk}%",
        parse_mode=ParseMode.HTML
    )

@bot.on_message(filters.command("logs") & filters.private)
async def logs(_, message: Message):
    if os.path.exists("logs.txt"): await message.reply_document(document="logs.txt", caption="<b>Logs</b>", parse_mode=ParseMode.HTML)
    else: await message.reply("<b>Not exists</b>", parse_mode=ParseMode.HTML)

@bot.on_message(filters.command("stop") & filters.private)
async def cancel_all_tasks(_, message: Message):
    GLOBAL_CANCEL.set()
    cancelled = len(list(get_running_tasks()))
    await message.reply(f"<b>Initiated shutdown for {cancelled} running task(s).</b>", parse_mode=ParseMode.HTML)
    await asyncio.sleep(2)
    GLOBAL_CANCEL.clear()

if __name__ == "__main__":
    if os.path.exists("downloads"):
        try:
            shutil.rmtree("downloads")
        except Exception as e:
            LOGGER(__name__).error(f"Failed to clean downloads directory: {e}")
    os.makedirs("downloads", exist_ok=True)

    LOGGER(__name__).info("Bot Started!")
    try: compose([bot, user])
    except KeyboardInterrupt: pass
    except Exception as e: LOGGER(__name__).error(f"Bot Crashed: {e}")
    finally: LOGGER(__name__).info("Bot Stopped.")