import os
import subprocess
import shutil
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# Loglama ayarları (Hataları görmek için)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- AYARLAR ---
TOKEN = "8570087251:AAFOTBbzJXFFHRx6h2gTm_StN39f3nX9_0A" # BotFather'dan aldığın token
OUTPUT_DIR = "bot_output"

# Klasörleri hazırla
os.makedirs(OUTPUT_DIR, exist_ok=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcı /start verdiğinde karşılama mesajı gönderir."""
    await update.message.reply_text(
        "👋 Merhaba! Ben Profesyonel Ses Ayrıştırıcı Bot.\n\n"
        "Lütfen ayırmak istediğiniz şarkıyı **Ses Dosyası (Audio)** olarak gönderin.\n"
        "Sizin için Vokal ve Enstrümantal (Altyapı) olarak ayırıp MP3 formatında göndereceğim. 🎵"
    )

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ses dosyası geldiğinde işleme başlar."""
    file_id = update.message.audio.file_id
    file_name = update.message.audio.file_name or f"{file_id}.mp3"
    
    # Kullanıcıya sürecin başladığını bildir
    status_msg = await update.message.reply_text("📥 Dosya alındı... Profesyonel AI modelleri (HTDemucs) kullanılarak işleniyor. Bu biraz zaman alabilir, lütfen bekleyin...")

    # Dosyayı indir
    new_file = await context.bot.get_file(file_id)
    input_path = os.path.join(OUTPUT_DIR, f"input_{file_id}.mp3")
    await new_file.download_to_drive(input_path)

    try:
        # Demucs Komutu
        # -n htdemucs: En kaliteli model
        # --two-stems=vocals: Sadece Vokal ve Enstrümantal
        # --mp3: Çıktıyı doğrudan MP3 yapar
        command = [
            "demucs",
            "--mp3",
            "--two-stems", "vocals",
            "-n", "htdemucs",
            "-o", OUTPUT_DIR,
            input_path
        ]
        
        # İşlemi başlat
        subprocess.run(command, check=True)

        # Demucs çıktı yolu (Demucs kendi klasör yapısını oluşturur)
        # Yapı: OUTPUT_DIR/htdemucs/input_file_id/
        folder_base_name = f"input_{file_id}"
        result_dir = os.path.join(OUTPUT_DIR, "htdemucs", folder_base_name)

        vocal_path = os.path.join(result_dir, "vocals.mp3")
        instr_path = os.path.join(result_dir, "no_vocals.mp3")

        # Dosyaları gönder
        await status_msg.edit_text("✅ İşlem tamamlandı! Dosyalar yükleniyor...")
        
        # Enstrümantal Gönderimi
        await update.message.reply_audio(
            audio=open(instr_path, 'rb'), 
            title=f"Enstrümantal - {file_name}",
            filename=f"Enstrumantal_{file_name}"
        )
        
        # Vokal Gönderimi
        await update.message.reply_audio(
            audio=open(vocal_path, 'rb'), 
            title=f"Vokal - {file_name}",
            filename=f"Vokal_{file_name}"
        )

        # İşlem bittiğinde temizlik yap (Sunucuda yer kaplamasın)
        shutil.rmtree(result_dir)
        os.remove(input_path)
        await status_msg.delete() # Bilgi mesajını sil

    except Exception as e:
        logging.error(f"Hata: {e}")
        await update.message.reply_text("❌ Üzgünüm, işlem sırasında bir hata oluştu. Lütfen dosya formatının doğru olduğundan emin olun.")

def main():
    # Botu oluştur
    app = Application.builder().token(TOKEN).build()
    
    # Komut ve Mesaj yakalayıcılar
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    
    print("Bot aktif... Şarkı gönderilmesi bekleniyor.")
    app.run_polling()

if __name__ == "__main__":
    main()
