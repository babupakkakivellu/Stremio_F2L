from pyrogram import filters, Client, enums
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait
from Backend.config import Telegram
from Backend.helper.encrypt import encode_string
from Backend.logger import LOGGER
from datetime import datetime, timedelta
from asyncio import sleep as asleep
import re
import urllib.parse

# In-memory cache to store user file message mapping
# Structure: {user_id: {user_msg_id: {"dump_chat_id": int, "dump_msg_id": int, "file_name": str, "timestamp": datetime}}}
file_cache = {}

# Cache cleanup settings
CACHE_TTL_HOURS = 1


def sanitize_filename(filename):
    """Make filename URL-safe by replacing spaces and special characters"""
    # Get file extension
    name_parts = filename.rsplit('.', 1)
    if len(name_parts) == 2:
        name, ext = name_parts
    else:
        name = filename
        ext = ''
    
    # Replace spaces with underscores
    name = name.replace(' ', '_')
    
    # Remove or replace special characters, keep alphanumeric, underscore, hyphen, dot
    name = re.sub(r'[^a-zA-Z0-9._-]', '', name)
    
    # Remove multiple consecutive underscores
    name = re.sub(r'_+', '_', name)
    
    # Remove leading/trailing underscores
    name = name.strip('_')
    
    # Reconstruct filename with extension
    if ext:
        return f"{name}.{ext}"
    return name


def clean_expired_cache():
    """Remove expired entries from cache"""
    current_time = datetime.utcnow()
    users_to_remove = []
    
    for user_id, messages in file_cache.items():
        msg_ids_to_remove = []
        for msg_id, data in messages.items():
            if current_time - data["timestamp"] > timedelta(hours=CACHE_TTL_HOURS):
                msg_ids_to_remove.append(msg_id)
        
        for msg_id in msg_ids_to_remove:
            del messages[msg_id]
        
        if not messages:
            users_to_remove.append(user_id)
    
    for user_id in users_to_remove:
        del file_cache[user_id]


@Client.on_message(filters.private & (filters.document | filters.video) & ~filters.command(['link', 'start', 'log', 'set', 'restart']))
async def file_to_link_handler(client: Client, message: Message):
    """
    Handle files sent to the bot in private messages.
    Forward them to FILE_TO_LINK_DUMP channel and store mapping.
    """
    try:
        # Check if FILE_TO_LINK_DUMP is configured
        if not Telegram.FILE_TO_LINK_DUMP:
            await message.reply_text(
                "⚠️ **File-to-Link feature is not configured.**\n\n"
                "Please contact the bot administrator.",
                quote=True
            )
            return
        
        # Clean expired cache entries
        clean_expired_cache()
        
        # Get file details
        file = message.video or message.document
        file_name = file.file_name or f"file_{message.id}"
        file_size = file.file_size
        
        # Check if it's a video file
        is_video = message.video or (message.document and message.document.mime_type and message.document.mime_type.startswith("video/"))
        
        if not is_video:
            await message.reply_text(
                "⚠️ **Only video files are supported.**\n\n"
                "Please send a video file (MP4, MKV, AVI, etc.)",
                quote=True
            )
            return
        
        try:
            # Forward file to FILE_TO_LINK_DUMP channel silently
            forwarded_msg = await message.forward(Telegram.FILE_TO_LINK_DUMP)
            
            # Sanitize filename for URL
            url_safe_filename = sanitize_filename(file_name)
            
            # Store in cache - map to original message for /link reply
            user_id = message.from_user.id
            if user_id not in file_cache:
                file_cache[user_id] = {}
            
            file_cache[user_id][message.id] = {
                "dump_chat_id": str(Telegram.FILE_TO_LINK_DUMP).replace("-100", ""),
                "dump_msg_id": forwarded_msg.id,
                "file_name": url_safe_filename,
                "original_name": file_name,
                "file_size": file_size,
                "file_size_str": get_readable_size(file_size),
                "timestamp": datetime.utcnow()
            }
            
            LOGGER.info(f"File uploaded silently by user {user_id}: {file_name}")
            
        except Exception as e:
            LOGGER.error(f"Error forwarding file to dump channel: {e}")
            await message.reply_text(
                "❌ **Failed to upload file.**\n\n"
                f"Error: {str(e)}\n\n"
                "Please try again or contact the administrator.",
                quote=True
            )
    
    except FloodWait as e:
        LOGGER.info(f"Sleeping for {str(e.value)}s due to FloodWait")
        await asleep(e.value)
        await message.reply_text(
            f"⚠️ **Rate limit hit. Please wait {str(e.value)} seconds and try again.**",
            quote=True
        )
    
    except Exception as e:
        LOGGER.error(f"Error in file_to_link_handler: {e}")
        await message.reply_text(
            f"❌ **An error occurred:**\n`{str(e)}`",
            quote=True
        )


