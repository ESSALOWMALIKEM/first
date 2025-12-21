import asyncio
import logging
import asyncpg
import httpx
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

GEMINI_KEY = 'AIzaSyD5AmaCXq29nbwU6e0j-IGF6zh26FkdsMY'
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"

LLAMA_KEY = 'ad33259d-2144-4a10-9dd9-4127d40ce933'
LLAMA_URL = 'https://api.sambanova.ai/v1/chat/completions'

SYSTEM_PROMPT = "Seniň adyň Ghost AI. Sen örän peýdaly we akylly emeli intellekt kömekçisi. Ähli soraglara diňe Türkmen dilinde, örän doly we düşnükli jogap bermeli. Markdown formatyny ulanyp bilersiň."

# --- INITIALIZATION ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)
keep_alive()

class BroadcastState(StatesGroup):
    waiting_for_content = State()

# --- DATABASE FUNCTIONS ---
async def get_db_conn():
    return await asyncpg.connect(DATABASE_URL)

async def init_db():
    conn = await get_db_conn()
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            model_name TEXT DEFAULT 'gemini'
        )
    ''')
    await conn.close()

async def get_user_model(user_id):
    conn = await get_db_conn()
    row = await conn.fetchrow('SELECT model_name FROM users WHERE user_id = $1', user_id)
    if not row:
        await conn.execute('INSERT INTO users(user_id) VALUES($1)', user_id)
        await conn.close()
        return 'gemini'
    await conn.close()
    return row['model_name']

async def update_user_model(user_id, new_model):
    conn = await get_db_conn()
    await conn.execute('UPDATE users SET model_name = $1 WHERE user_id = $2', new_model, user_id)
    await conn.close()

# --- AI LOGIC ---
async def ask_ai(prompt, model):
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            if model == 'gemini':
                payload = {
                    "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\nUlanyjy: {prompt}"}]}],
                    "safetySettings": [{"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"}]
                }
                resp = await client.post(GEMINI_URL, json=payload)
                data = resp.json()
                if 'candidates' in data and data['candidates']:
                    return data['candidates'][0]['content']['parts'][0]['text']
                else:
                    return "⚠️ Gemini jogap berip bilmedi. Biraz soňrak synanyşyň ýa-da /change ýazyň."
            
            else: # Llama (SambaNova)
                headers = {"Authorization": f"Bearer {LLAMA_KEY}", "Content-Type": "application/json"}
                payload = {
                    "model": "Meta-Llama-3.3-70B-Instruct",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    "max_completion_tokens": 5000
                }
                resp = await client.post(LLAMA_URL, json=payload, headers=headers)
                data = resp.json()
                return data['choices'][0]['message']['content']
                
        except Exception as e:
            logging.error(f"AI Error: {e}")
            return f"❌ Ýalňyşlyk ýüze çykdy. Modeli üýtgedip görüň."

# --- COMMANDS ---
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await get_user_model(message.from_user.id)
    welcome = "👻 **Ghost AI-a Hoş Geldiňiz!**\n\nMen size Türkmen dilinde kömek edýän emeli intellekt. \n\n🤖 **Häzirki model:** `Gemini`\n🔄 Modeli üýtgetmek üçin: /change"
    await message.answer(welcome, parse_mode="Markdown")

@router.message(Command("change"))
async def cmd_change(message: types.Message):
    current = await get_user_model(message.from_user.id)
    new_model = 'llama' if current == 'gemini' else 'gemini'
    await update_user_model(message.from_user.id, new_model)
    await message.answer(f"✅ Model üýtgedildi! Täze model: **{new_model.upper()}**", parse_mode="Markdown")

@router.message(Command("report"))
async def cmd_report(message: types.Message):
    await message.answer("📩 Şikaýatyňyz adminlere ýetirildi. Sag boluň!")

@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    conn = await get_db_conn()
    count = await conn.fetchval('SELECT COUNT(*) FROM users')
    await conn.close()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Duyuru Iber", callback_data="broadcast_start")]
    ])
    await message.answer(f"📊 **Admin Panel**\n\nUlanyjy sany: {count}", reply_markup=kb, parse_mode="Markdown")

# --- BROADCAST LOGIC (ADMIN) ---
@router.callback_query(F.data == "broadcast_start")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📢 **Duyuru habaryny iberiň.**\n\n(Surat, tekst ýa-da HTML formatynda bolup biler. Düwme goşmak üçin tekstiň ahyryna `| Düwme Ady | Link` görnüşinde ýazyň)")
    await state.set_state(BroadcastState.waiting_for_content)
    await callback.answer()

@router.message(BroadcastState.waiting_for_content)
async def do_broadcast(message: types.Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        return await message.answer("Lagal edildi.")

    conn = await get_db_conn()
    users = await conn.fetch('SELECT user_id FROM users')
    await conn.close()
    
    # Buton ayrıştırma mantığı (basit)
    kb = None
    text_to_send = message.text or message.caption
    if text_to_send and "|" in text_to_send:
        parts = text_to_send.split("|")
        text_to_send = parts[0].strip()
        btn_text = parts[1].strip()
        btn_url = parts[2].strip()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn_text, url=btn_url)]])

    success = 0
    for row in users:
        try:
            if message.photo:
                await bot.send_photo(row['user_id'], message.photo[-1].file_id, caption=text_to_send, parse_mode="HTML", reply_markup=kb)
            else:
                await bot.send_message(row['user_id'], text_to_send, parse_mode="HTML", reply_markup=kb)
            success += 1
        except: continue
    
    await message.answer(f"✅ Duyuru {success} adama üstünlikli ugradyldy.")
    await state.clear()

# --- GENERAL MESSAGE HANDLER (AI) ---
@router.message()
async def handle_ai_request(message: types.Message, state: FSMContext):
    # Eğer kullanıcı duyuru modundaysa AI cevap vermesin
    current_state = await state.get_state()
    if current_state == BroadcastState.waiting_for_content:
        return 

    if not message.text or message.text.startswith('/'): return
    
    wait_msg = await message.answer("⏳ Ghost AI oýlanýar...")
    user_model = await get_user_model(message.from_user.id)
    
    ai_response = await ask_ai(message.text, user_model)
    
    await wait_msg.delete()
    # Markdown parse_mode kullanarak AI'dan gelen **bold** gibi yapıları gösteriyoruz
    try:
        await message.answer(ai_response, parse_mode="Markdown")
    except:
        # Eğer Markdown hatası verirse düz metin gönder
        await message.answer(ai_response)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
