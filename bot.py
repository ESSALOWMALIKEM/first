import asyncio
import logging
import random
import time
from datetime import datetime, timedelta

import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import Message
from keep_alive import keep_alive
import os

# --- AYARLAR ---
# Bu bilgileri Render Environment Variables kısmından çekmek daha güvenlidir.
# Kodun içine de yazabilirsin ama önerilmez.
API_TOKEN = os.getenv("API_TOKEN", "8538506186:AAGSX9ZceJ0Kh_Nzeze9v8k2VHDUlZjTTSo") 
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:4OWUEBtffwv2lc65YQlDEg9danw4LLQi@dpg-d521qmv5r7bs73fqsq50-a/ghostdb_kt36")

# Botun tetiklenme ihtimali (0.1 = %10 şansla cevap verir)
REPLY_CHANCE = 0.15 
# Botun konuşmaya başlaması için gereken minimum mesaj sayısı
ACTIVATION_THRESHOLD = 7
# Sıkılma süresi (saniye cinsinden, 1 saat = 3600)
BOREDOM_TIMEOUT = 10 

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
DB_POOL = None

# --- GRUP DURUM TAKİBİ (HAFIZADA) ---
class ChatState:
    def __init__(self):
        self.message_count = 0
        self.last_message_time = time.time()
        self.active = False
        self.bored_msg_sent = False

# {chat_id: ChatState}
chat_states = {}

# --- VERİTABANI İŞLEMLERİ ---
async def init_db(pool):
    async with pool.acquire() as connection:
        # Mesajları saklayacağımız tablo
        # chat_id: Mesajın hangi gruptan geldiği (Grupları karıştırmamak için)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS group_messages (
                id SERIAL PRIMARY KEY, 
                chat_id BIGINT, 
                message_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

async def save_message_to_db(chat_id: int, text: str):
    """Mesajı veritabanına kaydeder."""
    async with DB_POOL.acquire() as conn:
        await conn.execute(
            "INSERT INTO group_messages (chat_id, message_text) VALUES ($1, $2)",
            chat_id, text
        )

async def get_random_message(chat_id: int):
    """Veritabanından o gruba ait rastgele bir mesaj çeker."""
    async with DB_POOL.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT message_text FROM group_messages WHERE chat_id = $1 ORDER BY RANDOM() LIMIT 1",
            chat_id
        )
        return row['message_text'] if row else None

# --- ARKA PLAN GÖREVİ: SIKILMA KONTROLÜ ---
async def boredom_checker():
    """Her dakika grupları kontrol eder, kimse yazmadıysa isyan eder."""
    while True:
        await asyncio.sleep(60)  # 1 dakika bekle
        now = time.time()
        
        # chat_states sözlüğünü kopyalayarak dönüyoruz ki işlem sırasında hata almayalım
        for chat_id, state in list(chat_states.items()):
            # Eğer son mesajdan bu yana 1 saat geçtiyse VE daha önce isyan etmediyse
            if (now - state.last_message_time > BOREDOM_TIMEOUT) and not state.bored_msg_sent:
                try:
                    await bot.send_message(chat_id, "🥱 Gelin artık sıkıldım...")
                    state.bored_msg_sent = True # Tekrar tekrar atmasın
                    state.active = False # Modu pasife çek
                    state.message_count = 0 # Sayacı sıfırla
                except Exception as e:
                    logging.error(f"Sıkılma mesajı atılamadı {chat_id}: {e}")

# --- HANDLERLAR ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("Selam! Ben bu grubu izliyorum ve sizin gibi konuşmayı öğreniyorum. 😎")

@dp.message(F.text)
async def chat_handler(message: Message):
    chat_id = message.chat.id
    text = message.text

    # 1. Mesajı veritabanına kaydet (Komut değilse ve çok kısa değilse)
    if not text.startswith("/") and len(text) > 2:
        await save_message_to_db(chat_id, text)

    # 2. Grup Durumunu Güncelle
    if chat_id not in chat_states:
        chat_states[chat_id] = ChatState()
    
    state = chat_states[chat_id]
    state.last_message_time = time.time()
    state.bored_msg_sent = False # Biri yazdı, sıkılma durumu iptal
    state.message_count += 1

    # 3. Aktivasyon Kontrolü (10 mesaj barajı)
    if state.message_count >= ACTIVATION_THRESHOLD:
        state.active = True

    # 4. Botun Cevap Vermesi
    # Eğer bot aktifse VE rastgele şans tutarsa
    if state.active and random.random() < REPLY_CHANCE:
        random_msg = await get_random_message(chat_id)
        if random_msg:
            # Gecikme efekti (İnsan gibi görünsün diye 1-3 saniye bekleme)
            await asyncio.sleep(random.randint(1, 3))
            # Mesaj sahibini yanıtlayarak cevap ver
            await message.reply(random_msg)

# --- BAŞLATMA ---
async def main():
    global DB_POOL
    
    # Web server'ı başlat (Render için)
    keep_alive()

    try:
        DB_POOL = await asyncpg.create_pool(dsn=DATABASE_URL)
        logging.info("Veritabanı bağlantısı başarılı.")
        await init_db(DB_POOL)
    except Exception as e:
        logging.critical(f"Veritabanı hatası: {e}")
        return

    # Sıkılma kontrolcüsünü arka planda başlat
    asyncio.create_task(boredom_checker())

    logging.info("Bot başlatılıyor...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot durduruldu.")
