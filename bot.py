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
API_TOKEN = '8245564742:AAFKi1RI50y9dPJDUxZwEsOPTZMNBTLaSkM'
ADMIN_ID = 7877979174
DATABASE_URL = "postgresql://user:4OWUEBtffwv2lc65YQlDEg9danw4LLQi@dpg-d521qmv5r7bs73fqsq50-a/ghostdb_kt36"

# Llama (SambaNova) API
LLAMA_KEY = 'ad33259d-2144-4a10-9dd9-4127d40ce933'
LLAMA_URL = 'https://api.sambanova.ai/v1/chat/completions'

SYSTEM_PROMPT = "Seniň adyň Ghost AI. Sen örän peýdaly we akylly emeli intellekt kömekçisi. Ähli soraglara diňe Türkmen dilinde, örän doly we düşnükli jogap bermeli. Jogaplaryňy Telegram Markdown formatyna laýyklykda ber."

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
            user_id BIGINT PRIMARY KEY
        )
    ''')
    await conn.close()

async def register_user(user_id):
    conn = await get_db_conn()
    await conn.execute('INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING', user_id)
    await conn.close()

# --- AI LOGIC (ONLY LLAMA 3.3) ---
async def ask_llama(prompt):
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
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
            data = resp.json()
            return data['choices'][0]['message']['content']
        except Exception as e:
            logging.error(f"Llama Error: {e}")
            return "❌ Bagyşlaň, häzirki wagtda jogap berip bilmeýärin. Soňrak synanyşyň."

# --- COMMANDS ---
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await register_user(message.from_user.id)
    welcome = "👻 **Ghost AI-a Hoş Geldiňiz!**\n\nMen size Türkmen dilinde kömek edýän iň kämil emeli intellekt (Llama 3.3).\n\nSoragyňyzy ýazyň, men jogap bereýin!"
    await message.answer(welcome, parse_mode="Markdown")

@router.message(Command("report"))
async def cmd_report(message: types.Message):
    await message.answer("📩 Şikaýatyňyz we teklibiňiz hasaba alyndy. Admin size sereder.")

@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    conn = await get_db_conn()
    count = await conn.fetchval('SELECT COUNT(*) FROM users')
    await conn.close()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Duyuru Iber", callback_data="broadcast_start")]
    ])
    await message.answer(f"📊 **Admin Panel**\n\nJemi ulanyjy sany: {count}", reply_markup=kb)

# --- BROADCAST LOGIC (ADMIN) ---
@router.callback_query(F.data == "broadcast_start")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📢 **Duyuru habaryny ugradyň.**\n\nFormatlar:\n1. Diňe Metin (HTML goldanýar)\n2. Metin - Link (Düwme goşar)\n3. Suratly habar (Caption içine ýazyň)")
    await state.set_state(BroadcastState.waiting_for_content)
    await callback.answer()

@router.message(BroadcastState.waiting_for_content)
async def do_broadcast(message: types.Message, state: FSMContext):
    conn = await get_db_conn()
    users = await conn.fetch('SELECT user_id FROM users')
    await conn.close()
    
    kb = None
    # HTML formatyny we entities-leri gorap saklamak üçin message.html_text ulanýarys
    raw_content = message.html_text if message.text else message.caption_entities
    content_text = message.html_text if message.text else message.caption

    # Link ayrıştırma: "Metin - Link"
    if content_text and " - http" in content_text:
        parts = content_text.split(" - http")
        content_text = parts[0]
        link_url = "http" + parts[1].strip()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Açmak 🌐", url=link_url)]])

    success = 0
    for row in users:
        try:
            if message.photo:
                await bot.send_photo(
                    row['user_id'], 
                    message.photo[-1].file_id, 
                    caption=content_text, 
                    parse_mode="HTML", 
                    reply_markup=kb
                )
            else:
                await bot.send_message(
                    row['user_id'], 
                    content_text, 
                    parse_mode="HTML", 
                    reply_markup=kb
                )
            success += 1
            await asyncio.sleep(0.05) # Telegram limitlerine takylmazlyk üçin
        except: continue
    
    await message.answer(f"✅ Duyuru {success} adama üstünlikli ugradyldy.")
    await state.clear()

# --- MESSAGE HANDLER ---
@router.message()
async def handle_ai_request(message: types.Message, state: FSMContext):
    # Admin duyuru modundaysa AI-a gitmesin
    if await state.get_state() == BroadcastState.waiting_for_content:
        return 

    if not message.text or message.text.startswith('/'): return
    
    wait_msg = await message.answer("⏳ Ghost AI oýlanýar...")
    ai_response = await ask_llama(message.text)
    
    await wait_msg.delete()
    
    try:
        await message.answer(ai_response, parse_mode="Markdown")
    except:
        await message.answer(ai_response) # Formatda ýalňyşlyk bolsa düz ýazgy iber

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
