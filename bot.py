import asyncio
import logging
import json
import os
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# --- AYARLAR ---
API_TOKEN = '7822880957:AAHk1St7_PxC0zVKmaMRpaHSado_5wsO-xM' 
LLAMA_API_KEY = 'ad33259d-2144-4a10-9dd9-4127d40ce933'
LLAMA_API_URL = 'https://api.sambanova.ai/v1/chat/completions'
MEMORY_FILE = 'ghost_memory.json'

# Loglama
logging.basicConfig(level=logging.INFO)

# Bot Ayarları (Markdown formatını aktif ettik)
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()
router = Router()

# --- HAFIZA SİSTEMİ (Basit) ---
def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_memory(data):
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

user_data = load_memory()

# --- YAPAY ZEKA İLETİŞİMİ ---
async def ask_llama(user_id, message_text):
    uid = str(user_id)
    
    # Kullanıcı kaydı yoksa oluştur
    if uid not in user_data:
        user_data[uid] = []

    # Geçmişi hazırla (Son 15 mesajı hatırla)
    history = user_data[uid][-15:]
    
    # Sistem Mesajı (Botun Kimliği)
    messages = [{
        "role": "system", 
        "content": "Senin adın Ghost Ai. Türkçe konuşan, yardımsever ve zeki bir asistansın. Cevaplarında önemli yerleri **kalın** yazarak vurgula."
    }]
    
    messages.extend(history)
    messages.append({"role": "user", "content": message_text})

    payload = {
        "model": "Meta-Llama-3.3-70B-Instruct",
        "messages": messages,
        "max_completion_tokens": 4096,
        "temperature": 0.7
    }
    
    headers = {"Authorization": f"Bearer {LLAMA_API_KEY}", "Content-Type": "application/json"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(LLAMA_API_URL, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    ai_response = result['choices'][0]['message']['content']
                    
                    # Hafızaya kaydet
                    user_data[uid].append({"role": "user", "content": message_text})
                    user_data[uid].append({"role": "assistant", "content": ai_response})
                    save_memory(user_data)
                    
                    return ai_response
                else:
                    logging.error(f"API Hatası: {resp.status}")
                    return "⚠️ Bağlantı hatası oluştu, lütfen tekrar dene."
    except Exception as e:
        logging.error(f"Hata: {e}")
        return "⚠️ Bir hata oluştu."

# --- HANDLERS (Komutlar ve Mesajlar) ---

@router.message(Command("start"))
async def start_command(message: Message):
    # Hafızayı temizle ki yeni sohbete başlasın
    uid = str(message.from_user.id)
    user_data[uid] = []
    save_memory(user_data)
    await message.answer("👻 **Ghost Ai** çevrimiçi.\nSenin için ne yapabilirim?")

@router.message(F.text)
async def chat_handler(message: Message):
    # 1. "Yazıyor..." eylemini gönder (Sürekli görünmesi için döngüye gerek yok, Telegram 5sn gösterir)
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # 2. Yapay zekadan cevap al
    response = await ask_llama(message.from_user.id, message.text)
    
    # 3. Cevabı gönder
    # Markdown modunda bazı özel karakterler hata verebilir, basit try-except ile koruyalım
    try:
        await message.answer(response)
    except Exception:
        # Eğer Markdown formatı bozuk gelirse düz metin olarak gönder
        await message.answer(response, parse_mode=None)

# --- BAŞLATMA ---
async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
