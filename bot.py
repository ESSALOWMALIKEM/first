import telebot
from telebot import types
import json
import os
import logging
import time
import flask

# Logging ayarları
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__) # __name__ KULLANILDI

# --- Yapılandırma ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or 'YOUR_TELEGRAM_BOT_TOKEN_HERE' # Token'ınızı buraya girin
bot = telebot.TeleBot(TOKEN, parse_mode=None)

# Webhook ayarları
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL")
WEBHOOK_PORT = int(os.environ.get('PORT', 8443))
WEBHOOK_LISTEN = '0.0.0.0'

WEBHOOK_URL_PATH = f"/{TOKEN}/"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_URL_PATH}" if WEBHOOK_HOST else None

# Flask app instance
app = flask.Flask(__name__) # __name__ KULLANILDI

# --- Sabitler ve Veri Dosyası ---
SUPER_ADMIN_ID = 0 # KENDİ TELEGRAM ID'NİZİ GİRİN! (ÇOK ÖNEMLİ)
DATA_FILE = 'channels.dat'

# Callback data sabitleri (basitleştirilmiş)
CB_SET_START_TEXT = "set_start_text"
CB_SET_CHANNEL_ANNOUNCE_TEXT = "set_channel_announce_text"
CB_VIEW_ADMINS = "view_admins"
CB_VIEW_CHANNELS = "view_channels"
CB_CREATE_SUPPORT_REQUEST = "create_support_request"

# --- Veri Yönetimi ---
def load_data():
    default_start_text = "👋 Hoş geldin {user_name}\\!\n\n📣 VPN KODUNU ALMAK İSTİYORSANIZ AŞAĞIDA GÖSTERİLEN SPONSOR KANALLARA ABONE OLUNUZ\\:"
    default_channel_announce_text = (
        "*🔥 PUBG İÇİN YARIP GEÇEN VPN KODU GELDİ\\! 🔥*\n\n"
        "⚡️ *30 \\- 40 PING* veren efsane kod botumuzda sizleri bekliyor\\!\n\n"
        "🚀 Hemen aşağıdaki butona tıklayarak veya [bota giderek](https://t.me/{bot_username}?start=pubgcode) kodu kapın\\!\n\n"
        "✨ _Aktif ve değerli üyelerimiz için özel\\!_ ✨"
    )

    if not os.path.exists(DATA_FILE):
        initial_data = {
            "channels": [],
            "success_message": "KOD: ",
            "users": [],
            "admins": [SUPER_ADMIN_ID] if SUPER_ADMIN_ID != 0 else [],
            "start_message_text": default_start_text,
            "channel_announcement_text": default_channel_announce_text,
            "bot_operational_status": "active"
        }
        with open(DATA_FILE, 'w', encoding='utf-8') as file:
            json.dump(initial_data, file, ensure_ascii=False, indent=4)
        logger.info(f"{DATA_FILE} oluşturuldu.")
        return initial_data
    else:
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as file:
                data = json.load(file)
            if not isinstance(data, dict):
                raise json.JSONDecodeError("Data is not a dictionary", "", 0)

            updated = False
            # Temel anahtarlar
            for key, default_value in [
                ("channels", []), ("success_message", "KOD: "), ("users", []),
                ("admins", [SUPER_ADMIN_ID] if SUPER_ADMIN_ID != 0 else []),
                ("start_message_text", default_start_text),
                ("channel_announcement_text", default_channel_announce_text),
                ("bot_operational_status", "active")
            ]:
                if key not in data:
                    data[key] = default_value
                    updated = True
            
            # Admin listesinde SUPER_ADMIN_ID kontrolü
            if SUPER_ADMIN_ID != 0 and SUPER_ADMIN_ID not in data.get("admins", []):
                 data.setdefault("admins", []).append(SUPER_ADMIN_ID)
                 updated = True
            
            # Eski resimle ilgili anahtarları kaldır (isteğe bağlı temizlik)
            for old_key in ["start_message_type", "start_message_image_id", 
                            "channel_announcement_type", "channel_announcement_image_id"]:
                if old_key in data:
                    del data[old_key]
                    updated = True

            if updated:
                save_data(data) 
            return data
        except json.JSONDecodeError as e:
            logger.error(f"{DATA_FILE} bozuk. Yeniden oluşturuluyor. Hata: {e}")
            # ... (önceki yedekleme ve yeniden oluşturma mantığı aynı kalabilir) ...
            initial_data_on_error = {
                "channels": [], "success_message": "KOD: ", "users": [], 
                "admins": [SUPER_ADMIN_ID] if SUPER_ADMIN_ID != 0 else [],
                "start_message_text": default_start_text,
                "channel_announcement_text": default_channel_announce_text,
                "bot_operational_status": "active"
            }
            with open(DATA_FILE, 'w', encoding='utf-8') as file:
                json.dump(initial_data_on_error, file, ensure_ascii=False, indent=4)
            return initial_data_on_error
        except Exception as e: # Diğer tüm hatalar
            logger.error(f"{DATA_FILE} yüklenirken beklenmedik genel hata: {e}")
            # En kötü durumda varsayılan bir yapı döndür
            return {"channels": [], "success_message": "KOD: ", "users": [], 
                    "admins": [SUPER_ADMIN_ID] if SUPER_ADMIN_ID != 0 else [],
                    "start_message_text": default_start_text, 
                    "channel_announcement_text": default_channel_announce_text,
                    "bot_operational_status": "active"}


def save_data(data):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        logger.info(f"Veri {DATA_FILE} dosyasına kaydedildi.")
    except Exception as e:
        logger.error(f"{DATA_FILE} dosyasına kaydederken hata: {e}")

