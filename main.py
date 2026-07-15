import os
import sys
import types
import asyncio

# ================= PYTHON 3.12+ / 3.14 PYROGRAM PURE ASYNC PATCH =================
# এই প্যাচটি Pyrogram-এর ত্রুটিযুক্ত সিঙ্ক র‍্যাপার নিষ্ক্রিয় করে এটিকে পিওর অ্যাসিনক্রোনাস মুডে রান করায়।
# এর ফলে আধুনিক পাইথন সংস্করণগুলোতে কোনো ইভেন্ট লুপ সংঘর্ষ ছাড়াই বট নির্বিঘ্নে চলবে।

sync_mod = types.ModuleType("pyrogram.sync")

async def dummy_idle():
    import signal
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    
    def signal_handler():
        if not future.done():
            future.set_result(None)
            
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            pass
    try:
        await future
    except asyncio.CancelledError:
        pass

async def dummy_compose(*args, **kwargs):
    pass

sync_mod.idle = dummy_idle
sync_mod.compose = dummy_compose

sys.modules["pyrogram.sync"] = sync_mod
# =================================================================================

import random
import string
import logging
import traceback
import certifi  # ক্লাউড প্ল্যাটফর্মে MongoDB SSL ভেরিফিকেশন ফিক্স করার জন্য

from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, ChatJoinRequest
from pyrogram.errors import UserNotParticipant
from motor.motor_asyncio import AsyncIOMotorClient

# বেসিক লগিং কনফিগারেশন
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- কনফিগারেশন ---
API_ID = int(os.environ.get("API_ID", "29462738")) 
API_HASH = os.environ.get("API_HASH", "297f51aaab99720a09e80273628c3c24") 
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8787371353:AAEUE0vK2siElnew2LnaAs-3djZPxxjFKpo") 
MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://hepemo5263:hepemo5263@cluster0.5vugv.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0") 
OWNER_ID = int(os.environ.get("OWNER_ID", "8297458824")) 
PORT = int(os.environ.get("PORT", "8000")) 

# থাম্বনেইল/পোস্টার ইমেজ লিংক
START_PIC = os.environ.get("START_PIC", "https://files.catbox.moe/4rpz79.jpg")

# বট ইনিশিয়ালাইজেশন
app = Client(
    "PublicBatchStoreBot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN,
    in_memory=True
)

# ডেটাবেজ কানেকশন
try:
    db_client = AsyncIOMotorClient(MONGO_URL, tlsCAFile=certifi.where())
    db = db_client["PublicBatchStoreDB"]
except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")

# ডাটাবেজ কালেকশনস
files_col = db["files"]
users_col = db["users"]
fsub_col = db["fsub_channels"]
requests_col = db["join_requests"]
admins_col = db["admins"]
settings_col = db["settings"]

# ইউনিক আইডি জেনারেটর
def generate_id():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=8))

# সাইজ রিডেবল করার ফাংশন
def get_readable_size(size_in_bytes):
    if not size_in_bytes:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0

# এডমিন চেক করার হেল্পার ফাংশন
async def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    admin = await admins_col.find_one({"_id": user_id})
    return admin is not None

# অটো-ডিলিট টাইম পাওয়ার হেল্পার
async def get_autodelete_time():
    setting = await settings_col.find_one({"_id": "autodelete_config"})
    if setting:
        return setting.get("time", 0)
    return 0

# আইডি কনভার্ট করার হেল্পার ফাংশন
def parse_chat_id(chat_id_str: str):
    chat_id_str = chat_id_str.strip()
    if chat_id_str.startswith("-") or chat_id_str.isdigit():
        try:
            return int(chat_id_str)
        except ValueError:
            return chat_id_str
    return chat_id_str

# মেসেজ ডিলিট করার ব্যাকগ্রাউন্ড টাস্ক
async def delete_after_delay(chat_id: int, message_ids: list, delay_minutes: int):
    await asyncio.sleep(delay_minutes * 60)
    try:
        await app.delete_messages(chat_id, message_ids)
    except Exception as e:
        logger.error(f"Error auto-deleting messages: {e}")

# ================= AIOHTTP WEB SERVER =================

async def handle_root(request):
    return web.Response(text="Bot Web Server is running!")

async def start_webserver():
    web_app = web.Application()
    web_app.router.add_get("/", handle_root)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web server successfully started on port {PORT}")

# ================= JOIN REQUEST TRACKING =================