@Client.on_message(filters.private & filters.command('link'))
async def link_command_handler(client: Client, message: Message):
    """
    Handle /link command to generate download link.
    Must be a reply to a file message.
    """
    try:
        # Check if FILE_TO_LINK_DUMP is configured
        if not Telegram.FILE_TO_LINK_DUMP:
            await message.reply_text(
                "⚠️ **File-to-Link feature is not configured.**\n\n"
                "Please contact the bot administrator.",
                quote=True
            )
            return
        
        # Clean expired cache entries
        clean_expired_cache()
        
        # Check if this is a reply to a message
        if not message.reply_to_message:
            await message.reply_text(
                "⚠️ **Please reply to a file message with this command.**\n\n"
                "Usage: Send a file to the bot, then reply to that file with `/link`",
                quote=True
            )
            return
        
        replied_msg = message.reply_to_message
        user_id = message.from_user.id
        
        # Check if file info exists in cache
        if user_id not in file_cache or replied_msg.id not in file_cache[user_id]:
            await message.reply_text(
                "⚠️ **File not found or link expired.**\n\n"
                f"Links expire after {CACHE_TTL_HOURS} hour(s). Please upload the file again.",
                quote=True
            )
            return
        
        # Get file info from cache
        file_info = file_cache[user_id][replied_msg.id]
        
        # Create encoded string for the link
        encoded_data = await encode_string({
            "chat_id": file_info["dump_chat_id"],
            "msg_id": file_info["dump_msg_id"]
        })
        
        # Generate download link with URL-safe filename (same format as Stremio streaming)
        file_name = file_info["file_name"]  # Already sanitized
        original_name = file_info.get("original_name", file_name)
        
        # Generate both streaming and download links
        download_link = f"{Telegram.BASE_URL}/dl/{encoded_data}/{file_name}"
        watch_link = f"{Telegram.BASE_URL}/watch/{encoded_data}/{file_name}"
        
        
        # Create inline keyboard with buttons
        keyboard = [
            [
                InlineKeyboardButton("▶️ Stream Online", url=watch_link),
                InlineKeyboardButton("📥 Download", url=download_link)
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send message with inline buttons
        await message.reply_text(
            "✅ **Links Generated Successfully!**\n\n"
            f"� **{original_name}**\n"
            f"� **Size:** {file_info.get('file_size_str', 'Unknown')}\n\n"
            "🎬 Click a button below:",
            quote=True,
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        
        LOGGER.info(f"Link generated for user {user_id}: {file_name}")
    
    except Exception as e:
        LOGGER.error(f"Error in link_command_handler: {e}")
        await message.reply_text(
            f"❌ **An error occurred while generating the link:**\n`{str(e)}`\n\n"
            "Please try again or contact the administrator.",
            quote=True
        )


def get_readable_size(size_bytes):
    """Convert bytes to human readable format"""
    if size_bytes == 0:
        return "0 B"
    
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = 0
    while size_bytes >= 1024 and i < len(size_name) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.2f} {size_name[i]}"