def add_user_if_not_exists(user_id):
    data = load_data()
    if user_id not in data.get("users", []):
        data.setdefault("users", []).append(user_id) # setdefault daha güvenli
        save_data(data)
        logger.info(f"Yeni kullanıcı eklendi: {user_id}")

def escape_markdown_v2(text):
    if not isinstance(text, str):
        text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join([f'\\{char}' if char in escape_chars else char for char in text])

# --- Güvenli Mesaj Gönderme Yardımcısı (Basitleştirilmiş) ---
def send_with_markdown_v2_fallback(bot_method, chat_id_or_message, text_content, reply_markup=None):
    """MarkdownV2 ile göndermeyi dener, ayrıştırma hatasında düz metin olarak veya Markdown'sız dener."""
    chat_id = chat_id_or_message.chat.id if hasattr(chat_id_or_message, 'chat') else chat_id_or_message
    is_reply = hasattr(chat_id_or_message, 'message_id') and bot_method == bot.reply_to

    args = [chat_id_or_message if is_reply else chat_id, text_content]
    kwargs_md = {"reply_markup": reply_markup, "parse_mode": "MarkdownV2"}
    kwargs_plain = {"reply_markup": reply_markup}

    try:
        bot_method(*args, **kwargs_md)
        return True
    except telebot.apihelper.ApiTelegramException as e:
        markdown_errors = ["can't parse entities", "unclosed token", "can't find end of the entity", "expected an entity after `[`", "wrong string"]
        if any(err_str in str(e).lower() for err_str in markdown_errors):
            logger.warning(f"MarkdownV2 ayrıştırma hatası (chat {chat_id}): {e}. Düz metin/Markdown'sız deneniyor.")
            try:
                # Önce escape edilmiş MarkdownV2 ile deneyelim
                escaped_text = escape_markdown_v2(text_content)
                args_escaped = [chat_id_or_message if is_reply else chat_id, escaped_text]
                bot_method(*args_escaped, **kwargs_md)
                return True
            except telebot.apihelper.ApiTelegramException as e2:
                logger.warning(f"Escaped MarkdownV2 ile gönderme de başarısız oldu (chat {chat_id}): {e2}. Parse_mode olmadan deneniyor.")
                try:
                    bot_method(*args, **kwargs_plain) # parse_mode yok
                    return True
                except Exception as e3:
                    logger.error(f"Düz metin/Markdown'sız gönderme son denemesi de başarısız oldu (chat {chat_id}): {e3}")
                    return False
        else: 
            logger.error(f"Başka bir API Hatası (chat {chat_id}): {e}")
            raise 
    except Exception as ex: 
        logger.error(f"Mesaj gönderilirken beklenmedik genel hata (chat {chat_id}): {ex}")
        return False

# --- Yetkilendirme ve Durum Kontrolü ---
def is_admin_check(user_id):
    data = load_data()
    return user_id in data.get("admins", [])

def is_super_admin_check(user_id):
    return user_id == SUPER_ADMIN_ID

def is_bot_active_for_user(user_id):
    data = load_data()
    if data.get("bot_operational_status") == "admin_only":
        return is_admin_check(user_id)
    return True

# --- Admin Paneli (Basitleştirilmiş) ---
def get_admin_panel_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton("📢 Kanallara Genel Duyuru", callback_data="admin_public_channels"), # Sadece metin
        types.InlineKeyboardButton("🗣️ Kullanıcılara Duyuru", callback_data="admin_alert_users"),     # Sadece metin
        types.InlineKeyboardButton("➕ Kanal Ekle", callback_data="admin_add_channel"),
        types.InlineKeyboardButton("➖ Kanal Sil", callback_data="admin_delete_channel_prompt"),
        types.InlineKeyboardButton("🔑 VPN Kodunu Değiştir", callback_data="admin_change_vpn"),
        types.InlineKeyboardButton("📊 İstatistikler", callback_data="admin_stats"),
        types.InlineKeyboardButton("➕ Admin Ekle", callback_data="admin_add_admin_prompt"),
        types.InlineKeyboardButton("➖ Admin Sil", callback_data="admin_remove_admin_prompt"),
        types.InlineKeyboardButton("✍️ Başlangıç Msj Ayarla", callback_data=CB_SET_START_TEXT),
        types.InlineKeyboardButton("✍️ Genel Kanal Dyr Ayarla", callback_data=CB_SET_CHANNEL_ANNOUNCE_TEXT),
        types.InlineKeyboardButton("📜 Adminleri Gör", callback_data=CB_VIEW_ADMINS),
        types.InlineKeyboardButton("📜 Kanalları Gör", callback_data=CB_VIEW_CHANNELS),
    ]
    markup.add(*buttons)
    return markup

@bot.message_handler(commands=['admin'])
def admin_panel_command(message):
    user_id = message.from_user.id
    if not is_admin_check(user_id):
        bot.reply_to(message, "⛔ Bu komutu kullanma yetkiniz yok.")
        return
    send_with_markdown_v2_fallback(bot.send_message, message.chat.id, "🤖 *Admin Paneli*\nLütfen bir işlem seçin:", reply_markup=get_admin_panel_markup())

# --- BAKIM MODU KOMUTLARI ---
@bot.message_handler(commands=['durdur'])
def stop_bot_command(message):
    if not is_admin_check(message.from_user.id):
        bot.reply_to(message, "⛔ Bu komutu kullanma yetkiniz yok.")
        return
    data = load_data()
    data["bot_operational_status"] = "admin_only"
    save_data(data)
    bot.reply_to(message, "🤖 Bot bakım moduna alındı. Sadece adminler komut kullanabilir.")

@bot.message_handler(commands=['baslat'])
def start_bot_command(message):
    if not is_admin_check(message.from_user.id):
        bot.reply_to(message, "⛔ Bu komutu kullanma yetkiniz yok.")
        return
    data = load_data()
    data["bot_operational_status"] = "active"
    save_data(data)
    bot.reply_to(message, "🤖 Bot aktif moda alındı. Tüm kullanıcılar komut kullanabilir.")

