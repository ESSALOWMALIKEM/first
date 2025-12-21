import asyncio
import logging
import asyncpg
import httpx
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from keep_alive import keep_alive

# --- KONFİGURASYON ---
API_TOKEN = '7822880957:AAHk1St7_PxC0zVKmaMRpaHSado_5wsO-xM'
ADMIN_ID = 7877979174
DATABASE_URL = "postgresql://user:4OWUEBtffwv2lc65YQlDEg9danw4LLQi@dpg-d521qmv5r7bs73fqsq50-a/ghostdb_kt36"

# Llama API
LLAMA_KEY = 'ad33259d-2144-4a10-9dd9-4127d40ce933'
LLAMA_URL = 'https://api.sambanova.ai/v1/chat/completions'

# Sistem Talimatı
SYSTEM_PROMPT = "Seniň adyň Ghost AI. Sen örän peýdaly we akylly emeli intellekt kömekçisi. Ähli soraglara diňe Türkmen dilinde jogap ber. Jogaplaryňy Telegram Markdown formatyna laýyklykda ber."

# --- GLOBAL VARIABLES ---
# Hafıza için basit bir sözlük (Prodüksiyonda Redis önerilir ama bu işini görür)
user_histories = {} 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)
keep_alive()

class BroadcastState(StatesGroup):
    waiting_for_content = State()

# --- DATABASE ---
async def get_db_conn():
    return await asyncpg.connect(DATABASE_URL)

async def init_db():
    conn = await get_db_conn()
    # Users tablosuna message_count ekledik
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            join_date TIMESTAMP DEFAULT NOW(),
            message_count INT DEFAULT 0
        )
    ''')
    await conn.close()

async def register_user(user_id):
    conn = await get_db_conn()
    await conn.execute('INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING', user_id)
    await conn.close()

async def increment_msg_count(user_id):
    conn = await get_db_conn()
    await conn.execute('UPDATE users SET message_count = message_count + 1 WHERE user_id = $1', user_id)
    await conn.close()

async def get_user_stats(user_id):
    conn = await get_db_conn()
    row = await conn.fetchrow('SELECT join_date, message_count FROM users WHERE user_id = $1', user_id)
    await conn.close()
    return row

# --- AI LOGIC (MEMORY ENABLED) ---
async def ask_llama(user_id, prompt):
    # 1. Kullanıcının geçmişini al, yoksa oluştur
    if user_id not in user_histories:
        user_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # 2. Yeni mesajı geçmişe ekle
    user_histories[user_id].append({"role": "user", "content": prompt})
    
    # 3. Hafızayı çok şişirmemek için son 10 mesajı tut (System prompt hariç)
    # [System, ...son 10 mesaj...]
    if len(user_histories[user_id]) > 12:
        user_histories[user_id] = [user_histories[user_id][0]] + user_histories[user_id][-10:]

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            headers = {"Authorization": f"Bearer {LLAMA_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "Meta-Llama-3.3-70B-Instruct",
                "messages": user_histories[user_id], # Tüm geçmişi gönderiyoruz
                "max_completion_tokens": 3000
            }
            resp = await client.post(LLAMA_URL, json=payload, headers=headers)
            data = resp.json()
            answer = data['choices'][0]['message']['content']
            
            # 4. Asistanın cevabını da hafızaya ekle
            user_histories[user_id].append({"role": "assistant", "content": answer})
            
            return answer
        except Exception as e:
            logging.error(f"Llama Error: {e}")
            return "❌ Bagyşlaň, bir ýalňyşlyk boldy. /clear ýazyp hafızany arassalaň."

# --- COMMANDS ---
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await register_user(message.from_user.id)
    # Hafızayı sıfırla
    user_histories[message.from_user.id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    welcome = (
        "👻 **Ghost AI-a Hoş Geldiňiz!**\n\n"
        "Men Llama 3.3 modeli bilen işleýän we **siziň bilen eden gürrüňlerimi ýadymda saklaýan** akylly kömekçi.\n\n"
        "👤 Profil üçin: /me\n"
        "🧹 Ýady arassalamak üçin: /clear"
    )
    await message.answer(welcome, parse_mode="Markdown")

@router.message(Command("clear"))
async def cmd_clear(message: types.Message):
    user_histories[message.from_user.id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    await message.answer("🧹 **Sohbet ýady arassalandy!** Täze sahypadan başlaýarys.", parse_mode="Markdown")

@router.message(Command("me"))
async def cmd_me(message: types.Message):
    stats = await get_user_stats(message.from_user.id)
    if stats:
        date_str = stats['join_date'].strftime("%d.%m.%Y")
        msg_count = stats['message_count']
        text = (
            f"👤 **Ulanyjy Profili**\n\n"
            f"🆔 ID: `{message.from_user.id}`\n"
            f"📅 Goşulan senesi: {date_str}\n"
            f"💬 Jemi Mesaj: {msg_count}\n"
            f"🧠 Ýatda saklanan: {len(user_histories.get(message.from_user.id, []))} blog"
        )
        await message.answer(text, parse_mode="Markdown")

@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    conn = await get_db_conn()
    count = await conn.fetchval('SELECT COUNT(*) FROM users')
    total_msgs = await conn.fetchval('SELECT SUM(message_count) FROM users')
    await conn.close()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Duyuru Iber", callback_data="broadcast_start")]
    ])
    await message.answer(f"📊 **Admin Panel**\n\n👥 Ulanyjy sany: {count}\n💬 Jemi Mesajlar: {total_msgs}", reply_markup=kb)

# --- BROADCAST (AYNI KALDI) ---
@router.callback_query(F.data == "broadcast_start")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📢 **Duyuru habaryny ugradyň (Metin - Link formaty goldanýar).**")
    await state.set_state(BroadcastState.waiting_for_content)
    await callback.answer()

@router.message(BroadcastState.waiting_for_content)
async def do_broadcast(message: types.Message, state: FSMContext):
    conn = await get_db_conn()
    users = await conn.fetch('SELECT user_id FROM users')
    await conn.close()
    
    kb = None
    content_text = message.html_text if message.text else message.caption
    
    if content_text and " - http" in content_text:
        parts = content_text.split(" - http")
        content_text = parts[0]
        link_url = "http" + parts[1].strip()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Açmak 🌐", url=link_url)]])

    success = 0
    for row in users:
        try:
            if message.photo:
                await bot.send_photo(row['user_id'], message.photo[-1].file_id, caption=content_text, parse_mode="HTML", reply_markup=kb)
            else:
                await bot.send_message(row['user_id'], content_text, parse_mode="HTML", reply_markup=kb)
            success += 1
            await asyncio.sleep(0.05)
        except: continue
    
    await message.answer(f"✅ Duyuru {success} adama üstünlikli ugradyldy.")
    await state.clear()

# --- MESSAGE HANDLER ---
@router.message()
async def handle_ai_request(message: types.Message, state: FSMContext):
    if await state.get_state() == BroadcastState.waiting_for_content: return 
    if not message.text or message.text.startswith('/'): return
    
    # İstatistik güncelle
    await increment_msg_count(message.from_user.id)

    wait_msg = await message.answer("⏳ Ghost AI oýlanýar...")
    
    # Hafızalı AI fonksiyonunu çağır
    ai_response = await ask_llama(message.from_user.id, message.text)
    
    await wait_msg.delete()
    try:
        await message.answer(ai_response, parse_mode="Markdown")
    except:
        await message.answer(ai_response)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
