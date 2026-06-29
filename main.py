import os
import asyncio
import random
import string
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, ChatJoinRequest
from pyrogram.errors import UserNotParticipant
from motor.motor_asyncio import AsyncIOMotorClient

# --- কনফিগারেশন ---
API_ID = int(os.environ.get("API_ID", "123456")) 
API_HASH = os.environ.get("API_HASH", "your_api_hash") 
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token") 
MONGO_URL = os.environ.get("MONGO_URL", "your_mongodb_url") 
OWNER_ID = int(os.environ.get("OWNER_ID", "123456789")) # বটের প্রধান মালিকের আইডি

# বট ও ডাটাবেজ ইনিশিয়ালাইজেশন
app = Client("PublicFileStoreBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
db_client = AsyncIOMotorClient(MONGO_URL)
db = db_client["PublicFileStoreDB"]

# ডাটাবেজ কালেকশনস
files_col = db["files"]
users_col = db["users"]
fsub_col = db["fsub_channels"]
requests_col = db["join_requests"]
admins_col = db["admins"] # সহকারী এডমিনদের তালিকা

# ইউনিক আইডি জেনারেটর
def generate_id():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=8))

# --- এডমিন চেক করার হেল্পার ফাংশন ---
async def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    admin = await admins_col.find_one({"_id": user_id})
    return admin is not None

# --- জয়েন রিকোয়েস্ট ট্র্যাকিং (পেন্ডিং রাখার জন্য) ---
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

# ================= OWNER COMMANDS =================

