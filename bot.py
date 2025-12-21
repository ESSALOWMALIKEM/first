import asyncio
import logging
import json
import os
import time
import aiohttp
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command, StateFilter
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
    waiting_for_confirmation = State() # Onay veya buton ekleme beklentisi
    waiting_for_button_input = State() # Buton linki beklentisi

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
    # İstatistik butonu kaldırıldı, sadece Duyuru var
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Duyuru Yap", callback_data="make_announcement")]
    ])
    await message.answer("🛠 <b>Ghost Ai Admin Paneli</b>", reply_markup=kb)

# --- ADMIN DUYURU İŞLEMLERİ (GÜNCELLENDİ) ---

@router.callback_query(F.data == "make_announcement")
async def start_announcement(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Duyuru metnini (veya resmini) gönderin. (HTML formatı desteklenir)")
    await state.set_state(AdminStates.waiting_for_announcement)
    await call.answer()

@router.message(AdminStates.waiting_for_announcement)
async def process_announcement_content(message: Message, state: FSMContext):
    # İçeriği kaydet
    content = {"text": message.html_text, "photo": message.photo[-1].file_id if message.photo else None}
    await state.update_data(announcement=content)
    
    # Seçim Butonlarını Göster
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Gönder", callback_data="send_now"),
         InlineKeyboardButton(text="➕ Buton Ekle", callback_data="add_btn")]
    ])
    
    await message.answer("✅ İçerik alındı. Ne yapmak istersiniz?", reply_markup=kb)
    await state.set_state(AdminStates.waiting_for_confirmation)

@router.callback_query(AdminStates.waiting_for_confirmation, F.data == "add_btn")
async def ask_for_button(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Butonu şu formatta gönderin:\n<code>Buton Yazısı - https://link.com</code>")
    await state.set_state(AdminStates.waiting_for_button_input)

@router.callback_query(AdminStates.waiting_for_confirmation, F.data == "send_now")
async def send_announcement_now(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("🚀 Duyuru gönderiliyor...")
    await perform_broadcast(call.message, state, None)

@router.message(AdminStates.waiting_for_button_input)
async def process_button_and_send(message: Message, state: FSMContext):
    btn_data = None
    if "-" in message.text:
        txt, url = message.text.split("-", 1)
        btn_data = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=txt.strip(), url=url.strip())]])
    
    await message.answer("🚀 Buton eklendi, duyuru gönderiliyor...")
    await perform_broadcast(message, state, btn_data)

async def perform_broadcast(message_obj, state, reply_markup):
    data = await state.get_data()
    content = data.get('announcement')
    
    users = list(user_data.keys())
    count = 0
    blocked_count = 0
    
    for user_id in users:
        try:
            if content['photo']:
                await bot.send_photo(user_id, content['photo'], caption=content['text'], reply_markup=reply_markup)
            else:
                await bot.send_message(user_id, content['text'], reply_markup=reply_markup)
            count += 1
            await asyncio.sleep(0.05) # Flood wait önlemek için minik bekleme
        except Exception: 
            blocked_count += 1
            continue
    
    await message_obj.answer(f"✅ Duyuru tamamlandı.\nBaşarılı: {count}\nBaşarısız: {blocked_count}")
    await state.clear()

# --- ANA MESAJ DÖNGÜSÜ ---

# StateFilter(None) ekledik: Eğer admin duyuru modundaysa bu handler çalışmaz.
# Böylece duyuru metinleri Llama API'a gitmez.
@router.message(F.text, StateFilter(None))
async def handle_message(message: Message):
    # Typing action gönder
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Bekleme mesajı (opsiyonel, typing olduğu için kaldırılabilir ama kalsın istersen)
    # wait_msg = await message.answer("👻") # İstersen bunu açabilirsin ama typing yeterli oluyor genelde.
    
    response = await ask_llama(message.from_user.id, message.text)
    
    # Cevabı gönder
    await message.answer(response)

dp.include_router(router)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
