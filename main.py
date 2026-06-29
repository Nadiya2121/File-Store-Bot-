import os
import asyncio

# --- Python 3.12+ / 3.14 Pyrogram ইভেন্ট লুপ ক্র্যাশ ফিক্স (হটফিক্স) ---
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import random
import string
import logging
import traceback
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
OWNER_ID = int(os.environ.get("OWNER_ID", "7409347279")) 
PORT = int(os.environ.get("PORT", "8080")) 

# থাম্বনেইল/পোস্টার ইমেজ লিংক (আপনি চাইলে এটি পরিবর্তন করতে পারেন)
START_PIC = os.environ.get("START_PIC", "https://files.catbox.moe/4rpz79.jpg")

# বট ও ডাটাবেজ ইনিশিয়ালাইজেশন
app = Client(
    "PublicBatchStoreBot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN,
    in_memory=True
)
db_client = AsyncIOMotorClient(MONGO_URL)
db = db_client["PublicBatchStoreDB"]

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

# সাইজ রিডেবল করার ফাংশন (Bytes to MB/GB)
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
        return setting.get("time", 0) # মিনিটে রিটার্ন করবে, ০ মানে বন্ধ
    return 0

# মেসেজ ডিলিট করার ব্যাকগ্রাউন্ড টাস্ক
async def delete_after_delay(chat_id: int, message_ids: list, delay_minutes: int):
    await asyncio.sleep(delay_minutes * 60)
    try:
        await app.delete_messages(chat_id, message_ids)
    except Exception as e:
        logger.error(f"Error auto-deleting messages: {e}")

# ================= AIOHTTP WEB SERVER =================

async def handle_root(request):
    return web.Response(text="Bot Web Server is running perfectly!")

async def start_webserver():
    web_app = web.Application()
    web_app.router.add_get("/", handle_root)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

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

# ================= OWNER & ADMIN COMMANDS =================

@app.on_message(filters.command("addadmin") & filters.user(OWNER_ID))
async def add_admin(client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("ব্যবহারের নিয়ম: `/addadmin <ইউজার_আইডি>`")
    try:
        new_admin_id = int(args[1])
        await admins_col.update_one({"_id": new_admin_id}, {"$set": {"active": True}}, upsert=True)
        await message.reply_text(f"ইউজার `{new_admin_id}` সফলভাবে এডমিন হিসেবে নিযুক্ত হয়েছেন।")
    except ValueError:
        await message.reply_text("সঠিক আইডি প্রদান করুন।")

@app.on_message(filters.command("deladmin") & filters.user(OWNER_ID))
async def del_admin(client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("ব্যবহারের নিয়ম: `/deladmin <ইউজার_আইডি>`")
    try:
        admin_id = int(args[1])
        await admins_col.delete_one({"_id": admin_id})
        await message.reply_text("এডমিন সফলভাবে বাদ দেওয়া হয়েছে।")
    except ValueError:
        await message.reply_text("সঠিক আইডি প্রদান করুন।")

# --- ডিলিট কমান্ড (এডমিনদের জন্য) ---
@app.on_message(filters.command("delete"))
async def delete_file(client, message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("ব্যবহারের নিয়ম:\n`/delete <ফাইল_কী>`")
    
    file_key = args[1]
    result = await files_col.delete_one({"_id": file_key})
    if result.deleted_count > 0:
        await message.reply_text("ফাইল/ব্যাচ ডাটাবেজ থেকে স্থায়ীভাবে ডিলিট করা হয়েছে।")
    else:
        await message.reply_text("এই ফাইল কী-টি ডাটাবেজে পাওয়া যায়নি।")

# --- অটো-ডিলিট টাইম সেট করার কমান্ড (এডমিনদের জন্য) ---
@app.on_message(filters.command("setautodelete"))
async def set_autodelete(client, message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("ব্যবহারের নিয়ম:\n`/setautodelete <মিনিট>`\n(বন্ধ করতে `/setautodelete 0` লিখুন)")
    try:
        minutes = int(args[1])
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

# --- FSub কমান্ডসমূহ ---
@app.on_message(filters.command("addfsub"))
async def add_fsub(client, message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        return await message.reply_text("ব্যবহারের নিয়ম: `/addfsub <চ্যানেল_আইডি> <লিংক>`")
    await fsub_col.update_one({"_id": args[1]}, {"$set": {"invite_link": args[2]}}, upsert=True)
    await message.reply_text("FSub চ্যানেল যুক্ত হয়েছে।")

@app.on_message(filters.command("delfsub"))
async def del_fsub(client, message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("ব্যবহারের নিয়ম: `/delfsub <আইডি>`")
    await fsub_col.delete_one({"_id": args[1]})
    await message.reply_text("FSub চ্যানেল বাদ দেওয়া হয়েছে।")

# ================= MULTI-FILE BATCH SYSTEM =================

@app.on_message(filters.command("batch") & filters.private)
async def start_batch(client, message: Message):
    user_id = message.from_user.id
    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"batch_mode": True, "batch_files": []}},
        upsert=True
    )
    await message.reply_text(
        "📥 **ব্যাচ মোড চালু হয়েছে!**\n\nএখন একে একে আপনার ফাইলগুলো পাঠাতে থাকুন। সব পাঠানো শেষ হলে `/done` লিখে কমান্ড দিন।\n\n*বাতিল করতে চাইলে `/cancel` লিখুন।*"
    )

@app.on_message(filters.command("cancel") & filters.private)
async def cancel_batch(client, message: Message):
    user_id = message.from_user.id
    await users_col.update_one(
        {"_id": user_id},
        {"$unset": {"batch_mode": "", "batch_files": ""}}
    )
    await message.reply_text("ব্যাচ মোড বাতিল করা হয়েছে।")

@app.on_message(filters.command("done") & filters.private)
async def done_batch(client, message: Message):
    user_id = message.from_user.id
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
    
    bot_username = (await client.get_me()).username
    share_link = f"https://t.me/{bot_username}?start={file_key}"
    
    await message.reply_text(
        f"✅ **আপনার ব্যাচ ফাইলটি সেভ হয়েছে!**\n\n📦 মোট ফাইলের সংখ্যা: `{len(files_list)}` টি\n🔗 **শেয়ার লিংক:**\n`{share_link}`",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("শেয়ার করুন 🚀", url=f"https://telegram.me/share/url?url={share_link}")
        ]])
    )

