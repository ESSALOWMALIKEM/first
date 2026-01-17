import os
import logging
import tempfile
from pathlib import Path
from typing import Optional
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from telegram.constants import ParseMode
from keep_alive import keep_alive

keep_alive()

# --- Konfigürasyon ---
DEEPSEEK_API_KEY = "sk-aa03b3e8a6b24a539b279dc85dd93b2a"  # API key'iniz
TELEGRAM_BOT_TOKEN = "8570087251:AAFOTBbzJXFFHRx6h2gTm_StN39f3nX9_0A"  # BotFather'dan alınan token
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB maksimum dosya boyutu
SUPPORTED_EXTENSIONS = {'.txt', '.pdf', '.py', '.js', '.java', '.cpp', '.c', 
                        '.html', '.css', '.json', '.xml', '.csv', '.md', '.log'}

# Konuşma durumları
SELECTING_ACTION, READING_FILE = range(2)

# --- Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DeepSeek İstemcisi ---
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

# --- Dosya İşleme Fonksiyonları ---
async def download_file(file_id: str, context: ContextTypes.DEFAULT_TYPE) -> Optional[Path]:
    """Telegram'dan dosya indir"""
    try:
        file = await context.bot.get_file(file_id)
        temp_dir = tempfile.mkdtemp()
        file_path = Path(temp_dir) / f"downloaded_file"
        
        await file.download_to_drive(file_path)
        logger.info(f"Dosya indirildi: {file_path}")
        return file_path
    except Exception as e:
        logger.error(f"Dosya indirme hatası: {e}")
        return None

def read_file_content(file_path: Path) -> Optional[str]:
    """Dosya içeriğini oku"""
    try:
        if file_path.suffix.lower() == '.pdf':
            return read_pdf_file(file_path)
        else:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
    except Exception as e:
        logger.error(f"Dosya okuma hatası: {e}")
        return None

def read_pdf_file(file_path: Path) -> Optional[str]:
    """PDF dosyasını okumak için (basit versiyon)"""
    try:
        # PyPDF2 kullanarak
        try:
            import PyPDF2
            text = ""
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            return text
        except ImportError:
            # PyPDF2 yoksa alternatif
            return f"PDF dosyası: {file_path.name}\nPDF okumak için PyPDF2 kurulumu gerekli: pip install PyPDF2"
    except Exception as e:
        return f"PDF okuma hatası: {e}"

def is_file_supported(filename: str) -> bool:
    """Desteklenen dosya tipi mi kontrol et"""
    ext = Path(filename).suffix.lower()
    return ext in SUPPORTED_EXTENSIONS

# --- DeepSeek API Fonksiyonları ---
async def ask_deepseek(prompt: str, context: str = "") -> str:
    """DeepSeek'e soru sor"""
    try:
        messages = []
        
        if context:
            messages.append({
                "role": "system",
                "content": f"Aşağıdaki dosya içeriğini dikkate al:\n\n{context}\n\n"
            })
        
        messages.append({"role": "user", "content": prompt})
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            max_tokens=2000,
            temperature=0.7,
            stream=False
        )
        
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek API hatası: {e}")
        return f"API hatası: {str(e)}"

