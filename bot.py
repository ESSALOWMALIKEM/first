import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# BOT TOKEN
TOKEN = '8055381750:AAHVoZzqwzLPenDbZXwKVWBX6iofrz_9CLk'
bot = telebot.TeleBot(TOKEN)

# Adminler listesi
ADMIN_IDS = {6884554706}

# Ulanyjy maglumatlary
users = set()
vpn_alanlar = set()

# Habarlar
vpn_mesaji = "Adaty VPN habary."
giris_mesaji = "Botumyza hoş geldiňiz! Aşakdaky kanallara goşulyň."

# Kanallar
kanallar = []

# Global admin gulpy
admin_lock = False

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id
    users.add(user_id)

    # Diňe bot admin bolan kanallar üçin barlag
    eksik_kanallar = [k for k in kanallar if k.get("check_membership", False)]
    eksik_kanallar = [
        kanal for kanal in eksik_kanallar
        if not is_user_member_of_channel(user_id, kanal['username'])
    ]

    markup = InlineKeyboardMarkup(row_width=1)
    for kanal in kanallar:
        markup.add(InlineKeyboardButton(kanal["name"], url=f"https://t.me/{kanal['username'].lstrip('@')}"))
    markup.add(InlineKeyboardButton("✅ Kanallara agza boldum", callback_data="check_channels"))

    bot.send_message(user_id, giris_mesaji, reply_markup=markup)

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id not in ADMIN_IDS:
        return

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🛠️ VPN habaryny üýtget", callback_data="admin_vpn"),
        InlineKeyboardButton("📝 Giriş habaryny üýtget", callback_data="admin_startmsg"),
        InlineKeyboardButton("➕ Kanal goş", callback_data="admin_add_channel"),
        InlineKeyboardButton("➖ Kanal aýyr", callback_data="admin_remove_channel"),
        InlineKeyboardButton("📜 Kanallary gör", callback_data="admin_list_channels"),
        InlineKeyboardButton("🔃 Kanal üýtget", callback_data="admin_edit_channel"),
        InlineKeyboardButton("📤 Ulanyjylara habar iber", callback_data="admin_broadcast"),
        InlineKeyboardButton("📊 Statistika", callback_data="admin_stats"),
        InlineKeyboardButton("👨‍💻 Admin goş", callback_data="admin_add_admin"),
        InlineKeyboardButton("📋 Admin sanawy", callback_data="admin_list_admins"),
        InlineKeyboardButton("👨‍💻 Admin aýyr", callback_data="admin_remove_admin")
    )

    bot.send_message(
        message.chat.id,
        "🛠️ *Admin Paneli*\nAşakdan islendik işi saýlaň:",
        parse_mode="Markdown",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    global admin_lock

    if call.data.startswith("admin_") and call.from_user.id not in ADMIN_IDS:
        return

    if admin_lock:
        bot.answer_callback_query(call.id, "Başga işlem tamamlanýança garaşyň.", show_alert=True)
        return

    if call.data not in ["admin_vpn", "admin_startmsg"]:
        admin_lock = True

    try:
        if call.data == "admin_vpn":
            msg = bot.send_message(call.message.chat.id, "Täze VPN habaryny giriziň:")
            bot.register_next_step_handler(msg, update_vpn_mesaji)

        elif call.data == "admin_startmsg":
            msg = bot.send_message(call.message.chat.id, "Täze giriş habaryny giriziň:")
            bot.register_next_step_handler(msg, update_giris_mesaji)

        elif call.data == "admin_add_channel":
            msg = bot.send_message(call.message.chat.id, "Täze kanal adyny giriziň (@ bilen):")
            bot.register_next_step_handler(msg, add_channel)

        elif call.data == "admin_remove_channel":
            msg = bot.send_message(call.message.chat.id, "Aýyrmak isleýän kanal adyny giriziň (@ bilen):")
            bot.register_next_step_handler(msg, remove_channel)

        elif call.data == "admin_edit_channel":
            msg = bot.send_message(call.message.chat.id, "Üýtgetmek isleýän kanal adyny giriziň (@ bilen):")
            bot.register_next_step_handler(msg, edit_channel)

        elif call.data == "admin_broadcast":
            msg = bot.send_message(call.message.chat.id, "Ugratmak isleýän habaryňyzy giriziň:")
            bot.register_next_step_handler(msg, broadcast_message)

        elif call.data == "admin_stats":
            stats = f"Jemi ulanyjylar: {len(users)}\nVPN alanlar: {len(vpn_alanlar)}"
            bot.send_message(call.message.chat.id, stats)

        elif call.data == "admin_add_admin":
            msg = bot.send_message(call.message.chat.id, "Admin bermek isleýän ID-ni giriziň:")
            bot.register_next_step_handler(msg, add_admin)

        elif call.data == "admin_remove_admin":
            msg = bot.send_message(call.message.chat.id, "Admin aýyrmak isleýän ID-ni giriziň:")
            bot.register_next_step_handler(msg, remove_admin)

        elif call.data == "admin_list_admins":
            markup = InlineKeyboardMarkup(row_width=1)
            for admin_id in ADMIN_IDS:
                try:
                    user = bot.get_chat(admin_id)
                    admin_name = user.first_name if user.first_name else "Ady ýok"
                    markup.add(InlineKeyboardButton(admin_name, url=f"tg://user?id={admin_id}"))
                except:
                    continue
            bot.send_message(call.message.chat.id, "Admin sanawy:", reply_markup=markup)

        elif call.data == "admin_list_channels":
            if not kanallar:
                bot.send_message(call.message.chat.id, "Hiç hili kanal goşulmady.")
            else:
                kanal_listesi = "\n".join([f"{i+1}. {k['username']}" for i, k in enumerate(kanallar)])
                mesaj = f"📜 *Botdaky Kanallar* 👇\n{kanal_listesi}"
                markup = InlineKeyboardMarkup(row_width=1)
                markup.add(InlineKeyboardButton("🔙 Yza", callback_data="back_to_admin"))
                bot.send_message(call.message.chat.id, mesaj, parse_mode=None, reply_markup=markup)

        elif call.data == "back_to_admin":
            admin_panel(call.message)

        elif call.data == "check_channels":
            kontrol_edilecek = [k for k in kanallar if k.get("check_membership", False)]
            eksik_kanallar = [
                kanal for kanal in kontrol_edilecek
                if not is_user_member_of_channel(call.from_user.id, kanal['username'])
            ]

            if eksik_kanallar:
                isimler = "\n".join([k["name"] for k in eksik_kanallar])
                bot.answer_callback_query(call.id, f"Aşakdaky kanallara goşulmandyňyz:\n{isimler}", show_alert=True)
            else:
                vpn_alanlar.add(call.from_user.id)
                bot.send_message(call.from_user.id, vpn_mesaji)

    finally:
        if call.data not in ["admin_vpn", "admin_startmsg"]:
            admin_lock = False

# === ADMIN FUNKSIÝALARY ===

def update_vpn_mesaji(message):
    global vpn_mesaji, admin_lock
    vpn_mesaji = message.text
    bot.send_message(message.chat.id, "VPN habary üstünlikli täzelendi.")
    admin_lock = False

def update_giris_mesaji(message):
    global giris_mesaji, admin_lock
    giris_mesaji = message.text
    bot.send_message(message.chat.id, "Giriş habary üstünlikli täzelendi.")
    admin_lock = False

def add_channel(message):
    global admin_lock
    if message.chat.id not in ADMIN_IDS:
        return

    kanal_adi = message.text.strip()
    if not kanal_adi.startswith("@"):
        bot.send_message(message.chat.id, "Kanal ady '@' bilen başlamaly!")
        admin_lock = False
        return

    try:
        chat_member = bot.get_chat_member(kanal_adi, bot.get_me().id)
        is_admin = chat_member.status in ["administrator", "creator"]
    except Exception:
        is_admin = False

    kanallar.append({
        'username': kanal_adi,
        'name': kanal_adi.lstrip("@"),
        'check_membership': is_admin
    })

    durum = "kontrol ediler" if is_admin else "kontrol edilmez"
    bot.send_message(message.chat.id, f"{kanal_adi} kanala goşuldy. ({durum})")
    admin_lock = False

def remove_channel(message):
    global admin_lock
    kanal_adi = message.text
    kanal_dict = next((k for k in kanallar if k["username"] == kanal_adi), None)
    if kanal_dict:
        kanallar.remove(kanal_dict)
        bot.send_message(message.chat.id, f"{kanal_adi} kanaldan aýryldy.")
    else:
        bot.send_message(message.chat.id, f"{kanal_adi} kanal tapylmady.")
    admin_lock = False

def edit_channel(message):
    kanal_adi = message.text
    kanal_dict = next((k for k in kanallar if k["username"] == kanal_adi), None)
    if kanal_dict:
        msg = bot.send_message(message.chat.id, "Täze kanal adyny giriziň:")
        bot.register_next_step_handler(msg, lambda m: update_channel_name(m, kanal_dict))
    else:
        bot.send_message(message.chat.id, f"{kanal_adi} kanal tapylmady.")
    global admin_lock
    admin_lock = False

def update_channel_name(message, kanal_dict):
    global admin_lock
    new_username = message.text
    kanal_dict["username"] = new_username
    kanal_dict["name"] = new_username.lstrip("@")
    bot.send_message(message.chat.id, f"Kanal täze ady bilen täzelendi: {new_username}")
    admin_lock = False

def broadcast_message(message):
    global admin_lock
    text = message.text
    for user_id in users:
        try:
            bot.send_message(user_id, text)
        except:
            continue
    bot.send_message(message.chat.id, "Habar ähli ulanyjylara ugradyldy.")
    admin_lock = False

def add_admin(message):
    global admin_lock
    try:
        new_admin_id = int(message.text)
        ADMIN_IDS.add(new_admin_id)
        bot.send_message(message.chat.id, f"{new_admin_id} ID admin boldy!")
    except ValueError:
        bot.send_message(message.chat.id, "Nädogry ID formaty. Diňe san giriziň.")
    admin_lock = False

def remove_admin(message):
    global admin_lock
    try:
        remove_id = int(message.text)
        if remove_id in ADMIN_IDS:
            ADMIN_IDS.remove(remove_id)
            bot.send_message(message.chat.id, f"{remove_id} admin hukuklary aýryldy!")
        else:
            bot.send_message(message.chat.id, "Bu ID adminleriň arasynda ýok.")
    except ValueError:
        bot.send_message(message.chat.id, "Nädogry ID formaty. Diňe san giriziň.")
    admin_lock = False

def is_user_member_of_channel(user_id, kanal_username):
    try:
        status = bot.get_chat_member(kanal_username, user_id).status
        return status in ('member', 'administrator', 'creator')
    except:
        return False

# Botu başlat
bot.polling(none_stop=True)