# ================= FILE RECEIVER (Handling Batch & Single) =================

@app.on_message((filters.document | filters.video | filters.audio | filters.photo) & filters.private)
async def handle_incoming_files(client, message: Message):
    user_id = message.from_user.id
    user_data = await users_col.find_one({"_id": user_id})

    # ফাইলের তথ্য, আসল নাম ও সাইজ সংগ্রহ করা হচ্ছে
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

    # ইউজার যদি ব্যাচ মোডে থাকে
    if user_data and user_data.get("batch_mode"):
        await users_col.update_one(
            {"_id": user_id},
            {"$push": {"batch_files": file_item}}
        )
        current_count = len(user_data.get("batch_files", [])) + 1
        return await message.reply_text(f"📥 ফাইল যুক্ত হয়েছে (মোট: {current_count} টি)। পরবর্তী ফাইল পাঠান অথবা শেষ করতে `/done` লিখুন।")

    # সাধারণ সিঙ্গেল ফাইল সেভ
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
    
    bot_username = (await client.get_me()).username
    share_link = f"https://t.me/{bot_username}?start={file_key}"
    
    await message.reply_text(
        f"📥 **ফাইল সেভ হয়েছে!**\n\n📁 **নাম:** `{file_name}`\n⚖️ **সাইজ:** `{get_readable_size(file_size)}`\n\n🔗 **লিংক:**\n`{share_link}`",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("শেয়ার করুন 🚀", url=f"https://telegram.me/share/url?url={share_link}")
        ]])
    )