# --- Genel Kullanıcı Komutları ---
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    if not is_bot_active_for_user(user_id):
        bot.reply_to(message, "ℹ️ Bot şu anda bakım modundadır. Lütfen daha sonra tekrar deneyin.")
        return

    user_name_raw = message.from_user.first_name or "Kullanıcı"
    user_name_escaped = escape_markdown_v2(user_name_raw)
    logger.info(f"Kullanıcı {user_id} ({user_name_raw}) /start komutunu kullandı.")
    add_user_if_not_exists(user_id)

    data = load_data()
    start_message_text_template = data.get("start_message_text", "👋 Hoş geldin {user_name}\\!")
    final_start_text = start_message_text_template.replace("{user_name}", user_name_escaped)
    send_with_markdown_v2_fallback(bot.send_message, message.chat.id, final_start_text)
    
    channels = data.get("channels", [])
    if channels:
        markup_channels = types.InlineKeyboardMarkup(row_width=1)
        text_for_channels = "📣 VPN KODUNU ALMAK İSTİYORSANIZ AŞAĞIDA GÖSTERİLEN SPONSOR KANALLARA ABONE OLUNUZ\\:"
        for index, channel_link in enumerate(channels, 1):
            channel_username = channel_link.strip('@')
            if channel_username:
                display_name = escape_markdown_v2(channel_link)
                button = types.InlineKeyboardButton(f"🔗 Kanal {index}: {display_name}", url=f"https://t.me/{channel_username}")
                markup_channels.add(button)
        button_check = types.InlineKeyboardButton("✅ ABONE OLDUM / KODU AL", callback_data="check_subscription")
        markup_channels.add(button_check)
        send_with_markdown_v2_fallback(bot.send_message, message.chat.id, text_for_channels, reply_markup=markup_channels)

