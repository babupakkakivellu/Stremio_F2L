from pyrogram import filters, Client, enums
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait
from Backend.config import Telegram
from Backend.helper.encrypt import encode_string
from Backend.helper.database import Database
from Backend.pyrofork.bot import multi_clients, work_loads
from Backend.logger import LOGGER
from datetime import datetime, timedelta
from asyncio import sleep as asleep
import re
import urllib.parse
import hashlib

# Database instance for persistent storage
db = Database()

# Temporary cache for /link command (maps user message to database ID)
# Structure: {user_id: {user_msg_id: file_db_id}}
temp_cache = {}


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


async def calculate_file_hash(client: Client, message: Message) -> str:
    """
    Calculate SHA256 hash of a file for duplicate detection.
    Only reads first 10MB for speed.
    
    Args:
        client: Pyrogram client
        message: Message containing the file
    
    Returns:
        SHA256 hash string
    """
    file = message.video or message.document
    file_id = message.video.file_id if message.video else message.document.file_id
    
    # Read first 10MB for hash calculation (fast duplicate detection)
    chunk_size = 10 * 1024 * 1024  # 10MB
    hasher = hashlib.sha256()
    
    async for chunk in client.stream_media(file_id, limit=chunk_size):
        hasher.update(chunk)
    
    return hasher.hexdigest()


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
            user_id = message.from_user.id
            
            # Step 1: Calculate file hash for duplicate detection
            progress_msg = await message.reply_text("🔄 Processing file...", quote=True)
            
            # Get least loaded client for upload (load balancing)
            index = min(work_loads, key=work_loads.get)
            upload_client = multi_clients[index]
            work_loads[index] += 1
            
            try:
                file_hash = await calculate_file_hash(upload_client, message)
                
                # Step 2: Check for duplicate
                existing_file = await db.get_file_by_hash(file_hash)
                
                if existing_file:
                    # Duplicate found - return existing link
                    await progress_msg.delete()
                    
                    # Store in temp_cache for /link command
                    if user_id not in temp_cache:
                        temp_cache[user_id] = {}
                    temp_cache[user_id][message.id] = existing_file["_id"]
                    
                    # Update access stats
                    await db.update_file_access(existing_file["_id"])
                    
                    LOGGER.info(f"Duplicate file detected for user {user_id}: {file_name}")
                    
                    await message.reply_text(
                        "✅ *File already exists!*\n\n"
                        f"📄 *File:* {existing_file['original_name']}\n"
                        f"💾 *Size:* {existing_file['file_size_str']}\n\n"
                        "🔄 *Using existing upload*\n"
                        "Reply with `/link` to get your links.",
                        quote=True,
                        parse_mode=enums.ParseMode.MARKDOWN
                    )
                    return
                
                # Step 3: No duplicate - proceed with upload
                await progress_msg.edit_text("🔄 Uploading to storage...")
                
                # Forward file to FILE_TO_LINK_DUMP channel using load-balanced client
                forwarded_msg = await upload_client.forward_messages(
                    chat_id=Telegram.FILE_TO_LINK_DUMP,
                    from_chat_id=message.chat.id,
                    message_ids=message.id
                )
                
                # Sanitize filename for URL
                url_safe_filename = sanitize_filename(file_name)
                
                # Step 4: Store in database
                file_data = {
                    "user_id": user_id,
                    "dump_chat_id": str(Telegram.FILE_TO_LINK_DUMP).replace("-100", ""),
                    "dump_msg_id": forwarded_msg.id,
                    "file_name": url_safe_filename,
                    "original_name": file_name,
                    "file_size": file_size,
                    "file_size_str": get_readable_size(file_size),
                    "file_hash": file_hash
                }
                
                file_db_id = await db.insert_file_to_link(file_data)
                
                # Store in temp_cache for /link command
                if user_id not in temp_cache:
                    temp_cache[user_id] = {}
                temp_cache[user_id][message.id] = file_db_id
                
                await progress_msg.delete()
                LOGGER.info(f"File uploaded by user {user_id}: {file_name} (hash: {file_hash[:8]}...)")
                
            finally:
                # Always decrement workload
                work_loads[index] -= 1
            
        except Exception as e:
            LOGGER.error(f"Error processing file: {e}")
            await message.reply_text(
                "❌ **Failed to process file.**\n\n"
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
        
        
        # Check if file info exists in temp_cache
        if user_id not in temp_cache or replied_msg.id not in temp_cache[user_id]:
            await message.reply_text(
                "⚠️ **File not found.**\n\n"
                "Please upload the file first, then reply to it with `/link`",
                quote=True
            )
            return
        
        # Get file_db_id from temp_cache
        file_db_id = temp_cache[user_id][replied_msg.id]
        
        # Retrieve full file info from database
        file_info = None
        for i in range(1, db.current_db_index + 1):
            db_key = f"storage_{i}"
            from bson import ObjectId
            result = await db.dbs[db_key]["file_to_link"].find_one({"_id": ObjectId(file_db_id)})
            if result:
                from Backend.helper.database import convert_objectid_to_str
                file_info = convert_objectid_to_str(result)
                break
        
        if not file_info:
            await message.reply_text(
                "⚠️ **File not found in database.**\n\n"
                "Please upload the file again.",
                quote=True
            )
            return
        
        # Create encoded string for the link
        encoded_data = await encode_string({
            "chat_id": file_info["dump_chat_id"],
            "msg_id": file_info["dump_msg_id"]
        })
        
        # Generate download link with URL-safe filename
        file_name = file_info["file_name"]
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
        
        # Send message with inline buttons AND text links
        await message.reply_text(
            "✅ *Links Generated Successfully!*\n\n"
            f"📄 *File:* {original_name}\n"
            f"💾 *Size:* {file_info.get('file_size_str', 'Unknown')}\n\n"
            "🎬 *Choose an option:*\n\n"
            f"🌐 *Stream:* `{watch_link}`\n"
            f"📥 *Download:* `{download_link}`",
            quote=True,
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=reply_markup,
            disable_web_page_preview=True
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
