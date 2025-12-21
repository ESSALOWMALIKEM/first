import asyncio
import logging
import json
import os
import time
import aiohttp
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

# --- YAPILANDIRMA ---
API_TOKEN = '7822880957:AAHk1St7_PxC0zVKmaMRpaHSado_5wsO-xM' # Senin API Key'in
LLAMA_API_KEY = 'ad33259d-2144-4a10-9dd9-4127d40ce933'
LLAMA_API_URL = 'https://api.sambanova.ai/v1/chat/completions'
SUPER_ADMIN_ID = 7877979174
DAILY_LIMIT = 25
MEMORY_FILE = 'user_memory.json'
# --------------------

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# Veritabanı (JSON) yükleme
def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_memory(data):
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

user_data = load_memory()

class AdminStates(StatesGroup):
    waiting_for_announcement = State()
    waiting_for_buttons = State()

# --- AI FONKSİYONU ---
async def ask_llama(user_id, message_text):
    global user_data
    uid = str(user_id)
    
    # Hafıza ve Limit Kontrolü
    today = time.strftime("%Y-%m-%d")
    if uid not in user_data:
        user_data[uid] = {"history": [], "last_date": today, "count": 0}
    
    if user_data[uid]["last_date"] != today:
        user_data[uid]["count"] = 0
        user_data[uid]["last_date"] = today
        
    if user_id != SUPER_ADMIN_ID and user_data[uid]["count"] >= DAILY_LIMIT:
        return "⚠️ Günlük 25 mesaj limitine ulaştınız. Yarın tekrar bekleriz!"

    # Mesaj Geçmişini Hazırla
    history = user_data[uid]["history"][-10:] # Son 10 mesajı hatırla
    messages = [{"role": "system", "content": "Senin adın Ghost Ai. Yardımsever bir yapay zekasın."}]
    for msg in history:
        messages.append(msg)
    messages.append({"role": "user", "content": message_text})

    payload = {
        "model": "Meta-Llama-3.3-70B-Instruct",
        "messages": messages,
        "max_completion_tokens": 10000
    }
    
    headers = {"Authorization": f"Bearer {LLAMA_API_KEY}", "Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        async with session.post(LLAMA_API_URL, json=payload, headers=headers) as resp:
            if resp.status == 200:
                result = await resp.json()
                ai_response = result['choices'][0]['message']['content']
                
                # Hafızaya Kaydet
                user_data[uid]["history"].append({"role": "user", "content": message_text})
                user_data[uid]["history"].append({"role": "assistant", "content": ai_response})
                user_data[uid]["count"] += 1
                save_memory(user_data)
                return ai_response
            else:
                return "❌ AI şu an yanıt veremiyor, lütfen teknik ekibe bildirin."

# --- KOMUTLAR ---

@router.message(Command("start"))
async def start(message: Message):
    await message.answer(f"👻 Merhaba! Ben <b>Ghost Ai</b>.\nBana dilediğin her şeyi sorabilirsin. Günlük limitin: {DAILY_LIMIT}")

@router.message(Command("clear"))
async def clear_memory(message: Message):
    uid = str(message.from_user.id)
    if uid in user_data:
        user_data[uid]["history"] = []
        save_memory(user_data)
        await message.answer("🧹 Hafızam senin için tamamen temizlendi!")

@router.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Duyuru Yap", callback_data="make_announcement")],
        [InlineKeyboardButton(text="📊 İstatistikler", callback_data="stats")]
    ])
    await message.answer("🛠 <b>Ghost Ai Admin Paneli</b>", reply_markup=kb)

# --- ADMIN İŞLEMLERİ ---

@router.callback_query(F.data == "make_announcement")
async def start_announcement(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Duyuru metnini gönderin. (Resim ekleyebilirsiniz. Kalın, İnce, Kod formatları desteklenir)")
    await state.set_state(AdminStates.waiting_for_announcement)

@router.message(AdminStates.waiting_for_announcement)
async def process_announcement(message: Message, state: FSMContext):
    content = {"text": message.html_text, "photo": message.photo[-1].file_id if message.photo else None}
    await state.update_data(announcement=content)
    await message.answer("Buton eklemek ister misiniz?\nFormat: `Buton Yazısı - https://link.com` (Yoksa 'hayır' yazın)")
    await state.set_state(AdminStates.waiting_for_buttons)

@router.message(AdminStates.waiting_for_buttons)
async def send_announcement(message: Message, state: FSMContext):
    data = await state.get_data()
    content = data['announcement']
    
    kb = None
    if "-" in message.text:
        btn_text, btn_url = message.text.split("-")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn_text.strip(), url=btn_url.strip())]])

    users = list(user_data.keys())
    count = 0
    for user_id in users:
        try:
            if content['photo']:
                await bot.send_photo(user_id, content['photo'], caption=content['text'], reply_markup=kb)
            else:
                await bot.send_message(user_id, content['text'], reply_markup=kb)
            count += 1
        except: continue
    
    await message.answer(f"✅ Duyuru {count} kişiye başarıyla gönderildi.")
    await state.clear()

# --- ANA MESAJ DÖNGÜSÜ ---

@router.message(F.text)
async def handle_message(message: Message):
    # Bekleme mesajı
    wait_msg = await message.answer("👻 <i>Ghost Ai düşünüyor...</i>")
    response = await ask_llama(message.from_user.id, message.text)
    await wait_msg.edit_text(response)

dp.include_router(router)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