# --- Telegram Komut Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start komutu"""
    user = update.effective_user
    welcome_text = f"""
👋 Merhaba {user.first_name}!

🤖 **DeepSeek AI Bot**'a hoş geldiniz!

✨ **Özellikler:**
• 📝 Metin sohbeti
• 📁 Dosya okuma (TXT, PDF, Python, vs.)
• 💭 Bağlamlı konuşma
• 🔍 Kod analizi

📋 **Desteklenen Dosyalar:** {', '.join(SUPPORTED_EXTENSIONS)}

**Komutlar:**
/start - Botu başlat
/help - Yardım mesajı
/file - Dosya yükleme modu
/clear - Konuşma geçmişini temizle
/model - Model seçimi

📤 **Dosya göndermek için:** /file komutunu kullan veya direkt dosya gönder
"""
    
    keyboard = [
        [InlineKeyboardButton("📁 Dosya Yükle", callback_data="upload_file"),
         InlineKeyboardButton("ℹ️ Yardım", callback_data="help")],
        [InlineKeyboardButton("💬 Sohbet", callback_data="chat_mode"),
         InlineKeyboardButton("🔄 Model Değiştir", callback_data="change_model")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return SELECTING_ACTION

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help komutu"""
    help_text = """
📚 **Kullanım Kılavuzu**

**1. Metin Sohbeti:**
Direkt mesaj göndererek sohbet edebilirsiniz.

**2. Dosya Yükleme:**
• /file komutunu kullanın
• Veya direkt dosya gönderin
• Desteklenen formatlar: txt, pdf, py, js, html, css, json, xml, csv, md

**3. Dosya Analizi:**
Dosya yükledikten sonra:
1. Dosya içeriği okunur
2. Dosya hakkında soru sorabilirsiniz
3. Kod analizi yapabilirsiniz

**4. Komutlar:**
/start - Botu başlat
/help - Bu yardım mesajı
/file - Dosya yükleme modu
/clear - Geçmişi temizle
/model - Model seç (chat/coder)

**Örnek Kullanım:**
1. Bir Python dosyası gönderin
2. "Bu kod ne yapıyor?" diye sorun
3. Bot kodunuzu analiz etsin
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/file komutu - dosya yükleme modu"""
    text = """
📁 **Dosya Yükleme Modu**

Lütfen bir dosya gönderin veya işlemi iptal etmek için /cancel yazın.

**Desteklenen Dosyalar:**
• Metin dosyaları (.txt, .md, .log)
• Kod dosyaları (.py, .js, .java, .cpp, .html, .css)
• Veri dosyaları (.json, .xml, .csv)
• PDF dosyaları (.pdf)

**Boyut sınırı:** 10MB
"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return READING_FILE

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/clear komutu - geçmişi temizle"""
    if 'file_content' in context.user_data:
        del context.user_data['file_content']
    if 'current_file' in context.user_data:
        del context.user_data['current_file']
    
    await update.message.reply_text(
        "✅ Konuşma geçmişi ve dosya içeriği temizlendi!",
        parse_mode=ParseMode.MARKDOWN
    )

async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/model komutu - model seçimi"""
    keyboard = [
        [InlineKeyboardButton("💬 DeepSeek-Chat (Genel)", callback_data="model_chat")],
        [InlineKeyboardButton("💻 DeepSeek-Coder (Kodlama)", callback_data="model_coder")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🤖 **Model Seçimi**\n\n"
        "• 💬 DeepSeek-Chat: Genel sohbet, metin analizi\n"
        "• 💻 DeepSeek-Coder: Kod yazma, hata ayıklama, optimizasyon\n\n"
        "Geçerli model: " + context.user_data.get('model', 'deepseek-chat'),
        reply_markup=reply_markup
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """İşlemi iptal et"""
    await update.message.reply_text("İşlem iptal edildi.")
    return ConversationHandler.END

# --- Mesaj Handlers ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Metin mesajlarını işle"""
    user_message = update.message.text
    
    # İşlem modunda mı kontrol et
    if context.user_data.get('mode') == 'reading_file' and 'file_content' in context.user_data:
        # Dosya içeriği ile birlikte sor
        file_content = context.user_data['file_content']
        current_file = context.user_data.get('current_file', 'dosya')
        
        await update.message.reply_chat_action(action="typing")
        
        prompt = f"""Dosya: {current_file}

Dosya içeriği:
{file_content[:3000]}...

Kullanıcı sorusu: {user_message}

Lütfen dosya içeriğine dayanarak cevap ver."""
        
        response = await ask_deepseek(prompt)
        await update.message.reply_text(response)
    else:
        # Normal sohbet
        await update.message.reply_chat_action(action="typing")
        response = await ask_deepseek(user_message)
        await update.message.reply_text(response)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dosya mesajlarını işle"""
    document = update.message.document
    
    # Dosya boyutu kontrolü
    if document.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"❌ Dosya boyutu çok büyük! Maksimum: {MAX_FILE_SIZE/1024/1024:.1f}MB"
        )
        return
    
    # Dosya tipi kontrolü
    filename = document.file_name or "dosya"
    if not is_file_supported(filename):
        ext = Path(filename).suffix
        await update.message.reply_text(
            f"❌ Desteklenmeyen dosya formatı: {ext}\n"
            f"Desteklenenler: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
        return
    
    # Dosyayı indir
    await update.message.reply_text(f"📥 {filename} indiriliyor...")
    file_path = await download_file(document.file_id, context)
    
    if not file_path:
        await update.message.reply_text("❌ Dosya indirme başarısız!")
        return
    
    # Dosya içeriğini oku
    await update.message.reply_text("📖 Dosya içeriği okunuyor...")
    content = read_file_content(file_path)
    
    if not content:
        await update.message.reply_text("❌ Dosya okunamadı!")
        return
    
    # İçeriği kaydet
    context.user_data['file_content'] = content
    context.user_data['current_file'] = filename
    
    # Kullanıcıya bilgi ver
    preview = content[:500] + ("..." if len(content) > 500 else "")
    
    keyboard = [
        [InlineKeyboardButton("❓ Bu dosya ne hakkında?", callback_data="analyze_file")],
        [InlineKeyboardButton("📝 Kod analizi yap", callback_data="analyze_code")],
        [InlineKeyboardButton("🧹 Temizle", callback_data="clear_file")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = f"""
✅ **Dosya yüklendi:** {filename}

📊 **İstatistikler:**
• Boyut: {document.file_size} bayt
• Satır sayısı: {len(content.splitlines())}
• Karakter: {len(content)}

📋 **Önizleme:**
{preview}

Artık bu dosya hakkında sorular sorabilirsiniz veya yukarıdaki butonları kullanabilirsiniz.
"""
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Dosyayı temizle
    try:
        os.remove(file_path)
    except:
        pass

# --- Callback Query Handler ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buton tıklamalarını işle"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "upload_file":
        await query.edit_message_text(
            "📁 Lütfen bir dosya gönderin. Desteklenen formatlar: " + 
            ", ".join(SUPPORTED_EXTENSIONS)
        )
    
    elif data == "help":
        await help_command(update, context)
    
    elif data == "analyze_file":
        if 'file_content' in context.user_data:
            content = context.user_data['file_content']
            filename = context.user_data.get('current_file', 'dosya')
            
            prompt = f"""Şu dosyayı analiz et: {filename}

Dosya içeriği:
{content[:4000]}

Lütfen:
1. Bu dosyanın ne olduğunu açıkla
2. Ana fonksiyonlarını/özelliklerini listele
3. Varsa önemli noktaları belirt
4. Özetle"""
            
            await query.edit_message_text("🔍 Dosya analiz ediliyor...")
            response = await ask_deepseek(prompt)
            
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"📊 **{filename} Analizi:**\n\n{response}"
            )
    
    elif data == "analyze_code":
        if 'file_content' in context.user_data:
            content = context.user_data['file_content']
            filename = context.user_data.get('current_file', 'dosya')
            
            prompt = f"""Şu kodu analiz et: {filename}

Kod:
{content[:4000]}

Lütfen:
1. Kodun ne yaptığını açıkla
2. Potansiyel hataları kontrol et
3. İyileştirme önerileri ver
4. Karmaşıklık analizi yap"""
            
            await query.edit_message_text("🔍 Kod analiz ediliyor...")
            response = await ask_deepseek(prompt, context.user_data.get('file_content', ''))
            
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"💻 **Kod Analizi:**\n\n{response}"
            )
    
    elif data == "clear_file":
        clear_command(update, context)
        await query.edit_message_text("✅ Dosya içeriği temizlendi!")
    
    elif data == "model_chat":
        context.user_data['model'] = 'deepseek-chat'
        await query.edit_message_text("✅ Model DeepSeek-Chat olarak ayarlandı!")
    
    elif data == "model_coder":
        context.user_data['model'] = 'deepseek-coder'
        await query.edit_message_text("✅ Model DeepSeek-Coder olarak ayarlandı!")

# --- Hata Handler ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hataları logla"""
    logger.error(f"Update {update} caused error {context.error}")

# --- Ana Fonksiyon ---
def main():
    """Botu başlat"""
    # Application oluştur
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Conversation handler (dosya yükleme için)
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('file', file_command),
            CommandHandler('start', start)
        ],
        states={
            READING_FILE: [
                MessageHandler(filters.Document.ALL, handle_document),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
            ],
            SELECTING_ACTION: [
                CallbackQueryHandler(button_handler)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Handlers ekle
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("model", model_command))
    
    # Mesaj handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Hata handler
    application.add_error_handler(error_handler)
    
    # Botu başlat
    print("🤖 Bot başlatılıyor...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
