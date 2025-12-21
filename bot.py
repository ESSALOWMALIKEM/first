import asyncio
import logging
import os
import asyncpg
import httpx
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.chat_action import ChatActionSender

# --- AYARLAR (Config) ---
# Güvenlik için bunları ortam değişkenlerinden (Environment Variables) çekmek en iyisidir
API_TOKEN = '7822880957:AAHk1St7_PxC0zVKmaMRpaHSado_5wsO-xM'
ADMIN_ID = 7877979174
DATABASE_URL = "postgresql://user:4OWUEBtffwv2lc65YQlDEg9danw4LLQi@dpg-d521qmv5r7bs73fqsq50-a/ghostdb_kt36"

LLAMA_KEY = 'ad33259d-2144-4a10-9dd9-4127d40ce933'
LLAMA_URL = 'https://api.sambanova.ai/v1/chat/completions'

SYSTEM_PROMPT = (
    "You are Ghost AI, a highly advanced assistant. "
    "Rule 1: Detect user's language and respond in it. "
    "Rule 2: Use professional yet friendly tone. "
    "Rule 3: Use Markdown for structure (bold, code blocks)."
)

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- BOT BAŞLATMA ---
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

class BroadcastState(StatesGroup):
    waiting_for_content = State()

# --- VERİTABANI YÖNETİMİ (Connection Pool) ---
class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(DATABASE_URL)
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    join_date TIMESTAMP DEFAULT NOW(),
                    message_count INT DEFAULT 0,
                    is_banned BOOLEAN DEFAULT FALSE
                )
            ''')

    async def register_user(self, user_id):
        async with self.pool.acquire() as conn:
            await conn.execute('INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING', user_id)

    async def increment_stats(self, user_id):
        async with self.pool.acquire() as conn:
            await conn.execute('UPDATE users SET message_count = message_count + 1 WHERE user_id = $1', user_id)

    async def get_stats(self, user_id):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow('SELECT join_date, message_count FROM users WHERE user_id = $1', user_id)

    async def get_all_users(self):
        async with self.pool.acquire() as conn:
            return await conn.fetch('SELECT user_id FROM users')

db = Database()
user_histories = {}

# --- AI MANTIĞI ---
async def ask_llama(user_id, prompt):
    if user_id not in user_histories:
        user_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    user_histories[user_id].append({"role": "user", "content": prompt})
    
    # Hafızayı sınırla (Sistem mesajı + son 10 mesaj)
    if len(user_histories[user_id]) > 11:
        user_histories[user_id] = [user_histories[user_id][0]] + user_histories[user_id][-10:]

    async with httpx.AsyncClient(timeout=100.0) as client:
        try:
            headers = {"Authorization": f"Bearer {LLAMA_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "Meta-Llama-3.3-70B-Instruct",
                "messages": user_histories[user_id],
                "temperature": 0.7,
                "max_completion_tokens": 2048
            }
            resp = await client.post(LLAMA_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            
            answer = data['choices'][0]['message']['content']
            user_histories[user_id].append({"role": "assistant", "content": answer})
            return answer

        except Exception as e:
            logger.error(f"Llama API Hatası: {e}")
            return "❌ Şu anda cevap veremiyorum, lütfen biraz sonra tekrar dene."

# --- HANDLERS ---
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await db.register_user(message.from_user.id)
    user_histories[message.from_user.id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    welcome = (
        "👻 *Ghost AI'a Hoş Geldiniz!*\n\n"
        "Sizinle istediğiniz dilde konuşabilirim. Sorularınızı bekliyorum.\n\n"
        "🛠 *Komutlar:*\n"
        "└ /me - Profilin\n"
        "└ /clear - Hafızayı temizle"
    )
    await message.answer(welcome, parse_mode="Markdown")

@router.message(Command("clear"))
async def cmd_clear(message: types.Message):
    user_histories[message.from_user.id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    await message.answer("🧹 *Hafıza başarıyla temizlendi.*", parse_mode="Markdown")

@router.message(Command("me"))
async def cmd_me(message: types.Message):
    stats = await db.get_stats(message.from_user.id)
    if stats:
        text = (
            f"👤 *Kullanıcı Profili*\n\n"
            f"🆔 *ID:* `{message.from_user.id}`\n"
            f"📅 *Kayıt:* {stats['join_date'].strftime('%d/%m/%Y')}\n"
            f"💬 *Mesaj Sayısı:* {stats['message_count']}"
        )
        await message.answer(text, parse_mode="Markdown")

@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    users = await db.get_all_users()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Duyuru Gönder", callback_data="broadcast_start")]
    ])
    await message.answer(f"📊 *Admin Paneli*\n\nToplam Kullanıcı: {len(users)}", reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data == "broadcast_start")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📢 Duyuru metnini gönderin (İptal için /cancel)")
    await state.set_state(BroadcastState.waiting_for_content)
    await callback.answer()

@router.message(BroadcastState.waiting_for_content)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        return await message.answer("İptal edildi.")

    users = await db.get_all_users()
    count = 0
    await message.answer("🚀 Duyuru başlatıldı...")

    for row in users:
        try:
            if message.photo:
                await bot.send_photo(row['user_id'], message.photo[-1].file_id, caption=message.caption)
            else:
                await bot.send_message(row['user_id'], message.text)
            count += 1
            await asyncio.sleep(0.05) # Rate limit koruması
        except Exception:
            continue

    await message.answer(f"✅ Duyuru tamamlandı. {count} kişiye ulaşıldı.")
    await state.clear()

@router.message()
async def handle_message(message: types.Message):
    if not message.text or message.text.startswith('/'): return
    
    # Veritabanı istatistiğini güncelle
    await db.increment_stats(message.from_user.id)

    # "Yazıyor..." aksiyonu göster
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        response = await ask_llama(message.from_user.id, message.text)
        
        try:
            await message.reply(response, parse_mode="Markdown")
        except Exception:
            # Markdown hatası olursa düz metin gönder
            await message.reply(response)

# --- ANA DÖNGÜ ---
async def main():
    logger.info("Bot başlatılıyor...")
    await db.connect()
    # keep_alive() # Eğer Replit kullanıyorsan aktif et
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot durduruldu.")