@app.on_message(filters.command("addadmin") & filters.user(OWNER_ID))
async def add_admin(client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("ব্যবহারের নিয়ম:\n`/addadmin <ইউজার_আইডি>`")
    try:
        new_admin_id = int(args[1])
        await admins_col.update_one({"_id": new_admin_id}, {"$set": {"active": True}}, upsert=True)
        await message.reply_text(f"ইউজার `{new_admin_id}` সফলভাবে এডমিন হিসেবে নিযুক্ত হয়েছেন।")
    except ValueError:
        await message.reply_text("দয়া করে সঠিক নিউমেরিক আইডি দিন।")

@app.on_message(filters.command("deladmin") & filters.user(OWNER_ID))
async def del_admin(client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("ব্যবহারের নিয়ম:\n`/deladmin <ইউজার_আইডি>`")
    try:
        admin_id = int(args[1])
        result = await admins_col.delete_one({"_id": admin_id})
        if result.deleted_count > 0:
            await message.reply_text("এডমিনকে সফলভাবে অপসারণ করা হয়েছে।")
        else:
            await message.reply_text("এই আইডিটি এডমিন লিস্টে পাওয়া যায়নি।")
    except ValueError:
        await message.reply_text("দয়া করে সঠিক নিউমেরিক আইডি দিন।")

@app.on_message(filters.command("adminlist") & filters.user(OWNER_ID))
async def list_admins(client, message: Message):
    admins = admins_col.find({})
    text = f"👑 **প্রধান মালিক:** `{OWNER_ID}`\n\n👮‍♂️ **সহকারী এডমিনবৃন্দ:**\n"
    async for admin in admins:
        text += f"- `{admin['_id']}`\n"
    await message.reply_text(text)

# ================= ADMIN COMMANDS (Owner & Admins) =================

@app.on_message(filters.command("addfsub"))
async def add_fsub(client, message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        return await message.reply_text("ব্যবহারের নিয়ম:\n`/addfsub <চ্যানেল_আইডি> <রিকোয়েস্ট_লিংক>`")
    
    channel_id = args[1]
    invite_link = args[2]
    await fsub_col.update_one({"_id": channel_id}, {"$set": {"invite_link": invite_link}}, upsert=True)
    await message.reply_text("FSub চ্যানেল সফলভাবে যুক্ত হয়েছে।")

@app.on_message(filters.command("delfsub"))
async def del_fsub(client, message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("ব্যবহারের নিয়ম:\n`/delfsub <চ্যানেল_আইডি>`")
    
    channel_id = args[1]
    result = await fsub_col.delete_one({"_id": channel_id})
    if result.deleted_count > 0:
        await message.reply_text("চ্যানেলটি FSub তালিকা থেকে বাদ দেওয়া হয়েছে।")
    else:
        await message.reply_text("চ্যানেলটি খুঁজে পাওয়া যায়নি।")

@app.on_message(filters.command("fsublist"))
async def list_fsub(client, message: Message):
    if not await is_admin(message.from_user.id):
        return
    channels = fsub_col.find({})
    text = "**FSub চ্যানেল তালিকা:**\n\n"
    async for ch in channels:
        text += f"ID: `{ch['_id']}`\nLink: {ch['invite_link']}\n\n"
    await message.reply_text(text or "কোনো FSub চ্যানেল যুক্ত নেই।")

@app.on_message(filters.command("stats"))
async def stats_handler(client, message: Message):
    if not await is_admin(message.from_user.id):
        return
    total_users = await users_col.count_documents({})
    total_files = await files_col.count_documents({})
    await message.reply_text(f"📈 **বটের বর্তমান অবস্থা:**\n\n👥 মোট ইউজার: `{total_users}`\n📂 মোট সংরক্ষিত ফাইল: `{total_files}`")

@app.on_message(filters.command("broadcast"))
async def broadcast_handler(client, message: Message):
    if not await is_admin(message.from_user.id):
        return
    if not message.reply_to_message:
        return await message.reply_text("যে মেসেজটি ব্রডকাস্ট করতে চান সেটি রিপ্লাই করে `/broadcast` লিখুন।")
    
    broadcast_msg = message.reply_to_message
    await message.reply_text("ব্রডকাস্ট শুরু হয়েছে...")
    
    users = users_col.find({})
    success = 0
    failed = 0
    
    async for user in users:
        try:
            await broadcast_msg.copy(chat_id=user["_id"])
            success += 1
            await asyncio.sleep(0.3) # ফ্লাড এড়াতে সাময়িক বিরতি
        except Exception:
            failed += 1
            
    await message.reply_text(f"📢 **ব্রডকাস্ট সম্পন্ন হয়েছে!**\n\nসফল: `{success}` জন\nব্যর্থ: `{failed}` জন")

# ================= PUBLIC FILE STORING (সবার জন্য ফাইল সেভ করার সুবিধা) =================

@app.on_message((filters.document | filters.video | filters.audio | filters.photo) & filters.private)
async def store_file_public(client, message: Message):
    user_id = message.from_user.id
    
    # ফাইলের ধরন অনুযায়ী আইডি সংগ্রহ
    if message.document:
        file_id = message.document.file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.audio:
        file_id = message.audio.file_id
    else:
        file_id = message.photo[0].file_id if isinstance(message.photo, list) else message.photo.file_id

    file_key = generate_id()
    
    # ডাটাবেজে ফাইল ও আপলোডারের তথ্য সেভ করা
    await files_col.insert_one({
        "_id": file_key,
        "file_id": file_id,
        "uploader_id": user_id
    })
    
    bot_username = (await client.get_me()).username
    share_link = f"https://t.me/{bot_username}?start={file_key}"
    
    await message.reply_text(
        f"📥 **আপনার ফাইলটি ডাটাবেজে সফলভাবে সংরক্ষিত হয়েছে!**\n\n🔗 **শেয়ার লিংক:**\n`{share_link}`",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("শেয়ার করুন 🚀", url=f"https://telegram.me/share/url?url={share_link}")
        ]])
    )

# ================= START COMMAND & FILE DELIVERY =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message: Message):
    user_id = message.from_user.id
    
    # ইউজার ডাটাবেজে সংরক্ষণ
    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"username": message.from_user.username}},
        upsert=True
    )

    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("স্বাগতম! আমি একটি ফাইল স্টোর বট। এখানে আপনি যেকোনো ফাইল পাঠিয়ে নিজের শেয়ারিং লিংক তৈরি করে নিতে পারবেন।")

    file_key = args[1]

    # FSub চ্যানেলসমূহ চেক করা
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

    # যদি কোনো চ্যানেলে রিকোয়েস্ট পাঠানো বাকি থাকে
    if unjoined_channels:
        buttons = []
        for index, ch in enumerate(unjoined_channels, start=1):
            buttons.append([InlineKeyboardButton(f"চ্যানেল {index}-এ জয়েন রিকোয়েস্ট পাঠান", url=ch["invite_link"])])
        
        try_again_url = f"https://t.me/{(await client.get_me()).username}?start={file_key}"
        buttons.append([InlineKeyboardButton("আমি রিকোয়েস্ট পাঠিয়েছি (ফাইল দিন)", url=try_again_url)])
        
        return await message.reply_text(
            "⚠️ **ফাইলটি পেতে আপনাকে আমাদের চ্যানেলে জয়েন রিকোয়েস্ট পাঠাতে হবে!**\n\nনিচের বাটনগুলো ব্যবহার করে রিকোয়েস্ট পাঠান এবং তারপর 'ফাইল দিন' বাটনে ক্লিক করুন।",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    # ফাইল ডাটাবেজ থেকে খুঁজে পাঠানো
    file_data = await files_col.find_one({"_id": file_key})
    if file_data:
        try:
            await client.send_cached_media(
                chat_id=message.chat.id,
                file_id=file_data["file_id"],
                caption="📤 **আপনার ফাইলটি নিচে দেওয়া হলো।**"
            )
        except Exception as e:
            await message.reply_text(f"ফাইলটি পাঠাতে সমস্যা হচ্ছে: {e}")
    else:
        await message.reply_text("❌ ফাইলটি ডাটাবেজে পাওয়া যায়নি বা মুছে ফেলা হয়েছে।")

if __name__ == "__main__":
    app.run()
