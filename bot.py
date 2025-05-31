# taze_webhook.py
import logging
import json
import os
import asyncio
from datetime import datetime
from typing import Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from fastapi import FastAPI, Request, Response, HTTPException
import uvicorn

# --- Logging Configuration ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Environment Variables & Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable not set!")
    exit(1)

ADMIN_ID_STR = os.environ.get("ADMIN_ID")
if not ADMIN_ID_STR or not ADMIN_ID_STR.isdigit():
    logger.error("ADMIN_ID environment variable not set or invalid!")
    exit(1)
ADMIN_ID = int(ADMIN_ID_STR)

WEBHOOK_URL = os.environ.get("WEBHOOK_URL") # e.g., https://your-app-name.onrender.com
if not WEBHOOK_URL:
    logger.error("WEBHOOK_URL environment variable not set!")
    exit(1)

# The secret path part of your webhook URL, e.g., WEBHOOK_URL/SECRET_PATH
# Using BOT_TOKEN as path is a common practice for simplicity, as it's already a secret.
# You could use a different secret string if you prefer.
SECRET_PATH = os.environ.get("SECRET_PATH", BOT_TOKEN)

PORT = int(os.environ.get("PORT", 8080)) # Port Render will expose

USERS_FILE = "users.json"
TEST_CODES_FILE = "test_codes.txt"
PROMO_FILE = "promocodes.json"

# --- Global Variables & File Initialization ---
active_orders: Dict[str, str] = {} # User ID <-> Admin ID for active chats

# Ensure data files exist
for file_path in [USERS_FILE, TEST_CODES_FILE, PROMO_FILE]:
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding='utf-8') as f:
            if file_path in [USERS_FILE, PROMO_FILE]:
                json.dump({}, f)
            elif file_path == TEST_CODES_FILE:
                f.write("") # Initialize with empty string
        logger.info(f"Created empty file: {file_path}")

