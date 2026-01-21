import re
from pyrogram.parser import Parser
from pyrogram.utils import get_channel_id


async def get_parsed_msg(text, entities):
    return Parser.unparse(text, entities or [], is_html=False)
    
def getChatMsgID(link: str):
    if "?" in link:
        link = link.split("?")[0]

    linkps = link.split("/")
    chat_id, message_thread_id, message_id = None, None, None
    
    try:
        if len(linkps) == 7 and linkps[3] == "c":
            chat_id = get_channel_id(int(linkps[4]))
            message_thread_id = int(linkps[5])
            message_id = int(linkps[6])
        elif len(linkps) == 6:
            if linkps[3] == "c":
                chat_id = get_channel_id(int(linkps[4]))
                message_id = int(linkps[5])
            else:
                chat_id = linkps[3]
                message_thread_id = int(linkps[4])
                message_id = int(linkps[5])
        elif len(linkps) == 5:
            chat_id = linkps[3]
            if chat_id == "m":
                raise ValueError("Invalid ClientType used to parse this message link")
            message_id = int(linkps[4])
    except (ValueError, TypeError):
        raise ValueError("Invalid post URL. Must end with a numeric ID.")

    if not chat_id or not message_id:
        raise ValueError("Please send a valid Telegram post URL.")

    return chat_id, message_id

def get_file_name(message_id: int, chat_message) -> str:
    def clean_name(name):
        if not name:
            return ""

        name = re.sub(r'^\d+_', '', name)

        name = name.replace('_', ' ')

        match = re.match(r'^(\d+)\s*([a-zA-Z])', name)
        if match:
            prefix_num = match.group(1)
            rest_of_text = name[len(match.group(0))-1:] 
            name = f"{prefix_num}) {rest_of_text}"

        if re.match(r'^\d+ ', name) and not name.startswith(f"{name.split(' ')[0]})"):
            parts = name.split(' ', 1)
            if len(parts) > 1:
                name = f"{parts[0]}) {parts[1]}"
            
        return name

    filename = ""

    if chat_message.document:
        filename = chat_message.document.file_name
    elif chat_message.video:
        filename = chat_message.video.file_name or f"{message_id}.mp4"
    elif chat_message.audio:
        filename = chat_message.audio.file_name or f"{message_id}.mp3"
    elif chat_message.voice:
        filename = f"{message_id}.ogg"
    elif chat_message.video_note:
        filename = f"{message_id}.mp4"
    elif chat_message.animation:
        filename = chat_message.animation.file_name or f"{message_id}.gif"
    elif chat_message.sticker:
        if chat_message.sticker.is_animated:
            filename = f"{message_id}.tgs"
        elif chat_message.sticker.is_video:
            filename = f"{message_id}.webm"
        else:
            filename = f"{message_id}.webp"
    elif chat_message.photo:
        filename = f"{message_id}.jpg"
    
    final_name = clean_name(filename)

    if not final_name or final_name.strip() == "":
        return str(message_id)

    return final_name