# ================= START COMMAND & FILE DELIVERY =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message: Message):
    user_id = message.from_user.id
    
    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"username": message.from_user.username}},
        upsert=True
    )

    args = message.text.split()
    
    # --- সাধারণ স্টার্ট মেসেজ (পোস্টার ও আকর্ষণীয় বাটন সহ) ---
    if len(args) < 2:
        start_caption = (
            "👋 **হ্যালো! আমি একটি অত্যন্ত দ্রুতগতির আধুনিক ফাইল স্টোর বট।**\n\n"
            "📂 এখানে আপনি যেকোনো মুভি, সিরিজ বা ফাইল সুরক্ষিতভাবে সংরক্ষণ করতে পারবেন এবং কাস্টম লিংক তৈরি করতে পারবেন।\n\n"
            "✨ **ফিচারসমূহ:**\n"
            "• মাল্টি-ফাইল ব্যাচ লিংক সাপোর্ট (`/batch`)\n"
            "• অটো-ডিলিট সিস্টেম প্রটেকশন\n"
            "• আনলিমিটেড স্টোরেজ ব্যাকআপ\n\n"
            "📢 নিচের বাটনগুলো ব্যবহার করে আমাদের সাথে যুক্ত থাকতে পারেন:"
        )
        
        # প্রফেশনাল স্টার্ট বাটন
        start_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📢 আপডেট চ্যানেল", url="https://t.me/TGLinkBase"), # আপনার চ্যানেল লিংক বসান
                InlineKeyboardButton("💬 সাপোর্ট গ্রুপ", url="https://t.me/TGLinkBase") # আপনার গ্রুপ লিংক বসান
            ],
            [
                InlineKeyboardButton("👨‍💻 ডেভেলপার আইডি", user_id=OWNER_ID)
            ]
        ])
        
        try:
            return await message.reply_photo(
                photo=START_PIC,
                caption=start_caption,
                reply_markup=start_buttons
            )
        except Exception:
            # কোনো কারণে ফটো সেন্ড না হলে টেক্সট হিসেবে পাঠানো হবে
            return await message.reply_text(
                text=start_caption,
                reply_markup=start_buttons
            )

    file_key = args[1]

    # FSub জয়েন রিকোয়েস্ট চেক করা
    unjoined_channels = []
    fsub_channels = fsub_col.find({})
    
    async for channel in fsub_channels:
        ch_id = channel["_id"]
        is_accessible = False
        try:
            member = await client.get_chat_member(chat_id=int(ch_id), user_id=user_id)
            if member.status in ["member", "administrator", "creator"]:
                is_accessible = True
        except UserNotParticipant:
            pass
        except Exception:
            pass

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
        
        try_again_url = f"https://t.me/{(await client.get_me()).username}?start={file_key}"
        buttons.append([InlineKeyboardButton("আমি রিকোয়েস্ট পাঠিয়েছি (ফাইল দিন)", url=try_again_url)])
        
        return await message.reply_text(
            "⚠️ **ফাইলগুলো পেতে আপনাকে আমাদের চ্যানেলে জয়েন রিকোয়েস্ট পাঠাতে হবে!**\n\nনিচের বাটনগুলো ব্যবহার করে রিকোয়েস্ট পাঠান এবং তারপর 'ফাইল দিন' বাটনে ক্লিক করুন।",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    # ফাইল বা ব্যাচ ডেলিভারি করা
    file_data = await files_col.find_one({"_id": file_key})
    if file_data:
        autodelete_time = await get_autodelete_time() # ডিলিট টাইম চেক করা হচ্ছে
        sent_messages = [] # পাঠানো মেসেজগুলোর আইডি ট্র্যাক করার জন্য
        
        try:
            # যদি অটো-ডিলিট অন থাকে
            if autodelete_time > 0:
                warning_msg = await message.reply_text(
                    f"⚠️ **নিরাপত্তাজনিত কারণে ফাইলটি `{autodelete_time}` মিনিট পর স্বয়ংক্রিয়ভাবে ডিলিট হয়ে যাবে।**\n"
                    "দয়া করে দ্রুত অন্য কোথাও ফরোয়ার্ড বা সেভ করে রাখুন।"
                )
                sent_messages.append(warning_msg.id)

            # ব্যাচ ফাইল হলে
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
                # সিঙ্গেল ফাইল হলে
                file_name = file_data.get("file_name", "Unnamed File")
                file_size = file_data.get("file_size", 0)
                caption_text = f"📁 **নাম:** `{file_name}`\n⚖️ **সাইজ:** `{get_readable_size(file_size)}`"
                
                sent_msg = await client.send_cached_media(
                    chat_id=message.chat.id,
                    file_id=file_data["file_id"],
                    caption=caption_text
                )
                sent_messages.append(sent_msg.id)

            # অটো-ডিলিট টাস্ক শিডিউল করা
            if autodelete_time > 0 and sent_messages:
                asyncio.create_task(delete_after_delay(message.chat.id, sent_messages, autodelete_time))

        except Exception as e:
            await message.reply_text(f"ফাইল পাঠাতে ত্রুটি হয়েছে: {e}")
    else:
        await message.reply_text("❌ ফাইল বা ব্যাচটি ডাটাবেজে পাওয়া যায়নি বা ডিলিট করা হয়েছে।")

# ================= RUNNING BOTH SERVER & BOT =================

async def run_bot():
    await app.start()
    logger.info("Telegram bot started successfully!")
    await start_webserver()
    await idle()
    await app.stop()

if __name__ == "__main__":
    try:
        loop.run_until_complete(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error("An error occurred during bot execution:")
        traceback.print_exc()