@app.on_chat_join_request()
async def track_join_request(client, request: ChatJoinRequest):
    channel_id = str(request.chat.id)
    is_fsub_channel = await fsub_col.find_one({"_id": channel_id})
    if is_fsub_channel:
        await requests_col.update_one(
            {"user_id": request.user.id, "channel_id": channel_id},
            {"$set": {"requested": True}},
            upsert=True
        )

# ================= START COMMAND LOGIC HELPERS =================

async def process_start_command(client, message: Message, args):
    user_id = message.from_user.id if message.from_user else message.chat.id
    username = message.from_user.username if message.from_user else None
    
    # ইউজার ডাটাবেজে সংরক্ষণ
    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"username": username}},
        upsert=True
    )

    # সাধারণ স্টার্ট মেসেজ
    if not args:
        start_caption = (
            "👋 **হ্যালো! আমি একটি অত্যন্ত দ্রুতগতির আধুনিক ফাইল স্টোর বট।**\n\n"
            "📂 এখানে আপনি যেকোনো মুভি, সিরিজ বা ফাইল সুরক্ষিতভাবে সংরক্ষণ করতে পারবেন এবং কাস্টম লিংক তৈরি করতে পারবেন।\n\n"
            "✨ **ফিচারসমূহ:**\n"
            "• মাল্টি-ফাইল ব্যাচ লিংক সাপোর্ট (`/batch`)\n"
            "• অটো-ডিলিট সিস্টেম প্রটেকশন\n"
            "• আনলিমিটেড স্টোরেজ ব্যাকআপ\n\n"
            "📢 নিচের বাটনগুলো ব্যবহার করে আমাদের সাথে যুক্ত থাকতে পারেন:"
        )
        
        start_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📢 আপডেট চ্যানেল", url="https://t.me/TGLinkBase"), 
                InlineKeyboardButton("💬 সাপোর্ট গ্রুপ", url="https://t.me/TGLinkBase") 
            ],
            [
                InlineKeyboardButton("👨‍💻 ডেভেলপার আইডি", url=f"tg://user?id={OWNER_ID}")
            ]
        ])
        
        try:
            return await message.reply_photo(
                photo=START_PIC,
                caption=start_caption,
                reply_markup=start_buttons
            )
        except Exception as e:
            logger.error(f"Failed to send photo: {e}")
            return await message.reply_text(
                text=start_caption,
                reply_markup=start_buttons
            )

    file_key = args[0]

    # FSub জয়েন রিকোয়েস্ট চেক করা
    unjoined_channels = []
    fsub_channels = fsub_col.find({})
    
    async for channel in fsub_channels:
        ch_id = channel["_id"]
        is_accessible = False
        parsed_id = parse_chat_id(ch_id)
        
        try:
            member = await client.get_chat_member(chat_id=parsed_id, user_id=user_id)
            if member.status in ["member", "administrator", "creator"]:
                is_accessible = True
        except UserNotParticipant:
            pass
        except Exception as e:
            logger.warning(f"FSub access check bypass or error for {ch_id}: {e}")

        if not is_accessible:
            req = await requests_col.find_one({"user_id": user_id, "channel_id": ch_id})
            if req and req.get("requested"):
                is_accessible = True

        if not is_accessible:
            unjoined_channels.append(channel)

    if unjoined_channels:
        buttons = []
        for index, ch in enumerate(unjoined_channels, start=1):
            buttons.append([InlineKeyboardButton(f"চ্যানেল {index}-এ জয়েন রিকোয়েস্ট পাঠান", url=ch["invite_link"])])
        
        bot_info = await client.get_me()
        try_again_url = f"https://t.me/{bot_info.username}?start={file_key}"
        buttons.append([InlineKeyboardButton("আমি রিকোয়েস্ট পাঠিয়েছি (ফাইল দিন)", url=try_again_url)])
        
        return await message.reply_text(
            "⚠️ **ফাইলগুলো পেতে আপনাকে আমাদের চ্যানেলে জয়েন রিকোয়েস্ট পাঠাতে হবে!**\n\nনিচের বাটনগুলো ব্যবহার করে রিকোয়েস্ট পাঠান এবং তারপর 'ফাইল দিন' বাটনে ক্লিক করুন।",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    # ফাইল বা ব্যাচ ডেলিভারি করা
    file_data = await files_col.find_one({"_id": file_key})
    if file_data:
        autodelete_time = await get_autodelete_time()
        sent_messages = []
        
        try:
            if autodelete_time > 0:
                warning_msg = await message.reply_text(
                    f"⚠️ **নিরাপত্তাজনিত কারণে ফাইলটি `{autodelete_time}` মিনিট পর স্বয়ংক্রিয়ভাবে ডিলিট হয়ে যাবে।**\n"
                    "দয়া করে দ্রুত অন্য কোথাও ফরোয়ার্ড বা সেভ করে রাখুন।"
                )
                sent_messages.append(warning_msg.id)

            if file_data.get("is_batch"):
                for file_item in file_data["files"]:
                    file_name = file_item.get("file_name", "Unnamed File")
                    file_size = file_item.get("file_size", 0)
                    caption_text = f"📁 **নাম:** `{file_name}`\n⚖️ **সাইজ:** `{get_readable_size(file_size)}`"
                    
                    sent_msg = await client.send_cached_media(
                        chat_id=message.chat.id,
                        file_id=file_item["file_id"],
                        caption=caption_text
                    )
                    sent_messages.append(sent_msg.id)
                    await asyncio.sleep(0.5)
            else:
                file_name = file_data.get("file_name", "Unnamed File")
                file_size = file_data.get("file_size", 0)
                caption_text = f"📁 **নাম:** `{file_name}`\n⚖️ **সাইজ:** `{get_readable_size(file_size)}`"
                
                sent_msg = await client.send_cached_media(
                    chat_id=message.chat.id,
                    file_id=file_data["file_id"],
                    caption=caption_text
                )
                sent_messages.append(sent_msg.id)

            if autodelete_time > 0 and sent_messages:
                asyncio.create_task(delete_after_delay(message.chat.id, sent_messages, autodelete_time))

        except Exception as e:
            await message.reply_text(f"ফাইল পাঠাতে ত্রুটি হয়েছে: {e}")
    else:
        await message.reply_text("❌ ফাইল বা ব্যাচটি ডাটাবেজে পাওয়া যায়নি বা ডিলিট করা হয়েছে।")

# ================= UNIFIED COMMAND ROUTER =================

@app.on_message(filters.text & filters.private)
async def unified_command_handler(client, message: Message):
    text = message.text.strip()
    
    if not text.startswith("/"):
        return 

    parts = text.split()
    command = parts[0].lower()
    args = parts[1:]
    
    user_id = message.from_user.id if message.from_user else message.chat.id

    # ১. /start কমান্ড
    if command == "/start":
        await process_start_command(client, message, args)

    # ২. /addadmin কমান্ড
    elif command == "/addadmin":
        if user_id != OWNER_ID:
            return await message.reply_text(
                f"❌ **এই কমান্ডটি ব্যবহারের অনুমতি আপনার নেই!**\n\n"
                f"👤 আপনার আইডি: `{user_id}`\n"
                f"👑 বটের মালিকের আইডি: `{OWNER_ID}`"
            )
        if len(args) < 1:
            return await message.reply_text("ব্যবহারের নিয়ম: `/addadmin <ইউজার_আইডি>`")
        try:
            new_admin_id = int(args[0])
            await admins_col.update_one({"_id": new_admin_id}, {"$set": {"active": True}}, upsert=True)
            await message.reply_text(f"ইউজার `{new_admin_id}` সফলভাবে এডমিন হিসেবে নিযুক্ত হয়েছেন।")
        except ValueError:
            await message.reply_text("দয়া করে সঠিক সংখ্যায় আইডি দিন।")

    # ৩. /deladmin কমান্ড
    elif command == "/deladmin":
        if user_id != OWNER_ID:
            return await message.reply_text(f"❌ এই কমান্ডটি ব্যবহারের অনুমতি আপনার নেই।\n👤 আপনার আইডি: `{user_id}`")
        if len(args) < 1:
            return await message.reply_text("ব্যবহারের নিয়ম: `/deladmin <ইউজার_আইডি>`")
        try:
            admin_id = int(args[0])
            await admins_col.delete_one({"_id": admin_id})
            await message.reply_text("এডমিন সফলভাবে বাদ দেওয়া হয়েছে।")
        except ValueError:
            await message.reply_text("দয়া করে সঠিক সংখ্যায় আইডি দিন。")

    # ৪. /adminlist কমান্ড
    elif command == "/adminlist":
        if user_id != OWNER_ID:
            return await message.reply_text(f"❌ এই কমান্ডটি ব্যবহারের অনুমতি আপনার নেই।\n👤 আপনার আইডি: `{user_id}`")
        admins = admins_col.find({})
        text_msg = f"👑 **প্রধান মালিক:** `{OWNER_ID}`\n\n👮‍♂️ **সহকারী এডমিনবৃন্দ:**\n"
        has_admin = False
        async for admin in admins:
            text_msg += f"- `{admin['_id']}`\n"
            has_admin = True
        if not has_admin:
            text_msg += "*(কোনো সহকারী এডমিন যুক্ত নেই)*"
        await message.reply_text(text_msg)

    # ৫. /addfsub কমান্ড
    elif command == "/addfsub":
        if not await is_admin(user_id):
            return await message.reply_text(f"❌ **আপনি এই বটের এডমিন নন!**\n👤 আপনার আইডি: `{user_id}`")
        if len(args) < 2:
            return await message.reply_text("ব্যবহারের নিয়ম: `/addfsub <চ্যানেল_আইডি> <লিংক>`")
        await fsub_col.update_one({"_id": args[0]}, {"$set": {"invite_link": args[1]}}, upsert=True)
        await message.reply_text("FSub চ্যানেল সফলভাবে যুক্ত হয়েছে।")

    # ৬. /delfsub কমান্ড
    elif command == "/delfsub":
        if not await is_admin(user_id):
            return await message.reply_text(f"❌ আপনি এই বটের এডমিন নন।\n👤 আপনার আইডি: `{user_id}`")
        if len(args) < 1:
            return await message.reply_text("ব্যবহারের নিয়ম: `/delfsub <আইডি>`")
        await fsub_col.delete_one({"_id": args[0]})
        await message.reply_text("FSub চ্যানেল বাদ দেওয়া হয়েছে।")

    # ७. /fsublist কমান্ড
    elif command == "/fsublist":
        if not await is_admin(user_id):
            return await message.reply_text(f"❌ আপনি এই বটের এডমিন নন。\n👤 আপনার আইডি: `{user_id}`")
        channels = fsub_col.find({})
        text_msg = "**FSub চ্যানেল তালিকা:**\n\n"
        has_channel = False
        async for ch in channels:
            text_msg += f"ID: `{ch['_id']}`\nLink: {ch['invite_link']}\n\n"
            has_channel = True
        if not has_channel:
            text_msg += "*(কোনো FSub চ্যানেল যুক্ত নেই)*"
        await message.reply_text(text_msg)

    # ৮. /setautodelete কমান্ড
    elif command == "/setautodelete":
        if not await is_admin(user_id):
            return await message.reply_text(f"❌ আপনি এই বটের এডমিন নন।\n👤 আপনার আইডি: `{user_id}`")
        if len(args) < 1:
            return await message.reply_text("ব্যবহারের নিয়ম:\n`/setautodelete <মিনিট>`\n(বন্ধ করতে `/setautodelete 0` লিখুন)")
        try:
            minutes = int(args[0])
            await settings_col.update_one(
                {"_id": "autodelete_config"},
                {"$set": {"time": minutes}},
                upsert=True
            )
            if minutes > 0:
                await message.reply_text(f"অটো-ডিলিট সফলভাবে `{minutes}` মিনিটের জন্য সেট করা হয়েছে।")
            else:
                await message.reply_text("অটো-ডিলিট সিস্টেম বন্ধ করা হয়েছে।")
        except ValueError:
            await message.reply_text("দয়া করে সঠিক মিনিট সংখ্যায় লিখুন।")

    # ৯. /delete কমান্ড
    elif command == "/delete":
        if not await is_admin(user_id):
            return await message.reply_text(f"❌ আপনি এই বটের এডমিন নন।\n👤 আপনার আইডি: `{user_id}`")
        if len(args) < 1:
            return await message.reply_text("ব্যবহারের নিয়ম:\n`/delete <ফাইল_কী>`")
        file_key = args[0]
        result = await files_col.delete_one({"_id": file_key})
        if result.deleted_count > 0:
            await message.reply_text("ফাইল/ব্যাচ ডাটাবেজ থেকে স্থায়ীভাবে ডিলিট করা হয়েছে।")
        else:
            await message.reply_text("এই ফাইল কী-টি ডাটাবেজে পাওয়া যায়নি।")

    # ১০. /batch কমান্ড
    elif command == "/batch":
        await users_col.update_one(
            {"_id": user_id},
            {"$set": {"batch_mode": True, "batch_files": []}},
            upsert=True
        )
        await message.reply_text(
            "📥 **ব্যাচ মোড চালু হয়েছে!**\n\nএখন একে একে আপনার ফাইলগুলো পাঠাতে থাকুন। সব পাঠানো শেষ হলে `/done` লিখে কমান্ড দিন।\n\n*বাতিল করতে চাইলে `/cancel` লিখুন।*"
        )

    # ১১. /cancel কমান্ড
    elif command == "/cancel":
        await users_col.update_one(
            {"_id": user_id},
            {"$unset": {"batch_mode": "", "batch_files": ""}}
        )
        await message.reply_text("ব্যাচ মোড বাতিল করা হয়েছে।")

    # ১২. /done কমান্ড
    elif command == "/done":
        user_data = await users_col.find_one({"_id": user_id})
        if not user_data or not user_data.get("batch_mode"):
            return await message.reply_text("আপনি ব্যাচ মোডে নেই। নতুন ব্যাচ শুরু করতে `/batch` লিখুন।")
        
        files_list = user_data.get("batch_files", [])
        if not files_list:
            return await message.reply_text("আপনি কোনো ফাইল পাঠাননি। ব্যাচ মোড বন্ধ করতে `/cancel` লিখুন।")
        
        file_key = generate_id()
        await files_col.insert_one({
            "_id": file_key,
            "files": files_list, 
            "uploader_id": user_id,
            "is_batch": True
        })
        
        await users_col.update_one(
            {"_id": user_id},
            {"$unset": {"batch_mode": "", "batch_files": ""}}
        )
        
        bot_info = await client.get_me()
        share_link = f"https://t.me/{bot_info.username}?start={file_key}"
        
        await message.reply_text(
            f"✅ **আপনার ব্যাচ ফাইলটি সেভ হয়েছে!**\n\n📦 মোট ফাইলের সংখ্যা: `{len(files_list)}` টি\n🔗 **শেয়ার লিংক:**\n`{share_link}`",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("শেয়ার করুন 🚀", url=f"https://telegram.me/share/url?url={share_link}")
            ]])
        )

    # ১৩. অন্য যেকোনো ভুল কমান্ডের জন্য
    else:
        await message.reply_text("❌ **দুঃখিত, এই কমান্ডটি বটের জানা নেই।**\nসঠিক কমান্ডগুলো দেখতে মেনু চেক করুন।")

