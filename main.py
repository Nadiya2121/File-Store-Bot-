import os
import asyncio
import random
import string
import logging
import traceback
from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, ChatJoinRequest
from pyrogram.errors import UserNotParticipant
from motor.motor_asyncio import AsyncIOMotorClient

# বেসিক লগিং কনফিগারেশন (যাতে রেন্ডারের লগে সব ডিটেইল দেখা যায়)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- কনফিগারেশন ---
API_ID = int(os.environ.get("API_ID", "29462738")) 
API_HASH = os.environ.get("API_HASH", "297f51aaab99720a09e80273628c3c24") 
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8787371353:AAEUE0vK2siElnew2LnaAs-3djZPxxjFKpo") 
MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://hepemo5263:hepemo5263@cluster0.5vugv.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0") 
OWNER_ID = int(os.environ.get("OWNER_ID", "7409347279")) 
PORT = int(os.environ.get("PORT", "8080")) # Render/Koyeb-এর পোর্ট

# বট ও ডাটাবেজ ইনিশিয়ালাইজেশন (সেশন লক এড়াতে in_memory=True যুক্ত করা হয়েছে)
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

# ইউনিক আইডি জেনারেটর
def generate_id():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=8))

# এডমিন চেক করার হেল্পার ফাংশন
async def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    admin = await admins_col.find_one({"_id": user_id})
    return admin is not None

# ================= AIOHTTP WEB SERVER (For Render/Koyeb) =================

async def handle_root(request):
    return web.Response(text="Bot Web Server is running perfectly!")

async def start_webserver():
    web_app = web.Application()
    web_app.router.add_get("/", handle_root)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web server started on port {PORT}")

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

# --- FSub অ্যাড/রিমুভ কমান্ডসমূহ ---
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

# ব্যাচ মোড শুরু করার কমান্ড
@app.on_message(filters.command("batch") & filters.private)
async def start_batch(client, message: Message):
    user_id = message.from_user.id
    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"batch_mode": True, "batch_files": []}},
        upsert=True
    )
    await message.reply_text(
        "📥 **ব্যাচ মোড চালু হয়েছে!**\n\nএখন একের পর এক আপনার ফাইলগুলো পাঠাতে থাকুন। সব পাঠানো শেষ হলে `/done` লিখে কমান্ড দিন।\n\n*বাতিল করতে চাইলে `/cancel` লিখুন।*"
    )

# ব্যাচ মোড বাতিল করার কমান্ড
@app.on_message(filters.command("cancel") & filters.private)
async def cancel_batch(client, message: Message):
    user_id = message.from_user.id
    await users_col.update_one(
        {"_id": user_id},
        {"$unset": {"batch_mode": "", "batch_files": ""}}
    )
    await message.reply_text("ব্যাচ মোড বাতিল করা হয়েছে।")

# ব্যাচ সেভ করার কমান্ড
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
    
    # ডাটাবেজে ব্যাচ ফাইল লিস্ট সেভ করা
    await files_col.insert_one({
        "_id": file_key,
        "files": files_list, 
        "uploader_id": user_id,
        "is_batch": True
    })
    
    # ইউজারের ব্যাচ মোড স্ট্যাটাস রিসেট করা
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

    # ফাইলের তথ্য সংগ্রহ
    if message.document:
        file_id, file_type = message.document.file_id, "document"
    elif message.video:
        file_id, file_type = message.video.file_id, "video"
    elif message.audio:
        file_id, file_type = message.audio.file_id, "audio"
    else:
        file_id, file_type = (message.photo[0].file_id if isinstance(message.photo, list) else message.photo.file_id), "photo"

    file_item = {"file_id": file_id, "type": file_type}

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
        "uploader_id": user_id,
        "is_batch": False
    })
    
    bot_username = (await client.get_me()).username
    share_link = f"https://t.me/{bot_username}?start={file_key}"
    
    await message.reply_text(
        f"📥 **ফাইল সেভ হয়েছে!**\n\n🔗 **লিংক:**\n`{share_link}`",
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
    if len(args) < 2:
        return await message.reply_text("হ্যালো! আমি একটি মাল্টি-ফাইল স্টোর বট। একাধিক ফাইলের একটি লিংক তৈরি করতে প্রথমে `/batch` কমান্ড দিন।")

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
        try:
            if file_data.get("is_batch"):
                await message.reply_text(f"📦 আপনার ব্যাচে মোট `{len(file_data['files'])}` টি ফাইল রয়েছে। ফাইলগুলো পাঠানো হচ্ছে...")
                for file_item in file_data["files"]:
                    await client.send_cached_media(
                        chat_id=message.chat.id,
                        file_id=file_item["file_id"]
                    )
                    await asyncio.sleep(0.5)
            else:
                await client.send_cached_media(
                    chat_id=message.chat.id,
                    file_id=file_data["file_id"],
                    caption="এখানে আপনার ফাইলটি দেওয়া হলো।"
                )
        except Exception as e:
            await message.reply_text(f"ফাইল পাঠাতে ত্রুটি হয়েছে: {e}")
    else:
        await message.reply_text("❌ ফাইল বা ব্যাচটি ডাটাবেজে পাওয়া যায়নি বা ডিলিট করা হয়েছে।")

# ================= RUNNING BOTH SERVER & BOT =================

async def run_bot():
    # বট স্টার্ট করা
    await app.start()
    logger.info("Telegram bot started successfully!")
    
    # ওয়েব সার্ভার ব্যাকগ্রাউন্ডে চালু করা
    await start_webserver()
    
    # সিগন্যাল হ্যান্ডলিং সহ বট সচল রাখা
    await idle()
    
    # বন্ধ করার সময় ক্লিনআপ
    await app.stop()

if __name__ == "__main__":
    try:
        # আধুনিক asyncio.run() ব্যবহার করা হয়েছে যা পাইথন ৩.১০+ এ সবচেয়ে নিরাপদ
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        # কোনো কারণে ক্র্যাশ করলে রেন্ডারের কনসোলে যেন সম্পূর্ণ ট্র্যাকিং দেখা যায়
        logger.error("An error occurred during bot execution:")
        traceback.print_exc()
