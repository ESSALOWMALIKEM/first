import telebot
from keep_alive import keep_alive

# BotFather'dan aldığınız API token'ını buraya tırnak içinde yapıştırın
TOKEN = "8717532319:AAETVAbBO5V1f6HogI6m_BchhPIxxaGJ1ic"

keep_alive()

# Bot nesnesini oluşturuyoruz
bot = telebot.TeleBot(TOKEN)

# /start veya /help komutları gönderildiğinde çalışacak fonksiyon
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Merhaba! Ben basit bir Telegram botuyum. Bana mesaj göndermeyi dene!")

# Gelen diğer tüm metin mesajlarını yakalayacak ve cevaplayacak fonksiyon
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    cevap = f"Şunu yazdın: {message.text}"
    bot.reply_to(message, cevap)

# Botun kapanmadan sürekli olarak yeni mesajları beklemesini sağlar
print("Bot başarıyla başlatıldı ve mesajları bekliyor...")
bot.infinity_polling()