# ================= FILE RECEIVER =================

@app.on_message((filters.document | filters.video | filters.audio | filters.photo) & filters.private)
async def handle_incoming_files(client, message: Message):
    user_id = message.from_user.id if message.from_user else message.chat.id
    user_data = await users_col.find_one({"_id": user_id})

    file_name = "Unnamed File"
    file_size = 0
    
    if message.document:
        file_id, file_type = message.document.file_id, "document"
        file_name = message.document.file_name or "Document"
        file_size = message.document.file_size
    elif message.video:
        file_id, file_type = message.video.file_id, "video"
        file_name = message.video.file_name or message.caption or "Video"
        file_size = message.video.file_size
    elif message.audio:
        file_id, file_type = message.audio.file_id, "audio"
        file_name = message.audio.file_name or "Audio"
        file_size = message.audio.file_size
    else:
        file_id, file_type = (message.photo[0].file_id if isinstance(message.photo, list) else message.photo.file_id), "photo"
        file_name = "Image File"
        file_size = 0

    file_item = {
        "file_id": file_id, 
        "type": file_type, 
        "file_name": file_name, 
        "file_size": file_size
    }

    if user_data and user_data.get("batch_mode"):
        await users_col.update_one(
            {"_id": user_id},
            {"$push": {"batch_files": file_item}}
        )
        current_count = len(user_data.get("batch_files", [])) + 1
        return await message.reply_text(f"📥 ফাইল যুক্ত হয়েছে (মোট: {current_count} টি)। পরবর্তী ফাইল পাঠান অথবা শেষ করতে `/done` লিখুন।")

    file_key = generate_id()
    await files_col.insert_one({
        "_id": file_key,
        "file_id": file_id,
        "type": file_type,
        "file_name": file_name,
        "file_size": file_size,
        "uploader_id": user_id,
        "is_batch": False
    })
    
    bot_info = await client.get_me()
    share_link = f"https://t.me/{bot_info.username}?start={file_key}"
    
    await message.reply_text(
        f"📥 **ফাইল সেভ হয়েছে!**\n\n📁 **নাম:** `{file_name}`\n⚖️ **সাইজ:** `{get_readable_size(file_size)}`\n\n🔗 **লিংক:**\n`{share_link}`",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("শেয়ার করুন 🚀", url=f"https://telegram.me/share/url?url={share_link}")
        ]])
    )

# ================= RUNNING BOTH SERVER & BOT =================

async def run_bot():
    await app.start()
    logger.info("Telegram bot started successfully in Pure Async Mode!")
    await start_webserver()
    await idle()
    await app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error("An error occurred during bot execution:")
        traceback.print_exc()