@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def check_subscription_callback(call):
    user_id = call.from_user.id
    if not is_bot_active_for_user(user_id):
        bot.answer_callback_query(call.id, "ℹ️ Bot bakımda.", show_alert=True)
        return
    bot.answer_callback_query(call.id, "🔄 Abonelikleriniz kontrol ediliyor...", show_alert=False)
    data = load_data()
    channels = data.get("channels", [])
    success_message_text = data.get("success_message", "KOD: ")
    if not channels:
        try: bot.edit_message_text("📢 Şu anda kontrol edilecek zorunlu kanal bulunmamaktadır.", call.message.chat.id, call.message.message_id)
        except telebot.apihelper.ApiTelegramException: bot.send_message(call.message.chat.id, "📢 Şu anda kontrol edilecek zorunlu kanal bulunmamaktadır.")
        return
    all_subscribed, failed_channels_list = True, []
    for channel_link in channels:
        effective_channel_id = channel_link
        if isinstance(channel_link, str) and not channel_link.startswith("@") and not channel_link.lstrip('-').isdigit():
             effective_channel_id = f"@{channel_link}"
        try:
            member = bot.get_chat_member(chat_id=effective_channel_id, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                all_subscribed = False; failed_channels_list.append(channel_link)
        except Exception as e: # Geniş tuttuk, SUPER_ADMIN'e bildirim önemli
            logger.error(f"Abonelik kontrol hatası ({effective_channel_id}), kullanıcı {user_id}: {e}")
            if SUPER_ADMIN_ID != 0:
                 try: bot.send_message(SUPER_ADMIN_ID, f"⚠️ Abonelik Kontrol Hatası: Kanal: {effective_channel_id}, Kullanıcı: {user_id}. Hata: {str(e)[:200]}")
                 except Exception as ex_admin: logger.error(f"SUPER_ADMIN'e uyarı gönderilemedi: {ex_admin}")
            all_subscribed = False; failed_channels_list.append(channel_link)
    if all_subscribed:
        try: bot.edit_message_text(success_message_text, call.message.chat.id, call.message.message_id, reply_markup=None, parse_mode="MarkdownV2")
        except telebot.apihelper.ApiTelegramException as e: # Markdown hatası veya mesaj bulunamadı
            logger.warning(f"Başarı mesajı düzenlenemedi ({e}), yeni mesaj gönderiliyor.")
            send_with_markdown_v2_fallback(bot.send_message, call.message.chat.id, success_message_text)
    else:
        error_text = "❌ Lütfen aşağıdaki kanalların hepsine abone olduğunuzdan emin olun ve tekrar deneyin:\n\n"
        markup = types.InlineKeyboardMarkup(row_width=1)
        for ch_link in channels:
            prefix = "❗️" if ch_link in failed_channels_list else "➡️"
            markup.add(types.InlineKeyboardButton(f"{prefix} Kanal: {escape_markdown_v2(ch_link)}", url=f"https://t.me/{ch_link.lstrip('@')}"))
        markup.add(types.InlineKeyboardButton("🔄 TEKRAR KONTROL ET", callback_data="check_subscription"))
        try: bot.edit_message_text(error_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="MarkdownV2") # error_text Markdown içermiyor
        except telebot.apihelper.ApiTelegramException: bot.send_message(call.message.chat.id, error_text, reply_markup=markup, parse_mode="MarkdownV2")

@bot.message_handler(commands=['help'])
def help_command(message):
    user_id = message.from_user.id
    if not is_bot_active_for_user(user_id):
        bot.reply_to(message, "ℹ️ Bot şu anda bakım modundadır. Lütfen daha sonra tekrar deneyin.")
        return
    base_help = "🤖 *BOT KOMUTLARI* 🤖\n\n👤 *Genel Kullanıcı Komutları:*\n/start \\- Botu başlatır\\.\n/help \\- Bu yardım mesajını gösterir\\.\n"
    admin_help_text = ""
    if is_admin_check(user_id):
        admin_help_text = "\n👑 *Admin Komutları:*\n/admin \\- Admin panelini açar\\.\n/durdur \\- Bakım modu\\.\n/baslat \\- Aktif mod\\.\n/yanitla `<id> <mesaj>` \\- Yanıtla\\.\n"
    full_help_text = base_help + admin_help_text
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✉️ Destek Talebi Oluştur", callback_data=CB_CREATE_SUPPORT_REQUEST))
    send_with_markdown_v2_fallback(bot.reply_to, message, full_help_text, reply_markup=markup)

# --- Destek Talebi İşleyicileri ---
@bot.callback_query_handler(func=lambda call: call.data == CB_CREATE_SUPPORT_REQUEST)
def create_support_request_callback(call):
    if not is_bot_active_for_user(call.from_user.id): bot.answer_callback_query(call.id, "ℹ️ Bot bakımda.", show_alert=True); return
    bot.answer_callback_query(call.id)
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
    sent_msg = bot.send_message(call.message.chat.id, "Lütfen sorununuzu veya mesajınızı detaylıca yazın. Mesajınız adminlere iletilecektir.")
    bot.register_next_step_handler(sent_msg, process_user_support_message)

def process_user_support_message(message):
    user_id, user_name_raw = message.from_user.id, message.from_user.first_name or f"User_{message.from_user.id}"
    user_name_esc = escape_markdown_v2(user_name_raw)
    user_username_raw = f"@{message.from_user.username}" if message.from_user.username else "Yok"
    user_username_esc = escape_markdown_v2(user_username_raw)
    support_text_esc = escape_markdown_v2(message.text)
    admin_msg_text = (f"🆘 *Yeni Destek Talebi* 🆘\n\n*Kullanıcı:* {user_name_esc}\n"
                      f"*Telegram ID:* `{user_id}`\n*Kullanıcı Adı:* {user_username_esc}\n\n"
                      f"*Mesajı:*\n{support_text_esc}\n\nCevaplamak için: `/yanitla {user_id} <mesajınız>`")
    data = load_data()
    admin_ids = data.get("admins", [])
    if not admin_ids and SUPER_ADMIN_ID != 0: admin_ids = [SUPER_ADMIN_ID]
    if not admin_ids: logger.error("Destek talebi iletilecek admin yok!"); bot.reply_to(message, "Üzgünüz, adminlere ulaşılamadı."); return
    sent_count = 0
    for admin_id_target in admin_ids:
        try: bot.send_message(admin_id_target, admin_msg_text, parse_mode="MarkdownV2"); sent_count +=1
        except Exception as e: logger.error(f"Admin {admin_id_target} destek iletilemedi: {e}")
    if sent_count > 0: bot.reply_to(message, "Mesajınız adminlere iletildi.")
    else: bot.reply_to(message, "Mesajınız adminlere iletilirken sorun oluştu.")

@bot.message_handler(commands=['yanitla'])
def reply_to_user_command(message):
    if not is_admin_check(message.from_user.id): bot.reply_to(message, "⛔ Yetkiniz yok."); return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3: bot.reply_to(message, "Kullanım: `/yanitla <kullanıcı_id> <mesajınız>`", parse_mode="MarkdownV2"); return
    try: user_id_to_reply, reply_text_raw = int(parts[1]), parts[2]
    except ValueError: bot.reply_to(message, "Geçersiz kullanıcı ID."); return
    final_reply_to_user = f"✉️ *Adminden Yanıt Var!*\n\n{reply_text_raw}" # Adminin yazdığı Markdown'ı koru
    if send_with_markdown_v2_fallback(bot.send_message, user_id_to_reply, final_reply_to_user):
        bot.reply_to(message, f"✅ `{user_id_to_reply}` ID'li kullanıcıya yanıtınız gönderildi.", parse_mode="MarkdownV2")
    else: bot.reply_to(message, f"⚠️ `{user_id_to_reply}` ID'li kullanıcıya yanıt gönderilemedi veya Markdown sorunu oldu (logları kontrol edin).", parse_mode="MarkdownV2")

# --- Ayarlanabilir Metin Mesaj İşleyicileri (Basitleştirilmiş) ---
def _set_text_message_prompt(call, text_key_to_set, prompt_identifier_text):
    if not is_admin_check(call.from_user.id): bot.answer_callback_query(call.id, "Yetkiniz yok.", show_alert=True); return
    bot.answer_callback_query(call.id)
    try:
        sent_msg = bot.edit_message_text(prompt_identifier_text, call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
    except telebot.apihelper.ApiTelegramException:
        sent_msg = bot.send_message(call.message.chat.id, prompt_identifier_text, parse_mode="MarkdownV2")
    bot.register_next_step_handler(sent_msg, _process_set_text_message, call.message.message_id, text_key_to_set)

def _process_set_text_message(message, original_message_id, text_key_to_set):
    if not is_admin_check(message.from_user.id): return
    new_text = message.text # Adminin girdiği ham metin
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    if not new_text.strip(): bot.send_message(message.chat.id, "❌ Mesaj boş olamaz. İşlem iptal edildi.")
    else:
        data = load_data()
        data[text_key_to_set] = new_text # Sadece metni kaydet
        save_data(data)
        bot.send_message(message.chat.id, "✅ Mesaj başarıyla güncellendi.")
    admin_panel_back_for_next_step(message.chat.id, original_message_id)

@bot.callback_query_handler(func=lambda call: call.data == CB_SET_START_TEXT)
def admin_set_start_text_callback(call):
    prompt = "🆕 Lütfen kullanıcılar /start yazdığında gösterilecek yeni metin mesajını girin.\nKullanıcının adını eklemek için `{user_name}` kullanabilirsiniz.\nMarkdownV2 kullanabilirsiniz."
    _set_text_message_prompt(call, "start_message_text", prompt)

@bot.callback_query_handler(func=lambda call: call.data == CB_SET_CHANNEL_ANNOUNCE_TEXT)
def admin_set_channel_announce_text_callback(call):
    prompt = "📢 Lütfen kanallara gönderilecek genel duyuru için yeni metin mesajını girin.\nBot kullanıcı adını eklemek için `{bot_username}` kullanabilirsiniz.\nMarkdownV2 kullanabilirsiniz."
    _set_text_message_prompt(call, "channel_announcement_text", prompt)

# --- KULLANICILARA DUYURU (Sadece Metin) ---
@bot.callback_query_handler(func=lambda call: call.data == "admin_alert_users") # Eskiden seçenek sunuyordu, şimdi direkt metin istiyor
def admin_alert_users_text_prompt_callback(call):
    if not is_admin_check(call.from_user.id): bot.answer_callback_query(call.id, "Yetkiniz yok.", show_alert=True); return
    bot.answer_callback_query(call.id)
    msg_text = "🗣️ Tüm bot kullanıcılarına göndermek istediğiniz *metin* mesajını yazın (Markdown kullanabilirsiniz):"
    try:
        sent_msg = bot.edit_message_text(msg_text, call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
    except telebot.apihelper.ApiTelegramException:
        sent_msg = bot.send_message(call.message.chat.id, msg_text, parse_mode="MarkdownV2")
    bot.register_next_step_handler(sent_msg, process_alert_users_message_text_only, call.message.message_id)

def process_alert_users_message_text_only(message, original_message_id): # Sadece metin işler
    if not is_admin_check(message.from_user.id): return
    alert_text_content = message.text # Adminin girdiği ham metin
    data = load_data(); users = data.get("users", [])
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    if not users: bot.send_message(message.chat.id, "ℹ️ Mesaj gönderilecek kullanıcı yok.")
    else:
        status_text = f"📢 {len(users)} kullanıcıya duyuru gönderiliyor..."
        try: status_msg = bot.edit_message_text(status_text, message.chat.id, original_message_id, parse_mode="MarkdownV2")
        except telebot.apihelper.ApiTelegramException: status_msg = bot.send_message(message.chat.id, status_text, parse_mode="MarkdownV2")
        
        success, failed, blocked = 0, 0, 0
        for user_id in users:
            sent_ok = False
            try:
                sent_ok = send_with_markdown_v2_fallback(bot.send_message, user_id, alert_text_content)
                if sent_ok: success += 1
                # else: failed += 1 # Fallback zaten logladı, burada tekrar saymaya gerek yok, dış try/except yakalar
            except telebot.apihelper.ApiTelegramException as e_outer:
                logger.error(f"Kullanıcı {user_id} duyuru (metin) gönderilemedi (API): {e_outer}")
                if any(err_str in str(e_outer).lower() for err_str in ["bot was blocked", "user is deactivated", "chat not found"]):
                    blocked +=1
                failed +=1
            except Exception as e_gen: logger.error(f"Kullanıcı {user_id} duyuru (metin) genel hata: {e_gen}"); failed +=1
            time.sleep(0.05) # Hafifletildi
        report = f"✅ Duyuru Tamamlandı:\nBaşarılı: {success}, Başarısız: {failed}, Engelli/Ulaşılamayan: {blocked}"
        try: bot.edit_message_text(report, status_msg.chat.id, status_msg.message_id, reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")
        except telebot.apihelper.ApiTelegramException: bot.send_message(status_msg.chat.id, report, reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")
        return
    admin_panel_back_for_next_step(message.chat.id, original_message_id)

# --- KANALLARA GENEL DUYURU (Sadece Metin) ---
@bot.callback_query_handler(func=lambda call: call.data == "admin_public_channels")
def admin_public_to_channels_callback(call):
    if not is_admin_check(call.from_user.id): bot.answer_callback_query(call.id, "Yetkiniz yok.", show_alert=True); return
    bot.answer_callback_query(call.id, "İşleniyor...")
    data = load_data(); channels_to_send = data.get("channels", [])
    if not channels_to_send:
        try: bot.edit_message_text("ℹ️ Duyuru yapılacak kanal yok.", call.message.chat.id, call.message.message_id, reply_markup=get_admin_panel_markup())
        except: pass; return
    announce_text_template = data.get("channel_announcement_text", "*Varsayılan Duyuru*")
    try: bot_username = bot.get_me().username
    except Exception as e: logger.error(f"Bot adı alınamadı: {e}"); bot_username = "BOT_KULLANICI_ADI"
    final_announce_text = announce_text_template.replace("{bot_username}", bot_username) # Ham metin
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🤖 BOTA GİT 🤖", url=f"https://t.me/{bot_username}?start=channelAnnounce"))
    status_text = f"📢 {len(channels_to_send)} kanala genel duyuru gönderiliyor..."
    try: status_msg = bot.edit_message_text(status_text, call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
    except telebot.apihelper.ApiTelegramException: status_msg = bot.send_message(call.message.chat.id, status_text, parse_mode="MarkdownV2")
    success, failed = 0, 0
    for channel_item in channels_to_send:
        sent_ok = False
        try:
            sent_ok = send_with_markdown_v2_fallback(bot.send_message, channel_item, final_announce_text, reply_markup=markup)
            if sent_ok: success += 1
            else: failed += 1
        except Exception as e_outer: logger.error(f"Kanal {channel_item} genel duyuru gönderilemedi (dış): {e_outer}"); failed +=1
        time.sleep(0.1) # Hafifletildi
    report = f"✅ Kanallara genel duyuru tamamlandı:\nBaşarılı: {success}, Başarısız: {failed}"
    try: bot.edit_message_text(report, status_msg.chat.id, status_msg.message_id, reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")
    except telebot.apihelper.ApiTelegramException: bot.send_message(status_msg.chat.id, report, reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")

# --- ADMİNLERİ VE KANALLARI GÖRÜNTÜLEME (Aynı kalabilir) ---
@bot.callback_query_handler(func=lambda call: call.data == CB_VIEW_ADMINS)
def admin_view_admins_callback(call): # Bu fonksiyon önceki gibi kalabilir
    if not is_admin_check(call.from_user.id): bot.answer_callback_query(call.id, "Yetkiniz yok.", show_alert=True); return
    bot.answer_callback_query(call.id); data = load_data(); admin_ids = data.get("admins", [])
    text_to_send = "ℹ️ Kayıtlı admin yok." if not admin_ids else "👑 *Kayıtlı Adminler:*\n"
    if admin_ids:
        details_list = []
        for admin_id in admin_ids:
            parts = [f"`{admin_id}`"]
            if admin_id == SUPER_ADMIN_ID: parts.append("\\(Süper Admin\\)")
            try:
                chat = bot.get_chat(admin_id)
                if chat.first_name: parts.append(f"\\- {escape_markdown_v2(chat.first_name)}")
                if chat.username: parts.append(f"\\(@{escape_markdown_v2(chat.username)}\\)")
            except: pass # Detay alınamazsa sorun değil
            details_list.append(" ".join(parts))
        text_to_send += "\n".join(details_list)
    try: bot.edit_message_text(text_to_send, call.message.chat.id, call.message.message_id, reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" not in str(e).lower(): bot.send_message(call.message.chat.id, text_to_send, reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")

@bot.callback_query_handler(func=lambda call: call.data == CB_VIEW_CHANNELS)
def admin_view_channels_callback(call): # Bu fonksiyon önceki gibi kalabilir
    if not is_admin_check(call.from_user.id): bot.answer_callback_query(call.id, "Yetkiniz yok.", show_alert=True); return
    bot.answer_callback_query(call.id); data = load_data(); channels = data.get("channels", [])
    text_to_send = "ℹ️ Kayıtlı kanal yok." if not channels else "📢 *Kayıtlı Kanallar:*\n" + "\n".join([escape_markdown_v2(ch) for ch in channels])
    try: bot.edit_message_text(text_to_send, call.message.chat.id, call.message.message_id, reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" not in str(e).lower(): bot.send_message(call.message.chat.id, text_to_send, reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")

# --- DİĞER ADMIN İŞLEVLERİ (Kanal Ekle/Sil, VPN Kodu, İstatistikler, Admin Ekle/Sil) ---
# Bu fonksiyonlar büyük ölçüde aynı kalabilir.
@bot.callback_query_handler(func=lambda call: call.data == "admin_add_channel")
def admin_add_channel_prompt_callback(call):
    if not is_admin_check(call.from_user.id): return bot.answer_callback_query(call.id, "Yetkiniz yok.", show_alert=True)
    bot.answer_callback_query(call.id)
    msg_text = ("➕ Eklenecek kanal\\(lar\\)ın kullanıcı adlarını girin \\(örneğin: `@kanal1 @kanal2`\\)\\. "
                "Botun kanallarda *yönetici olduğundan* emin olun\\.")
    try: sent_msg = bot.edit_message_text(msg_text, call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
    except: sent_msg = bot.send_message(call.message.chat.id, msg_text, parse_mode="MarkdownV2")
    bot.register_next_step_handler(sent_msg, process_add_multiple_channels, call.message.message_id)

def process_add_multiple_channels(message, original_message_id):
    if not is_admin_check(message.from_user.id): return
    inputs = message.text.split(); added, failed, exists = [], [], []
    data = load_data()
    for ch_in in inputs:
        new_ch = ch_in.strip()
        if not new_ch: continue
        if not new_ch.startswith("@") and not new_ch.lstrip('-').isdigit(): failed.append(f"{escape_markdown_v2(new_ch)} (Geçersiz)"); continue
        if new_ch not in data["channels"]: data["channels"].append(new_ch); added.append(new_ch)
        else: exists.append(new_ch)
    if added: save_data(data)
    parts = []
    if added: parts.append(f"✅ Eklendi:\n" + "\n".join(map(escape_markdown_v2, added)))
    if failed: parts.append(f"❌ Eklenemedi:\n" + "\n".join(failed))
    if exists: parts.append(f"ℹ️ Zaten Var:\n" + "\n".join(map(escape_markdown_v2,exists)))
    response = "\n\n".join(parts) if parts else "İşlem yapılacak kanal bulunamadı."
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    bot.send_message(message.chat.id, response, parse_mode="MarkdownV2")
    admin_panel_back_for_next_step(message.chat.id, original_message_id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_delete_channel_prompt")
def admin_delete_channel_prompt_callback(call):
    if not is_admin_check(call.from_user.id): return bot.answer_callback_query(call.id, "Yetkiniz yok.", show_alert=True)
    bot.answer_callback_query(call.id); data = load_data(); channels = data.get("channels", [])
    if not channels:
        try: bot.edit_message_text("➖ Silinecek kanal yok.", call.message.chat.id, call.message.message_id, reply_markup=get_admin_panel_markup())
        except: pass; return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for ch in channels: markup.add(types.InlineKeyboardButton(f"🗑️ Sil: {escape_markdown_v2(ch)}", callback_data=f"admin_del_ch_confirm:{ch}"))
    markup.add(types.InlineKeyboardButton("↩️ Geri", callback_data="admin_panel_back"))
    try: bot.edit_message_text("➖ Silinecek kanalı seçin:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="MarkdownV2")
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_del_ch_confirm:"))
def admin_delete_channel_confirm_callback(call):
    if not is_admin_check(call.from_user.id): return bot.answer_callback_query(call.id, "Yetkiniz yok.", show_alert=True)
    ch_to_remove = call.data.split(":", 1)[1]; data = load_data()
    if ch_to_remove in data["channels"]: data["channels"].remove(ch_to_remove); save_data(data); bot.answer_callback_query(call.id, f"✅ Silindi.")
    else: bot.answer_callback_query(call.id, f"ℹ️ Bulunamadı.", show_alert=True)
    admin_delete_channel_prompt_callback(call) 

@bot.callback_query_handler(func=lambda call: call.data == "admin_change_vpn")
def admin_change_vpn_prompt_callback(call):
    if not is_admin_check(call.from_user.id): return bot.answer_callback_query(call.id, "Yetkiniz yok.", show_alert=True)
    bot.answer_callback_query(call.id); data = load_data(); current_code = data.get("success_message", "KOD: ")
    msg_text = (f"🔑 Yeni VPN kodunu girin\\. Mevcut:\n`{escape_markdown_v2(current_code)}`\nMarkdown kullanabilirsiniz\\.")
    try: sent_msg = bot.edit_message_text(msg_text, call.message.chat.id, call.message.message_id, parse_mode="MarkdownV2")
    except: sent_msg = bot.send_message(call.message.chat.id, msg_text, parse_mode="MarkdownV2")
    bot.register_next_step_handler(sent_msg, process_change_vpn_code, call.message.message_id)

def process_change_vpn_code(message, original_message_id): 
    if not is_admin_check(message.from_user.id): return
    new_code = message.text; try: bot.delete_message(message.chat.id, message.message_id); except: pass
    if not new_code.strip(): bot.send_message(message.chat.id, "❌ Kod boş olamaz.")
    else: data = load_data(); data["success_message"] = new_code; save_data(data); bot.send_message(message.chat.id, "✅ VPN kodu güncellendi.")
    admin_panel_back_for_next_step(message.chat.id, original_message_id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
def admin_stats_callback(call):
    if not is_admin_check(call.from_user.id): return bot.answer_callback_query(call.id, "Yetkiniz yok.", show_alert=True)
    bot.answer_callback_query(call.id); data = load_data()
    stats = (f"📊 *Bot İstatistikleri*\n\n👤 Kullanıcı: {len(data.get('users',[]))}\n📢 Kanal: {len(data.get('channels',[]))}\n"
             f"👑 Admin: {len(data.get('admins',[]))}\n⚙️ Durum: `{escape_markdown_v2(data.get('bot_operational_status','active'))}`\n\n"
             f"_{escape_markdown_v2(time.strftime('%Y-%m-%d %H:%M:%S %Z'))}_")
    try: bot.edit_message_text(stats, call.message.chat.id, call.message.message_id, reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" not in str(e).lower(): bot.send_message(call.message.chat.id, stats, reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_admin_prompt")
def admin_add_admin_prompt_callback(call):
    if not is_super_admin_check(call.from_user.id): return bot.answer_callback_query(call.id, "⛔ Sadece Süper Admin.", show_alert=True)
    bot.answer_callback_query(call.id); msg_text = "➕ Admin yapılacak kullanıcının Telegram ID'sini girin:"
    try: sent_msg = bot.edit_message_text(msg_text, call.message.chat.id, call.message.message_id)
    except: sent_msg = bot.send_message(call.message.chat.id, msg_text)
    bot.register_next_step_handler(sent_msg, process_add_admin_id, call.message.message_id)

def process_add_admin_id(message, original_message_id):
    if not is_super_admin_check(message.from_user.id): return
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    try: new_admin_id = int(message.text.strip())
    except ValueError: bot.send_message(message.chat.id, "❌ Geçersiz ID."); admin_panel_back_for_next_step(message.chat.id, original_message_id); return
    data = load_data()
    if new_admin_id in data["admins"]: bot.send_message(message.chat.id, f"ℹ️ `{new_admin_id}` zaten admin.", parse_mode="MarkdownV2")
    else: data["admins"].append(new_admin_id); save_data(data); bot.send_message(message.chat.id, f"✅ `{new_admin_id}` admin yapıldı.", parse_mode="MarkdownV2")
    admin_panel_back_for_next_step(message.chat.id, original_message_id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_remove_admin_prompt")
def admin_remove_admin_prompt_callback(call):
    if not is_super_admin_check(call.from_user.id): return bot.answer_callback_query(call.id, "⛔ Sadece Süper Admin.", show_alert=True)
    bot.answer_callback_query(call.id); data = load_data(); admins_to_list = [aid for aid in data.get("admins", []) if aid != SUPER_ADMIN_ID]
    if not admins_to_list:
        try: bot.edit_message_text("➖ Silinecek başka admin yok.", call.message.chat.id, call.message.message_id, reply_markup=get_admin_panel_markup())
        except: pass; return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for aid in admins_to_list: markup.add(types.InlineKeyboardButton(f"🗑️ Sil: {aid}", callback_data=f"admin_rem_adm_confirm:{aid}"))
    markup.add(types.InlineKeyboardButton("↩️ Geri", callback_data="admin_panel_back"))
    try: bot.edit_message_text("➖ Silinecek admini seçin:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_rem_adm_confirm:"))
def admin_remove_admin_confirm_callback(call):
    if not is_super_admin_check(call.from_user.id): return bot.answer_callback_query(call.id, "⛔ Sadece Süper Admin.", show_alert=True)
    try: admin_id_to_remove = int(call.data.split(":", 1)[1])
    except: bot.answer_callback_query(call.id, "Geçersiz veri.", show_alert=True); admin_remove_admin_prompt_callback(call); return
    data = load_data()
    if admin_id_to_remove == SUPER_ADMIN_ID: bot.answer_callback_query(call.id, "⛔ Süper Admin silinemez.", show_alert=True)
    elif admin_id_to_remove in data.get("admins", []): data["admins"].remove(admin_id_to_remove); save_data(data); bot.answer_callback_query(call.id, f"✅ Admin {admin_id_to_remove} silindi.")
    else: bot.answer_callback_query(call.id, f"ℹ️ Admin {admin_id_to_remove} bulunamadı.", show_alert=True)
    admin_remove_admin_prompt_callback(call)

def admin_panel_back_for_next_step(chat_id, original_message_id):
    try: bot.edit_message_text("🤖 *Admin Paneli*\nLütfen bir işlem seçin:", chat_id, original_message_id, reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")
    except telebot.apihelper.ApiTelegramException as e:
        logger.warning(f"Next_step sonrası panel düzenlenemedi (ID: {original_message_id}): {e}")
        bot.send_message(chat_id, "🤖 *Admin Paneli*\nLütfen bir işlem seçin:", reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")

@bot.callback_query_handler(func=lambda call: call.data == "admin_panel_back")
def admin_panel_back_callback(call):
    if not is_admin_check(call.from_user.id): bot.answer_callback_query(call.id, "Yetkiniz yok.", show_alert=True); return
    bot.answer_callback_query(call.id)
    try: bot.edit_message_text("🤖 *Admin Paneli*\nLütfen bir işlem seçin:", call.message.chat.id, call.message.message_id, reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")
    except Exception as e: logger.error(f"Admin paneline geri dönerken hata: {e}"); bot.send_message(call.message.chat.id, "🤖 *Admin Paneli*\nLütfen bir işlem seçin:", reply_markup=get_admin_panel_markup(), parse_mode="MarkdownV2")

# --- Bilinmeyen Komutlar ve Mesajlar ---
@bot.message_handler(func=lambda message: True, content_types=['text', 'audio', 'document', 'photo', 'sticker', 'video', 'video_note', 'voice', 'location', 'contact'])
def handle_other_messages(message):
    user_id, text = message.from_user.id, message.text
    if not is_bot_active_for_user(user_id) and (not text or not text.startswith(('/start', '/help', '/admin'))): return
    if text and text.startswith('/'):
        known_cmds = ['/start', '/help', '/admin', '/durdur', '/baslat', '/yanitla']
        if not any(text.startswith(cmd) for cmd in known_cmds):
            logger.info(f"Kullanıcı {user_id} bilinmeyen komut: {text}")
            escaped_text, reply_msg = escape_markdown_v2(text), f"⛔ `{escaped_text}` komutu bulunamadı\\. "
            reply_msg += "/help veya /admin kullanın\\." if is_admin_check(user_id) else "/help kullanın\\."
            bot.reply_to(message, reply_msg, parse_mode="MarkdownV2")
            if SUPER_ADMIN_ID != 0 and user_id != SUPER_ADMIN_ID:
                try: bot.send_message(SUPER_ADMIN_ID, f"⚠️ Bilinmeyen Komut:\nKullanıcı ID: `{user_id}`\nKomut: `{escaped_text}`", parse_mode="MarkdownV2")
                except Exception as e: logger.error(f"SUPER_ADMIN'e bilinmeyen komut iletilemedi: {e}")

# --- Webhook ve Flask Ayarları ---
@app.route(WEBHOOK_URL_PATH, methods=['POST'])
def webhook_handler_route(): # İsim değişikliği, olası çakışmaları önlemek için
    if flask.request.headers.get('content-type') == 'application/json':
        json_string = flask.request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else: flask.abort(403)

@app.route('/')
def index_route(): logger.info("Ana dizin '/' isteği."); return 'Bot çalışıyor!', 200
@app.route('/health')
def health_check_route(): logger.info("Sağlık kontrolü '/health' isteği."); return "OK", 200

# --- Bot Başlatma ---
if __name__ == "__main__":
    logger.info("Bot başlatılıyor...")
    if SUPER_ADMIN_ID == 0: # type: ignore
        logger.critical("ÖNEMLİ: SUPER_ADMIN_ID ayarlanmamış! Lütfen kod içinde bu değeri kendi Telegram ID'niz ile güncelleyin.")
    if TOKEN == 'YOUR_TELEGRAM_BOT_TOKEN_HERE':
        logger.critical("ÖNEMLİ: TOKEN ayarlanmamış! Lütfen kod içinde bu değeri kendi bot token'ınız ile güncelleyin veya ortam değişkeni olarak ayarlayın.")
    load_data() 
    if WEBHOOK_URL and WEBHOOK_HOST and WEBHOOK_HOST.startswith("https://"):
        logger.info(f"Webhook modu aktif. URL: {WEBHOOK_URL}")
        bot.remove_webhook(); time.sleep(0.5)
        secret = TOKEN[-10:] if TOKEN and len(TOKEN) >= 10 and TOKEN != 'YOUR_TELEGRAM_BOT_TOKEN_HERE' else "DEFAULT_SECRET"
        bot.set_webhook(url=WEBHOOK_URL, secret_token=secret) 
        logger.info(f"Flask uygulaması {WEBHOOK_LISTEN}:{WEBHOOK_PORT} adresinde çalışacak.")
        app.run(host=WEBHOOK_LISTEN, port=WEBHOOK_PORT)
    else:
        logger.warning("WEBHOOK_HOST (RENDER_EXTERNAL_URL) ayarlanmamış/hatalı/HTTPS değil veya TOKEN değiştirilmemiş.")
        logger.info("Polling modunda başlatılıyor...")
        bot.remove_webhook(); time.sleep(0.1)
        bot.polling(none_stop=True, interval=1, timeout=40)
