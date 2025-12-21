import asyncio
import logging
import asyncpg
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from keep_alive import keep_alive

# --- KONFİGURASYON ---
API_TOKEN = '7822880957:AAHk1St7_PxC0zVKmaMRpaHSado_5wsO-xM'
ADMIN_ID = 7877979174
DATABASE_URL = "postgresql://user:4OWUEBtffwv2lc65YQlDEg9danw4LLQi@dpg-d521qmv5r7bs73fqsq50-a/ghostdb_kt36"

# AI API Bilgileri
GEMINI_KEY = 'AIzaSyD5AmaCXq29nbwU6e0j-IGF6zh26FkdsMY'
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"

LLAMA_KEY = 'ad33259d-2144-4a10-9dd9-4127d40ce933'
LLAMA_URL = 'https://api.sambanova.ai/v1/chat/completions'

# Özel Prompt (Görünmez Talimat)
SYSTEM_PROMPT = "Seniň adyň Ghost AI. Sen örän peýdaly we akylly emeli intellekt kömekçisi. Ähli soraglara diňe Türkmen dilinde, doly we düşnükli jogap bermeli."

# --- LOGLAMA VE BOT ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
keep_alive()

class BroadcastState(StatesGroup):
    waiting_for_content = State()

# --- VERİTABANI İŞLEMLERİ ---
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            model_name TEXT DEFAULT 'gemini'
        )
    ''')
    await conn.close()

async def get_user_model(user_id):
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow('SELECT model_name FROM users WHERE user_id = $1', user_id)
    if not row:
        await conn.execute('INSERT INTO users(user_id) VALUES($1)', user_id)
        return 'gemini'
    return row['model_name']

async def update_user_model(user_id, new_model):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('UPDATE users SET model_name = $1 WHERE user_id = $2', new_model, user_id)
    await conn.close()

# --- AI API ÇAĞRILARI ---
async def ask_ai(prompt, model):
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            if model == 'gemini':
                payload = {"contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\nSorag: {prompt}"}]}]}
                resp = await client.post(GEMINI_URL, json=payload)
                return resp.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                headers = {"Authorization": f"Bearer {LLAMA_KEY}", "Content-Type": "application/json"}
                payload = {
                    "model": "Meta-Llama-3.3-70B-Instruct",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    "max_completion_tokens": 4000
                }
                resp = await client.post(LLAMA_URL, json=payload, headers=headers)
                return resp.json()['choices'][0]['message']['content']
        except Exception as e:
            return f"Bagyşlaň, häzirki wagtda jogap berip bilmeýärin. (Error: {e})"

# --- KOMUTLAR ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await get_user_model(message.from_user.id) # Kayıt et
    welcome_text = "👋 **Salam! Men Ghost AI.**\n\nSize Türkmen dilinde kömek edip bilerin. Häzirki wagtda **Gemini** modelini ulanýarsyňyz.\n\nModeli üýtgetmek üçin /change ýazyň."
    await message.answer(welcome_text, parse_mode="Markdown")

@dp.message(Command("change"))
async def cmd_change(message: types.Message):
    current = await get_user_model(message.from_user.id)
    new_model = 'llama' if current == 'gemini' else 'gemini'
    await update_user_model(message.from_user.id, new_model)
    await message.answer(f"✅ Model üýtgedildi! Täze model: **{new_model.upper()}**", parse_mode="Markdown")

@dp.message(Command("report"))
async def cmd_report(message: types.Message):
    await message.answer("⚠️ Haýyş, şikaýatyňyzy ýa-da teklibiňizi şu ýere ýazyň. Admin size sereder.")

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    conn = await asyncpg.connect(DATABASE_URL)
    count = await conn.fetchval('SELECT COUNT(*) FROM users')
    await conn.close()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Duyuru Yap", callback_data="broadcast")]
    ])
    await message.answer(f"📊 **Admin Panel**\n\nJemi ulanyjy: {count}", reply_markup=kb)

@dp.callback_query(F.data == "broadcast")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Habaryňyzy iberiň (Surat, tekst we link düwmesi üçin format: Tekst | LinkText | URL)")
    await state.set_state(BroadcastState.waiting_for_content)

@dp.message(BroadcastState.waiting_for_content)
async def do_broadcast(message: types.Message, state: FSMContext):
    conn = await asyncpg.connect(DATABASE_URL)
    users = await conn.fetch('SELECT user_id FROM users')
    await conn.close()
    
    count = 0
    for row in users:
        try:
            if message.photo:
                await bot.send_photo(row['user_id'], message.photo[-1].file_id, caption=message.caption, parse_mode="HTML")
            else:
                await bot.send_message(row['user_id'], message.text, parse_mode="HTML")
            count += 1
        except: continue
    
    await message.answer(f"✅ {count} ulanyja habar ugradyldy.")
    await state.clear()

@dp.message()
async def handle_message(message: types.Message):
    if not message.text or message.text.startswith('/'): return
    
    wait_msg = await message.answer("⏳ Ghost AI oýlanýar...")
    model = await get_user_model(message.from_user.id)
    response = await ask_ai(message.text, model)
    
    await wait_msg.delete()
    await message.answer(response)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