# --- Database Class (unchanged) ---
class Database:
    @staticmethod
    def _read_json_file(file_path: str) -> Dict[Any, Any]:
        try:
            with open(file_path, "r", encoding='utf-8') as f:
                content = f.read()
                if not content: # Handle empty file case
                    return {}
                return json.loads(content)
        except FileNotFoundError:
            logger.warning(f"File not found: {file_path}, returning empty dict.")
            return {}
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {file_path}, returning empty dict.")
            return {} # Or handle more gracefully, e.g., by creating a backup and new file

    @staticmethod
    def _write_json_file(file_path: str, data: Dict[Any, Any]):
        try:
            with open(file_path, "w", encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error writing JSON to {file_path}: {e}")

    @staticmethod
    def read_db() -> Dict[Any, Any]:
        return Database._read_json_file(USERS_FILE)

    @staticmethod
    def save_db(data: Dict[Any, Any]):
        Database._write_json_file(USERS_FILE, data)

    @staticmethod
    def read_test_codes() -> str:
        try:
            with open(TEST_CODES_FILE, "r", encoding='utf-8') as f:
                return f.read().strip()
        except FileNotFoundError:
            logger.warning(f"File not found: {TEST_CODES_FILE}, returning empty string.")
            return ""
        except Exception as e:
            logger.error(f"Error reading test codes from {TEST_CODES_FILE}: {e}")
            return ""


    @staticmethod
    def write_test_codes(code: str):
        try:
            with open(TEST_CODES_FILE, "w", encoding='utf-8') as f:
                f.write(code)
        except Exception as e:
            logger.error(f"Error writing test codes to {TEST_CODES_FILE}: {e}")


    @staticmethod
    def read_promos() -> Dict[Any, Any]:
        return Database._read_json_file(PROMO_FILE)

    @staticmethod
    def write_promos(promos: Dict[Any, Any]):
        Database._write_json_file(PROMO_FILE, promos)

# --- Telegram Bot Handlers (largely unchanged, ensure they are async) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return # Should not happen with user-initiated commands
    user_id = str(user.id)
    users = Database.read_db()

    if context.args and len(context.args) > 0 and context.args[0].isdigit():
        referrer_id = context.args[0]
        if referrer_id in users and user_id != referrer_id:
            # Ensure 'referrals' list exists
            if 'referrals' not in users[referrer_id]:
                users[referrer_id]['referrals'] = []
            if user_id not in users[referrer_id].get('referrals', []):
                users[referrer_id]['ref_count'] = users[referrer_id].get('ref_count', 0) + 1
                users[referrer_id]['referrals'].append(user_id)
                Database.save_db(users)
                logger.info(f"User {user_id} referred by {referrer_id}")

    if user_id not in users:
        users[user_id] = {
            "keys": [],
            "ref_count": 0,
            "referrals": [],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        Database.save_db(users)
        logger.info(f"New user {user_id} ({user.full_name}) started the bot.")

    if user.id == ADMIN_ID:
        await show_admin_menu(update, context)
    else:
        await show_main_menu(update, user)

async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = Database.read_db()
    active_users_count = 0
    if users: # Check if users is not None and not empty
        active_users_count = len([u for u in users.values() if u.get('keys')])
    
    total_refs = 0
    if users: # Check if users is not None and not empty
        total_refs = sum(u.get('ref_count', 0) for u in users.values())


    text = f"""🔧 Admin panel

👥 Jemi ulanyjylar: {len(users) if users else 0}
✅ Aktiw ulanyjylar: {active_users_count}
🎁 Jemi referallar: {total_refs}"""

    keyboard = [
        [InlineKeyboardButton("📤 Test kody üýtget", callback_data="admin_change_test"), InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton("📩 Habar iber", callback_data="admin_broadcast"), InlineKeyboardButton("📦 Users bazasy", callback_data="admin_export")],
        [InlineKeyboardButton("🎟 Promokod goş", callback_data="admin_add_promo_btn"), InlineKeyboardButton("🎟 Promokod poz", callback_data="admin_remove_promo_btn")], # Renamed to avoid conflict with command
        [InlineKeyboardButton("🔙 Baş sahypa", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception as e: # Handle "message is not modified"
            logger.warning(f"Error editing message for admin menu (might be identical): {e}")
            await update.callback_query.answer("Menu is already up to date.") # Notify admin

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query: return
    users = Database.read_db()
    active_users_count = 0
    if users:
        active_users_count = len([u for u_id, u_data in users.items() if u_data.get('keys')])
    
    total_refs = 0
    if users:
        total_refs = sum(u_data.get('ref_count', 0) for u_data in users.values())


    text = f"""📊 *Bot statistikasy* 👥 Jemi ulanyjylar: {len(users) if users else 0}
✅ Aktiw ulanyjylar: {active_users_count}
🎁 Jemi referallar: {total_refs}
🕒 Soňky aktivlik: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Yza", callback_data="admin_panel")]]),
        parse_mode="Markdown"
    )

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query or not update.callback_query.message : return
    await update.callback_query.message.reply_text("📨 Ýaýlym habaryny iberiň (ähli ulanyjylara gider):")
    context.user_data["broadcasting"] = True # type: ignore

async def admin_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query or not update.callback_query.message : return
    if os.path.exists(USERS_FILE) and os.path.getsize(USERS_FILE) > 0:
        with open(USERS_FILE, "rb") as f:
            await update.callback_query.message.reply_document(f)
    else:
        await update.callback_query.message.reply_text("❌ Ulanyjy bazasy boş ýa-da tapylmady.")

async def admin_add_promo_btn(update: Update, context: ContextTypes.DEFAULT_TYPE): # Renamed from admin_add_promo
    if not update.callback_query or not update.callback_query.message : return
    await update.callback_query.message.reply_text("🎟 Täze promokod we skidkany ýazyň (mysal üçin: PROMO10 10):")
    context.user_data["adding_promo"] = True # type: ignore

async def admin_remove_promo_btn(update: Update, context: ContextTypes.DEFAULT_TYPE): # Renamed from admin_remove_promo
    if not update.callback_query or not update.callback_query.message : return
    promos = Database.read_promos()
    if not promos:
        await update.callback_query.message.reply_text("❌ Promokodlar ýok!")
        return

    keyboard = [[InlineKeyboardButton(promo, callback_data=f"remove_{promo}")] for promo in promos.keys()]
    keyboard.append([InlineKeyboardButton("🔙 Yza", callback_data="admin_panel")])
    await update.callback_query.edit_message_text( # edit instead of reply
        "🎟 Pozmaly promokody saýlaň:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_change_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query or not update.callback_query.message : return
    await update.callback_query.message.reply_text("✏️ Täze test kody iberiň:")
    context.user_data["waiting_for_test"] = True # type: ignore

async def show_main_menu(update: Update, user_obj: Any): # Pass user object
    text = f"""Merhaba, {user_obj.full_name} 👋 

🔑 Açarlarym - bassaňyz size mugt berilen ýa-da platny berilen kodlary ýatda saklap berer.
🎁 Referal - bassaňyz size Referal (dostlarınız) çagyryp platny kod almak üçin mümkinçilik berer.
🆓 Test Kody almak - bassaňyz siziň üçin Outline (ss://) kodyny berer.
💰 VPN Bahalary - bassaňyz platny vpn'leri alyp bilersiňiz.
🎟 Promokod - bassaňyz promokod ýazylýan ýer açylar.

'Bildirim' - 'Уведомления' Açyk goýn, sebäbi Test kody tazelenende wagtynda bot arkaly size habar beriler."""

    keyboard = [
        [InlineKeyboardButton("🔑 Açarlarym", callback_data="my_keys")],
        [InlineKeyboardButton("🎁 Referal", callback_data="referral"), InlineKeyboardButton("🆓 Test Kody Almak", callback_data="get_test")],
        [InlineKeyboardButton("💰 VPN Bahalary", callback_data="vpn_prices"), InlineKeyboardButton("🎟 Promokod", callback_data="use_promo")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query: # If called from a callback query (e.g. back button)
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Error editing message for main menu (might be identical): {e}")
            await update.callback_query.answer()


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_orders
    query = update.callback_query
    if not query or not query.from_user or not query.message: return
    await query.answer()
    data = query.data
    user_id = str(query.from_user.id)
    users = Database.read_db()

    if data == "my_keys":
        user_data = users.get(user_id, {})
        keys = user_data.get("keys", [])
        text = "Siziň açarlaryňyz:\n" + "\n".join(f"`{key}`" for key in keys) if keys else "Siziň açarlaryňyz ýok." # Added code block for keys
        # Removed the extra button layer, directly show keys or message
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Yza", callback_data="main_menu")]]), parse_mode="Markdown")

    elif data == "referral":
        ref_link = f"https://t.me/{context.bot.username}?start={user_id}"
        ref_count = users.get(user_id, {}).get("ref_count", 0)
        text = f"""Siz 5 adam çagyryp platny kod alyp bilersiňiz 🎁 

Referal sylkaňyz: `{ref_link}`

Referal sanyňyz: {ref_count}"""
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Yza", callback_data="main_menu")]]), parse_mode="Markdown")

    elif data == "get_test":
        test_kod = Database.read_test_codes()
        await query.edit_message_text("Test Kodyňyz Ýasalýar...")
        await asyncio.sleep(1) # Reduced sleep
        final_text = f"`{test_kod}`" if test_kod else "Häzirki wagtda test kody ýok."
        await query.edit_message_text(final_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Yza", callback_data="main_menu")]]), parse_mode="Markdown")

    elif data == "use_promo":
        await query.edit_message_text("🎟 Promokody ýazyň:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Yza", callback_data="main_menu")]]))
        context.user_data["waiting_for_promo"] = True # type: ignore

    elif data == "vpn_prices":
        base_prices = {"vpn_3": 20, "vpn_7": 40, "vpn_15": 100, "vpn_30": 150} # Corrected last price
        discount = context.user_data.get("promo_discount", 0) if context.user_data else 0 # type: ignore
        
        prices_text = (
            "**Eger platny kod almakçy bolsaňyz aşakdaky knopka basyň we BOT arkaly admin'iň size ýazmagyna garaşyn📍**\n"
            "-----------------------------------------------\n"
            "🌍 **VPN adı: Shadowsocks**🛍️\n"
            "-----------------------------------------------\n"
        )
        if discount > 0:
            prices_text += f"🎉 **Siziň {discount}% promokod skidkaňyz bar!** 🎉\n\n"

        price_lines = []
        for key, price in base_prices.items():
            days_map = {"vpn_3": "3 Gün'lik", "vpn_7": "Hepdelik (7 gün)", "vpn_15": "15 Gün'lik", "vpn_30": "Aýlyk (30 gün)"}
            day_text = days_map.get(key, f"{key.split('_')[1]} Gün'lik") # Default if key not in map
            
            original_price_str = f"{price} тмт"
            if discount > 0:
                discounted_price = price * (1 - discount / 100)
                price_lines.append(f"🕯️ {day_text}: ~{original_price_str}~ **{discounted_price:.0f} тмт**")
            else:
                price_lines.append(f"🕯️ {day_text}: {original_price_str}")
        
        prices_text += "\n".join(price_lines)

        keyboard_layout = []
        row = []
        for key, price in base_prices.items():
            final_price = price * (1 - discount / 100) if discount > 0 else price
            button_text = f"📅 {key.split('_')[1]} gün - {final_price:.0f} 𝚃𝙼𝚃"
            button = InlineKeyboardButton(button_text, callback_data=f"order_{key.split('_')[1]}_{final_price:.0f}")
            row.append(button)
            if len(row) == 2:
                keyboard_layout.append(row)
                row = []
        if row: # Add any remaining buttons
            keyboard_layout.append(row)
        keyboard_layout.append([InlineKeyboardButton("🔙 Yza", callback_data="main_menu")])
        
        await query.edit_message_text(
            text=prices_text,
            reply_markup=InlineKeyboardMarkup(keyboard_layout),
            parse_mode="Markdown"
        )

    elif data.startswith("order_"): # e.g. order_3_20.0
        parts = data.split("_")
        days = parts[1]
        price_ordered = parts[2] # Price at the time of order
        user = query.from_user
        
        order_message_text = f"✅ Siz {days} günlük VPN ({price_ordered} TMT) üçin sargyt etdiňiz."
        await context.bot.send_message(chat_id=user.id, text=order_message_text)
        await asyncio.sleep(0.5)
        await context.bot.send_message(chat_id=user.id, text="⏳ Tiz wagtdan admin size ýazar. Admin bilen şu çatda habarlaşyp bilersiňiz.")
        await asyncio.sleep(0.5)
        # Removed /stop command hint as direct chat will be established

        admin_text = f"🆕 Täze sargyt:\n👤 Ulanyjy: {user.full_name} (@{user.username} - `{user.id}`)\n📆 Sargyt: {days} günlük ({price_ordered} TMT)"
        keyboard = [[InlineKeyboardButton("✅ Kabul et & Çat başla", callback_data=f"accept_{user.id}_{days}")]]
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        await query.answer("Sargydyňyz admine ýetirildi.")


    elif data.startswith("accept_"):
        _, target_id_str, days = data.split("_")
        target_id = int(target_id_str)
        
        active_orders[str(target_id)] = str(ADMIN_ID)
        active_orders[str(ADMIN_ID)] = str(target_id)

        keyboard = [[InlineKeyboardButton("🚫 Sargydy/Çaty ýapmak", callback_data=f"close_{target_id}")]]
        await query.edit_message_text( # Edit the admin's message
            text=f"✅ Sargyt kabul edildi! Indi ulanyjy ({target_id}) bilen şu çatda ýazyşyp bilersiňiz.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await context.bot.send_message(
            chat_id=target_id,
            text="✅ Sargydyňyz kabul edildi! Indi admin bilen şu ýerde habarlaşyp bilersiňiz."
        )

    elif data.startswith("close_"):
        target_id_str = data.split("_")[1]
        admin_id_str = str(query.from_user.id) # Should be admin

        closed_for_user = False
        if target_id_str in active_orders and active_orders[target_id_str] == admin_id_str:
            del active_orders[target_id_str]
            closed_for_user = True
        
        closed_for_admin = False
        if admin_id_str in active_orders and active_orders[admin_id_str] == target_id_str:
            del active_orders[admin_id_str]
            closed_for_admin = True

        if closed_for_user or closed_for_admin:
            await query.edit_message_text("✅ Çat ýapyldy!")
            try:
                await context.bot.send_message(chat_id=int(target_id_str), text="🔒 Admin bilen çat ýapyldy. Täze sargyt edip bilersiňiz.")
            except Exception as e:
                logger.error(f"Could not notify user {target_id_str} about chat closure: {e}")
        else:
            await query.answer("❌ Bu çat eýýäm ýapyk ýa-da degişli däl.", show_alert=True)


    elif data.startswith("remove_"): # For removing promo codes
        promo_to_remove = data.split("_", 1)[1]
        promos = Database.read_promos()
        if promo_to_remove in promos:
            del promos[promo_to_remove]
            Database.write_promos(promos)
            await query.answer(f"✅ Promokod {promo_to_remove} pozuldy!", show_alert=True)
            # Refresh the list or go back
            await admin_remove_promo_btn(update, context) # Refresh the list
        else:
            await query.answer("❌ Promokod tapylmady!", show_alert=True)

    elif data == "admin_panel":
        await show_admin_menu(update, context)
    elif data == "main_menu":
        if query.from_user.id == ADMIN_ID:
            await show_admin_menu(update, context) # Admin goes to admin panel from main menu
        else:
            await show_main_menu(update, query.from_user)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_orders
    user = update.effective_user
    if not user or not update.message: return

    text = update.message.text.strip() if update.message.text else ""
    photo = update.message.photo[-1] if update.message.photo else None
    user_id_str = str(user.id)

    # Handle stateful inputs (promo codes, test codes, broadcast)
    if context.user_data:
        if context.user_data.get("waiting_for_test") and user.id == ADMIN_ID:
            Database.write_test_codes(text)
            await update.message.reply_text(f"✅ Täze test kody bellendi:\n`{text}`", parse_mode="Markdown")
            del context.user_data["waiting_for_test"]
            await show_admin_menu(update, context) # Show admin menu again
            return

        if context.user_data.get("broadcasting") and user.id == ADMIN_ID:
            del context.user_data["broadcasting"]
            users_db = Database.read_db()
            if not users_db:
                await update.message.reply_text("❌ Ulanyjy ýok, habar iberilmedi.")
                return

            sent_count = 0
            failed_count = 0
            await update.message.reply_text(f"📢 {len(users_db)} ulanyja habar ýaýlymy başlandy...")
            for uid_to_broadcast in users_db.keys():
                try:
                    await context.bot.send_message(chat_id=int(uid_to_broadcast), text=f"📣 Täze habar:\n\n{text}")
                    sent_count += 1
                    await asyncio.sleep(0.1) # Avoid hitting rate limits too hard
                except Exception as e:
                    logger.error(f"Failed to send broadcast to {uid_to_broadcast}: {e}")
                    failed_count +=1
            await update.message.reply_text(f"✅ Habar ýaýlymy tamamlandy.\n{sent_count} ulanyja iberildi.\n{failed_count} ulanyja iberilmedi.")
            await show_admin_menu(update, context)
            return

        if context.user_data.get("adding_promo") and user.id == ADMIN_ID:
            del context.user_data["adding_promo"]
            try:
                promo_code, discount_str = text.split()
                discount = int(discount_str)
                if not (1 <= discount <= 100): raise ValueError("Prosent aralykda däl")
                promos = Database.read_promos()
                promos[promo_code.upper()] = discount
                Database.write_promos(promos)
                await update.message.reply_text(f"✅ Promokod goşuldy: {promo_code.upper()} ({discount}%)")
            except ValueError:
                await update.message.reply_text("❌ Nädogry format. Mysal: KOD10 10")
            await show_admin_menu(update, context)
            return

        if context.user_data.get("waiting_for_promo"): # For regular users
            del context.user_data["waiting_for_promo"]
            promos = Database.read_promos()
            promo_code_entered = text.upper()
            if promo_code_entered in promos:
                discount_val = promos[promo_code_entered]
                context.user_data["promo_discount"] = discount_val # type: ignore
                await update.message.reply_text(f"✅ {discount_val}% skidka promokodyňyz kabul edildi! Indi VPN bahalaryny görüp bilersiňiz.")
                # Automatically show VPN prices with discount
                # Create a dummy user object for show_main_menu call if needed or adapt vpn_prices directly
                # For simplicity, just inform and let them click again
                # await button_handler(update, context) # This won't work directly as update isn't a callback query
                # Instead, resend the main menu or prices menu.
                # Let's guide them to click VPN Bahalary again.
                await update.message.reply_text("Indi '💰 VPN Bahalary' düwmesine basyp, täze bahalary görüň.")
            else:
                await update.message.reply_text("❌ Promokod nädogry ýa-da möhleti geçen.")
            # Always show main menu after promo attempt for non-admins
            await show_main_menu(update, user)
            return

    # Handle active chats between user and admin
    if user_id_str in active_orders:
        target_id_str = active_orders[user_id_str]
        sender_name = "Ulanyjy" if user.id != ADMIN_ID else "Admin"
        if photo:
            await context.bot.send_photo(chat_id=target_id_str, photo=photo.file_id, caption=f"👤 {sender_name} ({user.full_name}): [Surat]")
        elif text: # ensure text is not empty
             await context.bot.send_message(chat_id=target_id_str, text=f"💬 {sender_name} ({user.full_name}):\n{text}")
        return # Message relayed, stop further processing

    # Admin sending key directly to user in an active chat
    if user.id == ADMIN_ID and any(text.startswith(proto) for proto in ("ss://", "vmess://", "trojan://", "vless://", "tuic://", "hysteria2://", "hy2://", "nekoray://")):
        # Check if this admin is in an active chat with someone
        potential_target_id_str = active_orders.get(str(ADMIN_ID))
        if potential_target_id_str:
            users = Database.read_db()
            # Ensure user exists in DB, create if not
            if potential_target_id_str not in users:
                users[potential_target_id_str] = {"keys": [], "ref_count": 0, "referrals": [], "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            
            # Ensure 'keys' list exists
            if 'keys' not in users[potential_target_id_str]:
                users[potential_target_id_str]['keys'] = []
                
            users[potential_target_id_str]["keys"].append(text)
            Database.save_db(users)
            await update.message.reply_text(f"✅ Açar üstünlikli şu ulanyja ({potential_target_id_str}) goşuldy we iberildi.")
            await context.bot.send_message(chat_id=int(potential_target_id_str), text=f"🔑 Admin size täze VPN açar iberdi:\n`{text}`", parse_mode="Markdown")
            return # Key sent and saved

    # User saving a key (if not in active chat - might be from other sources)
    if user.id != ADMIN_ID and any(text.startswith(proto) for proto in ("ss://", "vmess://", "trojan://", "vless://", "tuic://", "hysteria2://", "hy2://", "nekoray://")):
        users = Database.read_db()
        # Ensure user exists in DB, create if not (though /start should handle this)
        if user_id_str not in users:
             users[user_id_str] = {"keys": [], "ref_count": 0, "referrals": [], "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        
        # Ensure 'keys' list exists
        if 'keys' not in users[user_id_str]:
            users[user_id_str]['keys'] = []

        users[user_id_str]["keys"].append(text)
        Database.save_db(users)
        await update.message.reply_text("✅ Açar üstünlikli 'Açarlarym' bölümüne goşuldy!")
        return

    # If no specific state or active chat, and message is not a command, show main menu (for non-admins)
    if user.id != ADMIN_ID and text and not text.startswith('/'): # Avoid re-triggering on commands
        logger.info(f"User {user_id_str} sent unhandled text: {text}. Showing main menu.")
        await show_main_menu(update, user)


async def vpn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Bu buýrugy diňe admin ulanyp biler!") # type: ignore
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("❌ Ulanyş usuly: /vpn <ulanyjy_id> <açar_kody>") # type: ignore
        return

    target_id = context.args[0]
    key = " ".join(context.args[1:]).strip()

    if not any(key.startswith(proto) for proto in ("ss://", "vmess://", "trojan://", "vless://", "tuic://", "hysteria2://", "hy2://", "nekoray://")):
        await update.message.reply_text("❌ Açar formaty nädogry! (ss://, vmess://, etc. bolmaly)") # type: ignore
        return

    users = Database.read_db()
    # Ensure user exists in DB, create if not
    if target_id not in users:
        users[target_id] = {"keys": [], "ref_count": 0, "referrals": [], "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    
    # Ensure 'keys' list exists
    if 'keys' not in users[target_id]:
        users[target_id]['keys'] = []
        
    users[target_id]["keys"].append(key)
    Database.save_db(users)

    await update.message.reply_text(f"✅ Açar üstünlikli {target_id} ID-li ulanyja goşuldy.") # type: ignore
    try:
        await context.bot.send_message(chat_id=int(target_id), text=f"🔑 Admin size täze VPN açar berdi:\n`{key}`", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to send key to user {target_id} via PM: {e}")
        await update.message.reply_text(f"⚠️ Ulanyja PM iberilmedi (mümkin boty bloklan ýa-da ID ýalňyş). Ýöne açar bazada saklandy.") # type: ignore

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This command is now less relevant as chats are managed via close_ buttons
    # but can serve as a user-side way to signal they want to end interaction if stuck
    global active_orders
    if not update.effective_user: return
    user_id_str = str(update.effective_user.id)
    
    admin_counterpart = None
    if user_id_str in active_orders:
        admin_counterpart = active_orders.pop(user_id_str)
    
    user_counterpart = None
    # If admin uses /stop, it should also clear their side
    if user_id_str == str(ADMIN_ID):
        # Find which user admin was talking to
        for u_id, adm_id in list(active_orders.items()): # Iterate over a copy
            if adm_id == user_id_str:
                user_counterpart = u_id
                del active_orders[u_id]
                break
    
    if admin_counterpart:
        if admin_counterpart in active_orders: # remove reverse mapping
            del active_orders[admin_counterpart]
        await update.message.reply_text("🔕 Admin bilen aragatnaşyk kesildi (siziň tarapyňyzdan).") # type: ignore
        try:
            await context.bot.send_message(chat_id=int(admin_counterpart), text=f"ℹ️ Ulanyjy {update.effective_user.full_name} ({user_id_str}) aragatnaşygy kesdi.")
        except Exception as e:
            logger.error(f"Could not notify admin {admin_counterpart} about user stopping: {e}")

    elif user_counterpart: # Admin stopped
        await update.message.reply_text(f"🔕 Ulanyjy {user_counterpart} bilen aragatnaşyk kesildi (siziň tarapyňyzdan).") # type: ignore
        try:
            await context.bot.send_message(chat_id=int(user_counterpart), text="ℹ️ Admin sizin bilen aragatnaşygy kesdi.")
        except Exception as e:
             logger.error(f"Could not notify user {user_counterpart} about admin stopping: {e}")
    else:
        await update.message.reply_text("ℹ️ Häzirki wagtda aktiv çat ýok.") # type: ignore


async def add_promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    if not update.message: return

    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Ullanylyşy: /add_promo <KOD> <SKIDKA_PROSENTI>")
        return
    
    promo_code, discount_str = context.args
    try:
        discount = int(discount_str)
        if not (1 <= discount <= 100):
            raise ValueError("Prosent aralygy 1-100 bolmaly.")
    except ValueError as e:
        await update.message.reply_text(f"Nädogry skidka: {e}")
        return
    
    promos = Database.read_promos()
    promos[promo_code.upper()] = discount
    Database.write_promos(promos)
    await update.message.reply_text(f"✅ Skidka: {promo_code.upper()} ({discount}%) Üstünlikli goşuldy!")

async def remove_promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    if not update.message: return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Ullanylyşy: /remove_promo <KOD>")
        return
    
    promo_code_to_remove = context.args[0].upper()
    promos = Database.read_promos()
    if promo_code_to_remove in promos:
        del promos[promo_code_to_remove]
        Database.write_promos(promos)
        await update.message.reply_text(f"✅ Promokod '{promo_code_to_remove}' üstünlikli pozuldy!")
    else:
        await update.message.reply_text(f"❌ '{promo_code_to_remove}' atly promokod tapylmady!")


# --- FastAPI Application ---
fastapi_app = FastAPI()
ptb_application: Application # Will be initialized in lifespan

async def lifespan(app: FastAPI):
    global ptb_application
    logger.info("FastAPI application starting up...")
    
    # Initialize PTB application
    ptb_builder = Application.builder().token(BOT_TOKEN)
    # If you have a custom BasePersistence, set it here:
    # persistence = PicklePersistence(filepath="bot_persistence") # Example
    # ptb_builder.persistence(persistence)
    ptb_application = ptb_builder.build()

    # Register handlers
    ptb_application.add_handler(CommandHandler("start", start))
    ptb_application.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    ptb_application.add_handler(CallbackQueryHandler(admin_broadcast, pattern="^admin_broadcast$"))
    ptb_application.add_handler(CallbackQueryHandler(admin_export, pattern="^admin_export$"))
    ptb_application.add_handler(CallbackQueryHandler(admin_add_promo_btn, pattern="^admin_add_promo_btn$")) # Renamed handler
    ptb_application.add_handler(CallbackQueryHandler(admin_remove_promo_btn, pattern="^admin_remove_promo_btn$")) # Renamed handler
    ptb_application.add_handler(CallbackQueryHandler(admin_change_test, pattern="^admin_change_test$"))
    
    ptb_application.add_handler(CommandHandler("stop", stop_command))
    ptb_application.add_handler(CommandHandler("add_promo", add_promo_command)) # Command version
    ptb_application.add_handler(CommandHandler("remove_promo", remove_promo_command)) # Command version
    ptb_application.add_handler(CommandHandler("vpn", vpn_command))
    
    ptb_application.add_handler(CallbackQueryHandler(button_handler)) # Catches all other callbacks

    # Message handlers (order matters if specific filters are used)
    # Handle text messages that are not commands and photo messages
    ptb_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    ptb_application.add_handler(MessageHandler(filters.PHOTO, message_handler))


    # Initialize PTB application (fetches bot info, etc.)
    await ptb_application.initialize()

    # Set webhook
    webhook_full_url = f"{WEBHOOK_URL.rstrip('/')}/{SECRET_PATH.lstrip('/')}"
    logger.info(f"Setting webhook to: {webhook_full_url}")
    await ptb_application.bot.set_webhook(
        url=webhook_full_url,
        allowed_updates=Update.ALL_TYPES,
        # drop_pending_updates=True # Optional: good for initial setup
    )
    
    # Start PTB's internal update processing (does not start network listening for webhooks)
    await ptb_application.start()
    logger.info("PTB application started and webhook set.")
    
    yield # FastAPI app is running
    
    logger.info("FastAPI application shutting down...")
    await ptb_application.stop()
    # await ptb_application.bot.delete_webhook(drop_pending_updates=False) # Optional: cleanup webhook
    await ptb_application.shutdown()
    logger.info("PTB application shut down.")

fastapi_app.router.lifespan_context = lifespan


@fastapi_app.post(f"/{SECRET_PATH.lstrip('/')}")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, ptb_application.bot)
        logger.debug(f"Received update: {update.update_id}")
        await ptb_application.process_update(update)
        return Response(status_code=200)
    except json.JSONDecodeError:
        logger.error("Webhook received invalid JSON.")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        logger.error(f"Error processing update in webhook: {e}", exc_info=True)
        # Consider not raising HTTPException for all errors to avoid Telegram retries for non-critical issues
        return Response(status_code=200) # Acknowledge receipt to Telegram even if processing fails, to avoid retries. Log error.


@fastapi_app.get("/health")
async def health_check():
    # You can add more sophisticated checks here, e.g., ptb_application.running
    if ptb_application and ptb_application.running:
        return {"status": "ok", "bot_running": True}
    return {"status": "degraded", "bot_running": False}


if __name__ == "__main__":
    # This part is for local testing. Render will use the Procfile.
    logger.info("Starting Uvicorn server for local development...")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT)
