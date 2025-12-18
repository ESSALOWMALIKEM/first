import asyncio
import logging
import random
import json
from urllib.parse import quote, unquote
import asyncpg
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, Chat
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from keep_alive import keep_alive

keep_alive()

logging.basicConfig(level=logging.INFO)

# --- CONFIGURATION ---
API_TOKEN = '8245564742:AAFKi1RI50y9dPJDUxZwEsOPTZMNBTLaSkM'
SUPER_ADMIN_ID = 7877979174
DATABASE_URL = "postgresql://user:4OWUEBtffwv2lc65YQlDEg9danw4LLQi@dpg-d521qmv5r7bs73fqsq50-a/ghostdb_kt36"
# --- END CONFIGURATION ---

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
storage = MemoryStorage()
dp = Dispatcher(bot=bot, storage=storage)
router = Router()
dp.include_router(router)

DB_POOL = None
# YENI: Aktiw söhbetdeşlikleri we kömek isleglerini yzarlamak üçin
ACTIVE_CHATS = {}  # {user_id: admin_id}
HELP_REQUESTS = {} # {user_id: [(admin_id, message_id), ...]}


back_to_admin_markup = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⬅️ Admin panele gaýtmak", callback_data="admin_panel_main")]
])

class SubscriptionStates(StatesGroup):
    checking_subscription = State()

# --- GÜNCELLENEN VE YENİ EKLENEN DURUMLAR ---
class ChatStates(StatesGroup):
    in_chat = State() # Kullanıcı ve admin arasındaki sohbet durumu

class AdminStates(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_to_delete = State()
    waiting_for_vpn_config = State()
    waiting_for_vpn_config_to_delete = State()
    waiting_for_welcome_message = State()
    waiting_for_user_mail_action = State()
    waiting_for_mailing_message = State()
    waiting_for_mailing_confirmation = State()
    waiting_for_mailing_buttons = State()
    waiting_for_channel_mail_action = State()
    waiting_for_channel_mailing_message = State()
    waiting_for_channel_mailing_confirmation = State()
    waiting_for_channel_mailing_buttons = State()
    waiting_for_admin_id_to_add = State()
    waiting_for_addlist_url = State()
    waiting_for_addlist_name = State()

async def init_db(pool):
    async with pool.acquire() as connection:
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT);
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS channels (id SERIAL PRIMARY KEY, channel_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL);
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS addlists (id SERIAL PRIMARY KEY, name TEXT NOT NULL, url TEXT UNIQUE NOT NULL);
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS vpn_configs (id SERIAL PRIMARY KEY, config_text TEXT UNIQUE NOT NULL);
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS bot_users (user_id BIGINT PRIMARY KEY);
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (user_id BIGINT PRIMARY KEY);
        """)
        default_welcome = "👋 <b>Hoş geldiňiz!</b>\n\nVPN Koduny almak üçin, aşakdaky Kanallara Agza boluň we soňra '✅ Agza Boldum' düwmesine basyň."
        await connection.execute(
            "INSERT INTO bot_settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
            'welcome_message', default_welcome
        )

async def get_setting_from_db(key: str, default: str = None):
    async with DB_POOL.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM bot_settings WHERE key = $1", key)
        return row['value'] if row else default

async def save_setting_to_db(key: str, value: str):
    async with DB_POOL.acquire() as conn:
        await conn.execute(
            "INSERT INTO bot_settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2",
            key, value
        )

async def save_last_mail_content(content: dict, keyboard: InlineKeyboardMarkup | None, mail_type: str):
    content_json = json.dumps(content)
    await save_setting_to_db(f'last_{mail_type}_mail_content', content_json)
    if keyboard:
        keyboard_json = json.dumps(keyboard.to_python())
        await save_setting_to_db(f'last_{mail_type}_mail_keyboard', keyboard_json)
    else:
        await save_setting_to_db(f'last_{mail_type}_mail_keyboard', 'null')

async def get_last_mail_content(mail_type: str) -> tuple[dict | None, InlineKeyboardMarkup | None]:
    content, keyboard = None, None
    content_json = await get_setting_from_db(f'last_{mail_type}_mail_content')
    if content_json:
        content = json.loads(content_json)
    keyboard_json = await get_setting_from_db(f'last_{mail_type}_mail_keyboard')
    if keyboard_json and keyboard_json != 'null':
        keyboard_data = json.loads(keyboard_json)
        keyboard = InlineKeyboardMarkup.model_validate(keyboard_data)
    return content, keyboard

async def send_mail_preview(chat_id: int, content: dict, keyboard: InlineKeyboardMarkup | None = None):
    content_type = content.get('type')
    caption = content.get('caption')
    text = content.get('text')
    file_id = content.get('file_id')

    try:
        if content_type == 'text':
            return await bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")
        elif content_type == 'photo':
            return await bot.send_photo(chat_id, photo=file_id, caption=caption or '', reply_markup=keyboard, parse_mode="HTML")
        elif content_type == 'video':
            return await bot.send_video(chat_id, video=file_id, caption=caption or '', reply_markup=keyboard, parse_mode="HTML")
        elif content_type == 'animation':
            return await bot.send_animation(chat_id, animation=file_id, caption=caption or '', reply_markup=keyboard, parse_mode="HTML")
        elif content_type == 'document':
            return await bot.send_document(chat_id, document=file_id, caption=caption or '', reply_markup=keyboard, parse_mode="HTML")
        elif content_type == 'audio':
            return await bot.send_audio(chat_id, audio=file_id, caption=caption or '', reply_markup=keyboard, parse_mode="HTML")
        elif content_type == 'voice':
            return await bot.send_voice(chat_id, voice=file_id, caption=caption or '', reply_markup=keyboard, parse_mode="HTML")
        else:
            return await bot.send_message(chat_id, "⚠️ Format tanınmadı. Mesaj gönderilemedi.")
    except Exception as e:
        logging.error(f"Error sending mail preview to {chat_id}: {e}")
        return await bot.send_message(chat_id, f"⚠️ Gönderim hatası: {e}")

# HATA DÜZELTMESİ: .caption_html -> .caption
async def process_mailing_content(message: Message, state: FSMContext, mail_type: str):
    content = {}
    if message.photo:
        # DÜZELTME: Hata düzeltildi, .caption_html yerine .caption kullanılıyor
        content = {'type': 'photo', 'file_id': message.photo[-1].file_id, 'caption': message.caption}
    elif message.text:
        content = {'type': 'text', 'text': message.html_text}
    else:
        await message.answer("⚠️ Bu habar görnüşi goldanmaýar. Diňe tekst ýa-da surat (ýazgysy bilen) iberiň.")
        return

    await state.update_data(mailing_content=content)
    
    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = message.chat.id

    try:
        if admin_message_id:
            await bot.delete_message(admin_chat_id, admin_message_id)
    except (TelegramBadRequest, AttributeError):
        pass

    preview_text = "🗂️ <b>Öňünden tassyklaň:</b>\n\nHabaryňyz aşakdaky ýaly bolar. Iberýärismi?"
    preview_message = await send_mail_preview(admin_chat_id, content)

    confirmation_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Düwmesiz ibermek", callback_data=f"{mail_type}_mail_confirm_send")],
        [InlineKeyboardButton(text="➕ Düwmeleri goşmak", callback_data=f"{mail_type}_mail_confirm_add_buttons")],
        [InlineKeyboardButton(text="⬅️ Ýatyr", callback_data="admin_panel_main")]
    ])
    confirm_msg = await bot.send_message(admin_chat_id, preview_text, reply_markup=confirmation_keyboard)

    await state.update_data(admin_message_id=confirm_msg.message_id, preview_message_id=preview_message.message_id)

    target_state = AdminStates.waiting_for_mailing_confirmation if mail_type == "user" else AdminStates.waiting_for_channel_mailing_confirmation
    await state.set_state(target_state)

async def get_channels_from_db():
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch("SELECT channel_id, name FROM channels ORDER BY name")
        return [{"id": row['channel_id'], "name": row['name']} for row in rows]

async def add_channel_to_db(channel_id: str, name: str):
    async with DB_POOL.acquire() as conn:
        try:
            await conn.execute("INSERT INTO channels (channel_id, name) VALUES ($1, $2)", str(channel_id), name)
            return True
        except asyncpg.UniqueViolationError:
            logging.warning(f"Channel {channel_id} already exists.")
            return False
        except Exception as e:
            logging.error(f"Error adding channel {channel_id} to DB: {e}")
            return False

async def delete_channel_from_db(channel_id: str):
    async with DB_POOL.acquire() as conn:
        result = await conn.execute("DELETE FROM channels WHERE channel_id = $1", str(channel_id))
        return result != "DELETE 0"

async def get_addlists_from_db():
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch("SELECT id, name, url FROM addlists ORDER BY name")
        return [{"db_id": row['id'], "name": row['name'], "url": row['url']} for row in rows]

async def add_addlist_to_db(name: str, url: str):
    async with DB_POOL.acquire() as conn:
        try:
            await conn.execute("INSERT INTO addlists (name, url) VALUES ($1, $2)", name, url)
            return True
        except asyncpg.UniqueViolationError:
            logging.warning(f"Addlist URL {url} already exists.")
            return False
        except Exception as e:
            logging.error(f"Error adding addlist {name} to DB: {e}")
            return False

async def delete_addlist_from_db(db_id: int):
    async with DB_POOL.acquire() as conn:
        result = await conn.execute("DELETE FROM addlists WHERE id = $1", db_id)
        return result != "DELETE 0"

async def get_vpn_configs_from_db():
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch("SELECT id, config_text FROM vpn_configs ORDER BY id")
        return [{"db_id": row['id'], "config_text": row['config_text']} for row in rows]

async def add_vpn_config_to_db(config_text: str):
    async with DB_POOL.acquire() as conn:
        try:
            await conn.execute("INSERT INTO vpn_configs (config_text) VALUES ($1)", config_text)
            return True
        except asyncpg.UniqueViolationError:
            logging.warning(f"VPN config already exists.")
            return False
        except Exception as e:
            logging.error(f"Error adding VPN config to DB: {e}")
            return False

async def delete_vpn_config_from_db(db_id: int):
    async with DB_POOL.acquire() as conn:
        result = await conn.execute("DELETE FROM vpn_configs WHERE id = $1", db_id)
        return result != "DELETE 0"

async def get_users_from_db():
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM bot_users")
        return [row['user_id'] for row in rows]

async def add_user_to_db(user_id: int):
    async with DB_POOL.acquire() as conn:
        await conn.execute("INSERT INTO bot_users (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", user_id)

async def get_admins_from_db():
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM bot_admins")
        return [row['user_id'] for row in rows]

async def add_admin_to_db(user_id: int):
    async with DB_POOL.acquire() as conn:
        await conn.execute("INSERT INTO bot_admins (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", user_id)
        return True

async def delete_admin_from_db(user_id: int):
    async with DB_POOL.acquire() as conn:
        result = await conn.execute("DELETE FROM bot_admins WHERE user_id = $1", user_id)
        return result != "DELETE 0"

async def is_user_admin_in_db(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True
    admins = await get_admins_from_db()
    return user_id in admins

async def get_unsubscribed_channels(user_id: int) -> list:
    all_channels = await get_channels_from_db()
    unsubscribed = []
    for channel in all_channels:
        try:
            member = await bot.get_chat_member(chat_id=channel['id'], user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                unsubscribed.append(channel)
        except (TelegramForbiddenError, TelegramBadRequest):
            unsubscribed.append(channel)
        except Exception as e:
            logging.error(f"Error checking subscription for user {user_id} in channel {channel['id']}: {e}")
            unsubscribed.append(channel)
    return unsubscribed

def create_admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Bot statistikasy", callback_data="get_stats")],
        [InlineKeyboardButton(text="🚀 Ulanyjylara bildiriş ibermek", callback_data="start_mailing"),
         InlineKeyboardButton(text="📢 Kanallara bildiriş ibermek", callback_data="start_channel_mailing")],
        [InlineKeyboardButton(text="➕ Kanal goşmak", callback_data="add_channel"), InlineKeyboardButton(text="➖ Kanal pozmak", callback_data="delete_channel")],
        [InlineKeyboardButton(text="📜 Kanallary görmek", callback_data="list_channels")],
        [InlineKeyboardButton(text="📁 addlist goşmak", callback_data="add_addlist"), InlineKeyboardButton(text="🗑️ addlist pozmak", callback_data="delete_addlist")],
        [InlineKeyboardButton(text="🔑 VPN goşmak", callback_data="add_vpn_config"), InlineKeyboardButton(text="🗑️ VPN pozmak", callback_data="delete_vpn_config")],
        [InlineKeyboardButton(text="✏️ Başlangyç haty üýtgetmek", callback_data="change_welcome")]
    ]
    if user_id == SUPER_ADMIN_ID:
        buttons.extend([
            [InlineKeyboardButton(text="👮 Admin goşmak", callback_data="add_admin"), InlineKeyboardButton(text="🚫 Admin pozmak", callback_data="delete_admin")],
            [InlineKeyboardButton(text="👮 Adminleri görmek", callback_data="list_admins")]
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ Admin panelden çykmak", callback_data="exit_admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await add_user_to_db(user_id)
    await state.clear()

    vpn_configs = await get_vpn_configs_from_db()
    if not vpn_configs:
        await message.answer("😔 Gynansak-da, häzirki wagtda elýeterli VPN Kodlary ýok. Haýyş edýäris, soňrak synanyşyň.")
        return

    unsubscribed_channels = await get_unsubscribed_channels(user_id)
    addlists = await get_addlists_from_db()

    if not unsubscribed_channels and not addlists:
        vpn_config_text = random.choice(vpn_configs)['config_text']
        text = "🎉 Siz ähli kanallara agza bolduňyz!"
        await message.answer(
            f"{text}\n\n🔑 <b>VPN Kodyňyz:</b>\n<pre><code>{vpn_config_text}</code></pre>"
        )
    else:
        welcome_text = await get_setting_from_db('welcome_message', "👋 <b>Hoş geldiňiz!</b>")
        
        tasks_text_list = []
        keyboard_buttons = []
        
        for channel in unsubscribed_channels:
            tasks_text_list.append(f"▫️ <a href=\"https://t.me/{str(channel['id']).lstrip('@')}\">{channel['name']}</a>")
            keyboard_buttons.append([InlineKeyboardButton(text=f"{channel['name']}", url=f"https://t.me/{str(channel['id']).lstrip('@')}")])

        for addlist in addlists:
            tasks_text_list.append(f"▫️ <a href=\"{addlist['url']}\">{addlist['name']}</a>")
            keyboard_buttons.append([InlineKeyboardButton(text=f"{addlist['name']}", url=addlist['url'])])
        
        if tasks_text_list:
            full_message = welcome_text + "\n\nVPN koduny almak üçin şu ýerlere agza boluň:\n\n" + "\n".join(tasks_text_list)
            keyboard_buttons.append([InlineKeyboardButton(text="✅ Agza Boldum", callback_data="check_subscription")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            await message.answer(full_message, reply_markup=keyboard, disable_web_page_preview=True)
            await state.set_state(SubscriptionStates.checking_subscription)
        else:
            vpn_config_text = random.choice(vpn_configs)['config_text']
            await message.answer(f"✨ Agza bolanyňyz üçin sagboluň!\n\n🔑 <b>Siziň VPN Kodyňyz:</b>\n<pre><code>{vpn_config_text}</code></pre>")

# HATA DÜZELTMESİ: .caption_html -> .caption
@router.message(Command("help"))
async def help_command(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    user_info = f"👤 <b>{user.full_name}</b>"
    if user.username:
        user_info += f" (@{user.username})"
    user_info += f"\n🆔 ID: <code>{user.id}</code>"

    if user.id in ACTIVE_CHATS:
        await message.answer("Siz eýýäm bir admin bilen söhbetdeşlik edýärsiňiz. Söhbeti gutarmak üçin /end ýazyň.")
        return

    all_admins = await get_admins_from_db()
    if SUPER_ADMIN_ID not in all_admins:
        all_admins.append(SUPER_ADMIN_ID)

    if not all_admins:
        await message.answer("😔 Gynansagam, häzirki wagtda size kömek edip biljek admin tapylmady.")
        return

    await message.answer(
        "✅ Ýardam islegiňiz adminlere iberildi.\n"
        "Bir admin jogap berende, bu ýerde göni onuň bilen gürleşip bilersiňiz.\n"
        "Söhbeti gutarmak üçin /end ýazyň."
    )
    
    request_messages = []
    for admin_id in all_admins:
        try:
            sent_msg = await bot.send_message(
                admin_id,
                f"🆘 <b>Täze Ýardam Islegi</b>\n\n{user_info}\n\n"
                "Bu ulanyjy bilen söhbetdeşlige başlamak üçin aşakdaky düwmä basyň.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↪️ Söhbetdeşlige başla", callback_data=f"start_chat:{user.id}")]
                ])
            )
            request_messages.append((admin_id, sent_msg.message_id))
        except (TelegramForbiddenError, TelegramBadRequest):
            logging.warning(f"Could not send help request to admin {admin_id}. Bot might be blocked.")
        except Exception as e:
            logging.error(f"Failed to forward help message to admin {admin_id}: {e}")
    
    if request_messages:
        HELP_REQUESTS[user.id] = request_messages


@router.callback_query(lambda c: c.data.startswith("start_chat:"))
async def start_chat_with_user(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        return await callback.answer("⛔ Giriş gadagan.", show_alert=True)
    
    try:
        user_id_to_chat = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        return await callback.answer("⚠️ Nädogry ulanyjy ID.", show_alert=True)
    
    admin_id = callback.from_user.id

    if user_id_to_chat in ACTIVE_CHATS:
        active_admin_id = ACTIVE_CHATS[user_id_to_chat]
        if active_admin_id == admin_id:
            await callback.answer("✅ Siz eýýäm bu ulanyjy bilen söhbetdeşlikde.", show_alert=True)
        else:
            try:
                admin_info = await bot.get_chat(active_admin_id)
                admin_name = admin_info.full_name
            except Exception:
                admin_name = f"ID {active_admin_id}"
            await callback.answer(f"⚠️ Bu ulanyja eýýäm ({admin_name}) kömek edýär.", show_alert=True)
        return
    
    ACTIVE_CHATS[user_id_to_chat] = admin_id

    await state.set_state(ChatStates.in_chat)
    await state.update_data(chat_partner_id=user_id_to_chat)

    user_state = dp.fsm.resolve_context(bot=bot, chat_id=user_id_to_chat, user_id=user_id_to_chat)
    await user_state.set_state(ChatStates.in_chat)
    await user_state.update_data(chat_partner_id=admin_id)

    if user_id_to_chat in HELP_REQUESTS:
        try:
            admin_who_accepted_info = await bot.get_chat(admin_id)
            admin_name = admin_who_accepted_info.full_name
        except Exception:
            admin_name = f"Admin ID {admin_id}"

        for other_admin_id, msg_id in HELP_REQUESTS[user_id_to_chat]:
            try:
                if other_admin_id == admin_id:
                    await bot.edit_message_text(f"✅ <code>{user_id_to_chat}</code> ID-li ulanyjy bilen söhbetdeşlik başlady.\n"
                                             f"Habarlaryňyz oňa gönüden-göni iberiler.\n"
                                             f"Söhbeti gutarmak üçin /end ýazyň.", chat_id=admin_id, message_id=msg_id)
                else:
                    await bot.edit_message_text(f"✅ Bu ýardam islegi <b>{admin_name}</b> tarapyndan kabul edildi.",
                                                chat_id=other_admin_id, message_id=msg_id, reply_markup=None)
            except (TelegramBadRequest, TelegramForbiddenError):
                continue
        del HELP_REQUESTS[user_id_to_chat]

    await bot.send_message(user_id_to_chat, "✅ Bir admin size jogap berdi!\n"
                                            "Indi habarlaryňyzy bu ýere ýazyp bilersiňiz.\n"
                                            "Söhbeti gutarmak üçin /end ýazyň.")
    await callback.answer()


@router.message(Command("end"))
async def end_chat_command(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != ChatStates.in_chat:
        return

    data = await state.get_data()
    partner_id = data.get('chat_partner_id')
    user_id = message.from_user.id

    is_admin_ending = await is_user_admin_in_db(user_id)
    user_in_chat_id = partner_id if is_admin_ending else user_id
    if user_in_chat_id in ACTIVE_CHATS:
        del ACTIVE_CHATS[user_in_chat_id]

    await state.clear()
    await message.answer("💬 Söhbet gutardy.")

    if partner_id:
        partner_state = dp.fsm.resolve_context(bot=bot, chat_id=partner_id, user_id=partner_id)
        if await partner_state.get_state() == ChatStates.in_chat:
            await partner_state.clear()
            try:
                await bot.send_message(partner_id, f"💬 Söhbetdeşligiňiz tamamlandy.")
            except (TelegramForbiddenError, TelegramBadRequest):
                pass


# HATA DÜZELTMESİ: .caption_html -> .caption
@router.message(ChatStates.in_chat)
async def forward_chat_message(message: Message, state: FSMContext):
    data = await state.get_data()
    partner_id = data.get('chat_partner_id')

    if not partner_id:
        await message.answer("⚠️ Ýalňyşlyk: Söhbet partneri tapylmady. Söhbeti gutarmak üçin /end ýazyň.")
        return

    sender = message.from_user
    sender_name = sender.full_name
    is_admin = await is_user_admin_in_db(sender.id)
    prefix = f"<b>{sender_name} (Admin):</b>" if is_admin else f"<b>{sender_name}:</b>"

    try:
        if message.text:
            await bot.send_message(partner_id, f"{prefix}\n{message.html_text}")
        elif message.photo:
            caption = f"{prefix}\n{message.caption or ''}" # DÜZELTME
            await bot.send_photo(partner_id, message.photo[-1].file_id, caption=caption)
        elif message.video:
            caption = f"{prefix}\n{message.caption or ''}" # DÜZELTME
            await bot.send_video(partner_id, message.video.file_id, caption=caption)
        elif message.animation:
            caption = f"{prefix}\n{message.caption or ''}" # DÜZELTME
            await bot.send_animation(partner_id, message.animation.file_id, caption=caption)
        elif message.audio:
            caption = f"{prefix}\n{message.caption or ''}" # DÜZELTME
            await bot.send_audio(partner_id, message.audio.file_id, caption=caption)
        elif message.voice:
            caption = f"{prefix}\n{message.caption or ''}" # DÜZELTME
            await bot.send_voice(partner_id, message.voice.file_id, caption=caption)
        elif message.document:
            caption = f"{prefix}\n{message.caption or ''}" # DÜZELTME
            await bot.send_document(partner_id, message.document.file_id, caption=caption)
        else:
            await message.copy_to(partner_id)

    except (TelegramForbiddenError, TelegramBadRequest):
        await message.answer("⚠️ Habar iberilmedi. Ulanyjy boty bloklan bolmagy ähtimal. Söhbet gutardy.")
        partner_state = dp.fsm.resolve_context(bot=bot, chat_id=partner_id, user_id=partner_id)
        await partner_state.clear()
        await state.clear()
        if partner_id in ACTIVE_CHATS:
            del ACTIVE_CHATS[partner_id]
    except Exception as e:
        await message.answer(f"⚠️ Habar iberlende näsazlyk ýüze çykdy: {e}")


@router.message(Command("admin"))
async def admin_command(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id):
        await message.answer("⛔ Bu buýruga girmäge rugsadyňyz ýok.")
        return
    await message.answer("⚙️ <b>Admin-panel</b>\n\nBir hereket saýlaň:", reply_markup=create_admin_keyboard(message.from_user.id))
    await state.clear()

@router.callback_query(lambda c: c.data == "exit_admin_panel")
async def exit_admin_panel_handler(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    await state.clear()
    try:
        await callback.message.edit_text("✅ Siz admin panelden çykdyňyz.\n\nAdaty ulanyjy hökmünde täzeden işe başlamak üçin /start giriziň.")
    except TelegramBadRequest:
        await callback.message.delete()
        await callback.message.answer("✅ Siz admin panelden çykdyňyz.")
    await callback.answer()

@router.callback_query(lambda c: c.data == "get_stats")
async def get_statistics(callback: types.CallbackQuery):
    if not await is_user_admin_in_db(callback.from_user.id):
        return await callback.answer("⛔ Giriş gadagan.", show_alert=True)
    async with DB_POOL.acquire() as conn:
        user_count = await conn.fetchval("SELECT COUNT(*) FROM bot_users")
        channel_count = await conn.fetchval("SELECT COUNT(*) FROM channels")
        addlist_count = await conn.fetchval("SELECT COUNT(*) FROM addlists")
        vpn_count = await conn.fetchval("SELECT COUNT(*) FROM vpn_configs")
        admin_count = await conn.fetchval("SELECT COUNT(*) FROM bot_admins")

    status_description = "Bot işleýär" if vpn_count > 0 else "VPN KODLARY ÝOK!"
    alert_text = (f"📊 Bot statistikasy:\n"
                  f"👤 Ulanyjylar: {user_count}\n"
                  f"📢 Kanallar: {channel_count}\n"
                  f"📁 addlistlar: {addlist_count}\n"
                  f"🔑 VPN Kodlary: {vpn_count}\n"
                  f"👮 Adminler (goşulan): {admin_count}\n"
                  f"⚙️ Ýagdaýy: {status_description}")
    await callback.answer(text=alert_text, show_alert=True)

def parse_buttons_from_text(text: str) -> types.InlineKeyboardMarkup | None:
    lines, keyboard_buttons = text.strip().split('\n'), []
    for line in lines:
        if ' - ' not in line: continue
        parts = line.split(' - ', 1)
        btn_text, btn_url = parts[0].strip(), parts[1].strip()
        if btn_text and (btn_url.startswith('https://') or btn_url.startswith('http://')):
            keyboard_buttons.append([types.InlineKeyboardButton(text=btn_text, url=btn_url)])
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons) if keyboard_buttons else None

async def execute_user_broadcast(admin_message: types.Message, mailing_content: dict, mailing_keyboard: types.InlineKeyboardMarkup | None):
    users_to_mail = await get_users_from_db()
    if not users_to_mail:
        return await admin_message.edit_text("👥 Ibermek üçin ulanyjylar ýok.", reply_markup=back_to_admin_markup)
    
    await admin_message.edit_text(f"⏳ <b>{len(users_to_mail)}</b> sany ulanyja ibermek başlanýar...", reply_markup=None)
    success_count, fail_count = 0, 0
    for user_id in users_to_mail:
        try:
            await send_mail_preview(user_id, mailing_content, mailing_keyboard)
            success_count += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            fail_count += 1
        except Exception as e:
            fail_count += 1
            logging.error(f"Ulanyja {user_id} iberlende näbelli ýalňyşlyk: {e}")
        await asyncio.sleep(0.1)

    await save_last_mail_content(mailing_content, mailing_keyboard, "user")
    final_report_text = f"✅ <b>Ulanyjylara Iberiş Tamamlandy</b> ✅\n\n👍 Üstünlikli: {success_count}\n👎 Başartmady: {fail_count}"
    await admin_message.edit_text(final_report_text, reply_markup=back_to_admin_markup)

@router.message(AdminStates.waiting_for_mailing_message, F.content_type.in_({'text', 'photo'}))
async def process_user_mailing_message(message: Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    await process_mailing_content(message, state, "user")

@router.callback_query(lambda c: c.data == "start_mailing")
async def start_mailing_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id): return
    last_content, _ = await get_last_mail_content("user")
    keyboard_buttons = [[InlineKeyboardButton(text="➕ Täze habar döretmek", callback_data="create_new_user_mail")]]
    if last_content:
        keyboard_buttons.insert(0, [InlineKeyboardButton(text="🔄 Soňky habary ulanmak", callback_data="repeat_last_user_mail")])
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Yza", callback_data="admin_panel_main")])
    await callback.message.edit_text("📬 <b>Ulanyjylara Iberiş</b> 📬\n\nBir hereket saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))
    await state.set_state(AdminStates.waiting_for_user_mail_action)
    await callback.answer()

@router.callback_query(AdminStates.waiting_for_user_mail_action)
async def process_user_mail_action(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data
    if action == "create_new_user_mail":
        msg_text = "✍️ Ibermek isleýän habaryňyzy iberiň (diňe tekst ýa-da surat goldanýar)."
        msg = await callback.message.edit_text(msg_text, reply_markup=back_to_admin_markup)
        await state.update_data(admin_message_id=msg.message_id)
        await state.set_state(AdminStates.waiting_for_mailing_message)
    elif action == "repeat_last_user_mail":
        content, keyboard = await get_last_mail_content("user")
        if not content:
            return await callback.answer("⚠️ Soňky habar tapylmady.", show_alert=True)
        await state.update_data(mailing_content=content, mailing_keyboard=keyboard)
        await callback.message.delete()
        preview_text = "🗂️ <b>Soňky habary tassyklaň:</b>\n\nŞu habary ulanyjylara iberýärismi?"
        preview_msg = await send_mail_preview(callback.from_user.id, content, keyboard)
        confirmation_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Hawa, ibermek", callback_data="user_mail_confirm_send_repeated")],
            [InlineKeyboardButton(text="⬅️ Ýok, yza", callback_data="admin_panel_main")]
        ])
        confirm_msg = await bot.send_message(callback.from_user.id, preview_text, reply_markup=confirmation_keyboard)
        await state.update_data(admin_message_id=confirm_msg.message_id, preview_message_id=preview_msg.message_id)
        await state.set_state(AdminStates.waiting_for_mailing_confirmation)
    await callback.answer()

@router.callback_query(AdminStates.waiting_for_mailing_confirmation)
async def process_user_mailing_confirmation(callback: types.CallbackQuery, state: FSMContext):
    fsm_data = await state.get_data()
    mailing_content = fsm_data.get('mailing_content')
    mailing_keyboard = fsm_data.get('mailing_keyboard')
    
    try:
        if fsm_data.get('admin_message_id'): await bot.delete_message(callback.from_user.id, fsm_data.get('admin_message_id'))
        if fsm_data.get('preview_message_id'): await bot.delete_message(callback.from_user.id, fsm_data.get('preview_message_id'))
    except (TelegramBadRequest, KeyError): pass

    if not mailing_content:
        await bot.send_message(callback.from_user.id, "⚠️ Ýalňyşlyk: habar tapylmady.", reply_markup=back_to_admin_markup)
        return await state.clear()

    if callback.data in ["user_mail_confirm_send", "user_mail_confirm_send_repeated"]:
        msg_for_broadcast = await bot.send_message(callback.from_user.id, "⏳...")
        await execute_user_broadcast(msg_for_broadcast, mailing_content, mailing_keyboard)
        await state.clear()
    elif callback.data == "user_mail_confirm_add_buttons":
        msg = await bot.send_message(callback.from_user.id, "🔗 <b>Düwmeleri goşmak</b> 🔗\n\nFormat: <code>Tekst - https://deezer.com</code>\nHer düwme täze setirde.", reply_markup=back_to_admin_markup)
        await state.update_data(admin_message_id=msg.message_id)
        await state.set_state(AdminStates.waiting_for_mailing_buttons)
    await callback.answer()

@router.message(AdminStates.waiting_for_mailing_buttons)
async def process_user_mailing_buttons(message: Message, state: FSMContext):
    keyboard = parse_buttons_from_text(message.text)
    if not keyboard:
        return await message.answer("⚠️ Nädogry format! Täzeden synanyşyň.")
    await message.delete()
    fsm_data = await state.get_data()
    mailing_content = fsm_data.get('mailing_content')
    try:
        if fsm_data.get('admin_message_id'): await bot.delete_message(message.chat.id, fsm_data.get('admin_message_id'))
    except (TelegramBadRequest, KeyError): pass
    msg_for_broadcast = await bot.send_message(message.chat.id, "⏳...")
    await execute_user_broadcast(msg_for_broadcast, mailing_content, keyboard)
    await state.clear()

async def execute_channel_broadcast(admin_message: types.Message, mailing_content: dict, mailing_keyboard: types.InlineKeyboardMarkup | None):
    channels_to_mail = await get_channels_from_db()
    if not channels_to_mail:
        return await admin_message.edit_text("📢 Ibermek üçin kanallar ýok.", reply_markup=back_to_admin_markup)

    await admin_message.edit_text(f"⏳ <b>{len(channels_to_mail)}</b> sany kanala ibermek başlanýar...", reply_markup=None)
    success_count, fail_count = 0, 0
    for channel in channels_to_mail:
        try:
            await send_mail_preview(channel['id'], mailing_content, mailing_keyboard)
            success_count += 1
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            fail_count += 1
            logging.warning(f"Kanala {channel['name']} ({channel['id']}) habar ibermek başartmady: {e}")
        except Exception as e:
            fail_count += 1
            logging.error(f"Kanala {channel['name']} ({channel['id']}) iberlende näbelli ýalňyşlyk: {e}")
        await asyncio.sleep(0.2)
    
    await save_last_mail_content(mailing_content, mailing_keyboard, "channel")
    final_report_text = f"✅ <b>Kanallara Iberiş Tamamlandy</b> ✅\n\n👍 Üstünlikli: {success_count}\n👎 Başartmady: {fail_count}"
    await admin_message.edit_text(final_report_text, reply_markup=back_to_admin_markup)

@router.callback_query(lambda c: c.data == "start_channel_mailing")
async def start_channel_mailing_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id): return
    last_content, _ = await get_last_mail_content("channel")
    keyboard_buttons = [[InlineKeyboardButton(text="➕ Täze habar döretmek", callback_data="create_new_channel_mail")]]
    if last_content:
        keyboard_buttons.insert(0, [InlineKeyboardButton(text="🔄 Soňky habary ulanmak", callback_data="repeat_last_channel_mail")])
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Yza", callback_data="admin_panel_main")])
    await callback.message.edit_text("📢 <b>Kanallara Iberiş</b> 📢\n\nBir hereket saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))
    await state.set_state(AdminStates.waiting_for_channel_mail_action)
    await callback.answer()

@router.callback_query(AdminStates.waiting_for_channel_mail_action)
async def process_channel_mail_action(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data
    if action == "create_new_channel_mail":
        msg_text = "✍️ Ibermek isleýän habaryňyzy iberiň (diňe tekst ýa-da surat goldanýar)."
        msg = await callback.message.edit_text(msg_text, reply_markup=back_to_admin_markup)
        await state.update_data(admin_message_id=msg.message_id)
        await state.set_state(AdminStates.waiting_for_channel_mailing_message)
    elif action == "repeat_last_channel_mail":
        content, keyboard = await get_last_mail_content("channel")
        if not content:
            return await callback.answer("⚠️ Soňky habar tapylmady.", show_alert=True)
        await state.update_data(mailing_content=content, mailing_keyboard=keyboard)
        await callback.message.delete()
        preview_text = "🗂️ <b>Soňky habary tassyklaň:</b>\n\nŞu habary kanallara iberýärismi?"
        preview_msg = await send_mail_preview(callback.from_user.id, content, keyboard)
        confirmation_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Hawa, ibermek", callback_data="channel_mail_confirm_send_repeated")],
            [InlineKeyboardButton(text="⬅️ Ýok, yza", callback_data="admin_panel_main")]
        ])
        confirm_msg = await bot.send_message(callback.from_user.id, preview_text, reply_markup=confirmation_keyboard)
        await state.update_data(admin_message_id=confirm_msg.message_id, preview_message_id=preview_msg.message_id)
        await state.set_state(AdminStates.waiting_for_channel_mailing_confirmation)
    await callback.answer()

@router.message(AdminStates.waiting_for_channel_mailing_message, F.content_type.in_({'text', 'photo'}))
async def process_channel_mailing_message(message: Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    await process_mailing_content(message, state, "channel")

@router.callback_query(AdminStates.waiting_for_channel_mailing_confirmation)
async def process_channel_mailing_confirmation(callback: types.CallbackQuery, state: FSMContext):
    fsm_data = await state.get_data()
    mailing_content = fsm_data.get('mailing_content')
    mailing_keyboard = fsm_data.get('mailing_keyboard')
    
    try:
        if fsm_data.get('admin_message_id'): await bot.delete_message(callback.from_user.id, fsm_data.get('admin_message_id'))
        if fsm_data.get('preview_message_id'): await bot.delete_message(callback.from_user.id, fsm_data.get('preview_message_id'))
    except (TelegramBadRequest, KeyError): pass

    if not mailing_content:
        await bot.send_message(callback.from_user.id, "⚠️ Ýalňyşlyk: habar tapylmady.", reply_markup=back_to_admin_markup)
        return await state.clear()

    if callback.data in ["channel_mail_confirm_send", "channel_mail_confirm_send_repeated"]:
        msg_for_broadcast = await bot.send_message(callback.from_user.id, "⏳...")
        await execute_channel_broadcast(msg_for_broadcast, mailing_content, mailing_keyboard)
        await state.clear()
    elif callback.data == "channel_mail_confirm_add_buttons":
        msg = await bot.send_message(callback.from_user.id, "🔗 <b>Düwmeleri goşmak</b> 🔗\n\nFormat: <code>Tekst - https://salgy.com</code>\nHer düwme täze setirde.", reply_markup=back_to_admin_markup)
        await state.update_data(admin_message_id=msg.message_id)
        await state.set_state(AdminStates.waiting_for_channel_mailing_buttons)
    await callback.answer()

@router.message(AdminStates.waiting_for_channel_mailing_buttons)
async def process_channel_mailing_buttons(message: Message, state: FSMContext):
    keyboard = parse_buttons_from_text(message.text)
    if not keyboard:
        return await message.answer("⚠️ Nädogry format! Täzeden synanyşyň.")
    await message.delete()
    fsm_data = await state.get_data()
    mailing_content = fsm_data.get('mailing_content')
    try:
        if fsm_data.get('admin_message_id'): await bot.delete_message(message.chat.id, fsm_data.get('admin_message_id'))
    except (TelegramBadRequest, KeyError): pass
    msg_for_broadcast = await bot.send_message(message.chat.id, "⏳...")
    await execute_channel_broadcast(msg_for_broadcast, mailing_content, keyboard)
    await state.clear()

@router.callback_query(lambda c: c.data == "add_channel")
async def process_add_channel_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        return await callback.answer("⛔ Giriş gadagan.", show_alert=True)
    msg = await callback.message.edit_text(
        "📡 <b>Kanal Goşmak</b> 📡\n\n"
        "Goşmak isleýän kanallaryňyzyň ID'lerini ýa-da ulanyjy adlaryny (<code>@username</code>) <b>virgül (,)</b> bilen aýryp ýazyň.\n\n"
        "<b>Meselem:</b> <code>@kanal1, @kanal2, -100123456789</code>\n\n"
        "<i>Bot ähli kanallarda administrator bolmaly we adyny awtomatiki alar.</i>",
        reply_markup=back_to_admin_markup
    )
    await state.update_data(admin_message_id=msg.message_id, admin_chat_id=msg.chat.id)
    await state.set_state(AdminStates.waiting_for_channel_id)
    await callback.answer()

@router.message(AdminStates.waiting_for_channel_id)
async def process_channel_id_and_save(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    
    channel_inputs = [ch.strip() for ch in message.text.replace(' ', ',').split(',') if ch.strip()]
    await message.delete()

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    
    if not admin_message_id or not channel_inputs:
        await bot.send_message(message.chat.id, "⚠️ Ýalňyşlyk ýa-da boş giriş. Admin panelden täzeden synanyşyň.", reply_markup=create_admin_keyboard(message.from_user.id))
        return await state.clear()

    await bot.edit_message_text("⏳ Kanallar barlanýar we goşulýar...", chat_id=admin_chat_id, message_id=admin_message_id)
    
    success_list = []
    fail_list = []

    for channel_id_input in channel_inputs:
        try:
            chat_obj = await bot.get_chat(channel_id_input)
            channel_name = chat_obj.title
            
            bot_member = await bot.get_chat_member(chat_id=chat_obj.id, user_id=bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                fail_list.append(f"{channel_id_input} (Bot admin däl)")
                continue

            id_to_store = channel_id_input if channel_id_input.startswith('@') else str(chat_obj.id)
            
            success = await add_channel_to_db(id_to_store, channel_name)
            if success:
                success_list.append(f"{channel_name} (<code>{id_to_store}</code>)")
            else:
                fail_list.append(f"{channel_name} (Eýýäm bar)")
        
        except Exception as e:
            logging.error(f"Error getting channel info for {channel_id_input}: {e}")
            fail_list.append(f"{channel_id_input} (Tapylmady/Ýalňyşlyk)")
        
        await asyncio.sleep(0.3) 

    report_text = "✅ <b>Netije:</b>\n\n"
    if success_list:
        report_text += "<b>Goşulanlar:</b>\n" + "\n".join(f"▫️ {s}" for s in success_list) + "\n\n"
    if fail_list:
        report_text += "<b>Goşulmadyklar:</b>\n" + "\n".join(f"▪️ {f}" for f in fail_list)

    await bot.edit_message_text(report_text, chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()


@router.callback_query(lambda c: c.data == "delete_channel")
async def process_delete_channel_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id): return
    channels = await get_channels_from_db()
    if not channels:
        return await callback.message.edit_text("🗑️ Kanallaryň sanawy boş.", reply_markup=back_to_admin_markup)
    keyboard_buttons = [[InlineKeyboardButton(text=f"{ch['name']} ({ch['id']})", callback_data=f"del_channel:{ch['id']}")] for ch in channels]
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")])
    await callback.message.edit_text("🔪 <b>Kanal Pozmak</b> 🔪\n\nPozmak üçin kanaly saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))
    await callback.answer()

@router.callback_query(lambda c: c.data == "list_channels")
async def list_channels_handler(callback: types.CallbackQuery):
    if not await is_user_admin_in_db(callback.from_user.id):
        return await callback.answer("⛔ Giriş gadagan.", show_alert=True)
    
    channels = await get_channels_from_db()
    if not channels:
        message_text = "ℹ️ Botuň yzarlaýan kanaly ýok."
    else:
        details = [f"▫️ {ch['name']} (ID: <code>{ch['id']}</code>)" for ch in channels]
        message_text = "📢 <b>Botdaky Kanallaryň Sanawy</b> 📢\n\n" + "\n".join(details)
        
    await callback.message.edit_text(message_text, reply_markup=back_to_admin_markup)
    await callback.answer()

@router.callback_query(lambda c: c.data == "admin_panel_main")
async def back_to_admin_panel(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        return await callback.answer("⛔ Giriş gadagan.", show_alert=True)
    admin_reply_markup = create_admin_keyboard(callback.from_user.id)
    try:
        await callback.message.edit_text("⚙️ <b>Admin-panel</b>\n\nBir hereket saýlaň:", reply_markup=admin_reply_markup)
    except TelegramBadRequest:
        await callback.message.delete()
        await callback.message.answer("⚙️ <b>Admin-panel</b>\n\nBir hereket saýlaň:", reply_markup=admin_reply_markup)
    await state.clear()
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("del_channel:"))
async def confirm_delete_channel(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id): return
    channel_id_to_delete = callback.data.split(":", 1)[1]
    if await delete_channel_from_db(channel_id_to_delete):
        await callback.message.edit_text(f"🗑️ Kanal (<code>{channel_id_to_delete}</code>) üstünlikli pozuldy.", reply_markup=back_to_admin_markup)
        await callback.answer("Kanal pozuldy", show_alert=False)
    else:
        await callback.message.edit_text("⚠️ Kanal tapylmady ýa-da pozmakda ýalňyşlyk ýüze çykdy.", reply_markup=back_to_admin_markup)
        await callback.answer("Kanal tapylmady ýa-da ýalňyşlyk", show_alert=True)

@router.callback_query(lambda c: c.data == "add_addlist")
async def process_add_addlist_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id): return
    msg = await callback.message.edit_text("🔗 <b>addlist Goşmak</b> 🔗\n\nURL-ni giriziň (<code>https://t.me/addlist/xxxx</code>):", reply_markup=back_to_admin_markup)
    await state.update_data(admin_message_id=msg.message_id, admin_chat_id=msg.chat.id)
    await state.set_state(AdminStates.waiting_for_addlist_url)
    await callback.answer()

@router.message(AdminStates.waiting_for_addlist_url)
async def process_addlist_url(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    addlist_url = message.text.strip()
    await message.delete()

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')

    if not addlist_url.startswith("https://t.me/addlist/"):
        return await bot.edit_message_text(f"⚠️ <b>Ýalňyşlyk:</b> URL <code>https://t.me/addlist/</code> bilen başlamaly.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    
    addlists_in_db = await get_addlists_from_db()
    if any(al['url'] == addlist_url for al in addlists_in_db):
        return await bot.edit_message_text(f"⚠️ Bu addlist (<code>{addlist_url}</code>) eýýäm goşulan.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    
    await state.update_data(addlist_url=addlist_url)
    await bot.edit_message_text("✏️ Indi bu addlist üçin <b>görkezilýän ady</b> giriziň:", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.set_state(AdminStates.waiting_for_addlist_name)

@router.message(AdminStates.waiting_for_addlist_name)
async def save_addlist_name(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    addlist_name = message.text.strip()
    await message.delete()

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    addlist_url = fsm_data.get('addlist_url')

    if not addlist_name:
        return await bot.edit_message_text(f"⚠️ addlist ady boş bolup bilmez.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)

    if await add_addlist_to_db(addlist_name, addlist_url):
        await bot.edit_message_text(f"✅ <b>{addlist_name}</b> addlistsy üstünlikli goşuldy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    else:
        await bot.edit_message_text(f"⚠️ <b>{addlist_name}</b> addlistsy goşmak başartmady.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()

@router.callback_query(lambda c: c.data == "delete_addlist")
async def process_delete_addlist_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id): return
    addlists = await get_addlists_from_db()
    if not addlists:
        return await callback.message.edit_text("🗑️ addlistlaryň sanawy boş.", reply_markup=back_to_admin_markup)
    
    keyboard = [[InlineKeyboardButton(text=f"{al['name']}", callback_data=f"del_addlist_id:{al['db_id']}")] for al in addlists]
    keyboard.append([InlineKeyboardButton(text="⬅️ Yza", callback_data="admin_panel_main")])
    await callback.message.edit_text("🔪 <b>addlist Pozmak</b> 🔪\n\nPozmak üçin saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("del_addlist_id:"))
async def confirm_delete_addlist(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id): return
    try:
        addlist_db_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        return await callback.message.edit_text("⚠️ Ýalňyşlyk: Nädogry ID.", reply_markup=back_to_admin_markup)
    
    if await delete_addlist_from_db(addlist_db_id):
        await callback.message.edit_text(f"🗑️ addlist üstünlikli pozuldy.", reply_markup=back_to_admin_markup)
        await callback.answer("addlist pozuldy", show_alert=False)
    else:
        await callback.message.edit_text("⚠️ addlist pozmakda ýalňyşlyk.", reply_markup=back_to_admin_markup)
        await callback.answer("Pozmak ýalňyşlygy", show_alert=True)

@router.callback_query(lambda c: c.data == "add_vpn_config")
async def process_add_vpn_config_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id): return
    msg = await callback.message.edit_text("🔑 <b>VPN Kody Goşmak</b> 🔑\n\nVPN <b>kodyny</b> iberiň.", reply_markup=back_to_admin_markup)
    await state.update_data(admin_message_id=msg.message_id, admin_chat_id=msg.chat.id)
    await state.set_state(AdminStates.waiting_for_vpn_config)
    await callback.answer()

@router.message(AdminStates.waiting_for_vpn_config)
async def save_vpn_config(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    vpn_config_text = message.text.strip()
    await message.delete()

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')

    if not vpn_config_text:
        return await bot.edit_message_text("⚠️ VPN kody boş bolup bilmez.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)

    if await add_vpn_config_to_db(vpn_config_text):
        await bot.edit_message_text("✅ VPN kody üstünlikli goşuldy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    else:
        await bot.edit_message_text("⚠️ VPN kodyny goşmak başartmady. Mümkin ol eýýäm bar.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()

@router.callback_query(lambda c: c.data == "delete_vpn_config")
async def process_delete_vpn_config_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id): return
    vpn_configs = await get_vpn_configs_from_db()
    if not vpn_configs:
        return await callback.message.edit_text("🗑️ VPN kody sanawy boş.", reply_markup=back_to_admin_markup)
    
    keyboard = [[InlineKeyboardButton(text=f"Kod #{i+1} (<code>{item['config_text'][:20]}...</code>)", callback_data=f"del_vpn_id:{item['db_id']}")] for i, item in enumerate(vpn_configs)]
    keyboard.append([InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")])
    await callback.message.edit_text("🔪 <b>VPN Kodyny Pozmak</b> 🔪\n\nPozmak üçin kody saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("del_vpn_id:"))
async def confirm_delete_vpn_config(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id): return
    try:
        config_db_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        return await callback.message.edit_text("⚠️ Ýalňyşlyk: Nädogry kod ID-si.", reply_markup=back_to_admin_markup)
    
    if await delete_vpn_config_from_db(config_db_id):
        await callback.message.edit_text("🗑️ VPN kody üstünlikli pozuldy.", reply_markup=back_to_admin_markup)
        await callback.answer("VPN Kody pozuldy", show_alert=False)
    else:
        await callback.message.edit_text("⚠️ Kod tapylmady ýa-da pozmakda ýalňyşlyk boldy.", reply_markup=back_to_admin_markup)
        await callback.answer("Kod tapylmady/ýalňyşlyk", show_alert=True)

@router.callback_query(lambda c: c.data == "change_welcome")
async def process_change_welcome_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id): return
    current_welcome = await get_setting_from_db("welcome_message", "<i>Häzirki Başlangyç haty ýok.</i>")
    msg = await callback.message.edit_text(
        f"📝 <b>Başlangyç hatyny Üýtgetmek</b> 📝\n\n"
        f"Häzirki hat:\n<blockquote>{current_welcome}</blockquote>\n"
        f"Täze başlangyç hatyny giriziň (HTML goldanýar).",
        reply_markup=back_to_admin_markup
    )
    await state.update_data(admin_message_id=msg.message_id, admin_chat_id=msg.chat.id)
    await state.set_state(AdminStates.waiting_for_welcome_message)
    await callback.answer()

@router.message(AdminStates.waiting_for_welcome_message)
async def save_welcome_message(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    new_welcome_message = message.html_text
    await message.delete()

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')

    if not new_welcome_message or not new_welcome_message.strip():
        return await bot.edit_message_text("⚠️ Başlangyç haty boş bolup bilmez.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)

    await save_setting_to_db('welcome_message', new_welcome_message)
    await bot.edit_message_text("✅ Başlangyç hat üstünlikli täzelendi!", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()

@router.callback_query(lambda c: c.data == "add_admin")
async def add_admin_prompt(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return await callback.answer("⛔ Diňe baş admin üçin elýeterli.", show_alert=True)
    msg = await callback.message.edit_text("👮 <b>Admin Goşmak</b> 👮\n\nUlanyjynyň Telegram ID-sini giriziň.", reply_markup=back_to_admin_markup)
    await state.update_data(admin_message_id=msg.message_id, admin_chat_id=msg.chat.id)
    await state.set_state(AdminStates.waiting_for_admin_id_to_add)
    await callback.answer()

@router.message(AdminStates.waiting_for_admin_id_to_add)
async def process_add_admin_id(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID: return
    await message.delete()
    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    try:
        new_admin_id = int(message.text.strip())
    except ValueError:
        return await bot.edit_message_text("⚠️ <b>Ýalňyşlyk:</b> User ID san bolmaly.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)

    if new_admin_id == SUPER_ADMIN_ID:
        return await bot.edit_message_text("⚠️ Baş admin eýýäm ähli hukuklara eýe.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)

    if new_admin_id in await get_admins_from_db():
        return await bot.edit_message_text(f"⚠️ <code>{new_admin_id}</code> ID-li ulanyjy eýýäm admin.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)

    if await add_admin_to_db(new_admin_id):
        await bot.edit_message_text(f"✅ <code>{new_admin_id}</code> ID-li ulanyjy admin bellenildi!", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    else:
        await bot.edit_message_text(f"⚠️ <code>{new_admin_id}</code> ID-li admini goşmak başartmady.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()

@router.callback_query(lambda c: c.data == "delete_admin")
async def delete_admin_prompt(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return await callback.answer("⛔ Diňe baş admin üçin elýeterli.", show_alert=True)
    
    admins_in_db = await get_admins_from_db()
    if not admins_in_db:
        return await callback.message.edit_text("🚫 Goşmaça admin sanawy boş.", reply_markup=back_to_admin_markup)

    admin_details = []
    for admin_id in admins_in_db:
        try:
            user = await bot.get_chat(admin_id)
            admin_details.append({'id': admin_id, 'name': user.full_name, 'username': user.username})
        except Exception:
            admin_details.append({'id': admin_id, 'name': f"Unknown ({admin_id})", 'username': None})
    
    admin_details.sort(key=lambda x: x['name'])

    keyboard_buttons = []
    for admin in admin_details:
        display_name = f"{admin['name']} (@{admin['username']})" if admin['username'] else f"{admin['name']} ({admin['id']})"
        keyboard_buttons.append([InlineKeyboardButton(text=display_name, callback_data=f"del_admin_id:{admin['id']}")])
    
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Yza", callback_data="admin_panel_main")])
    await callback.message.edit_text("🔪 <b>Admin Pozmak</b> 🔪\n\nHukuklaryny aýyrmak üçin admini saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))
    await callback.answer()

@router.callback_query(lambda c: c.data == "list_admins")
async def list_admins_handler(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return await callback.answer("⛔ Diňe baş admin üçin elýeterli.", show_alert=True)
    
    other_admins = await get_admins_from_db()
    all_admin_ids = [SUPER_ADMIN_ID] + other_admins

    admin_details = []
    for admin_id in all_admin_ids:
        try:
            user = await bot.get_chat(admin_id)
            role = "👑 Baş Admin" if user.id == SUPER_ADMIN_ID else "👮 Admin"
            name = user.full_name
            username = f"@{user.username}" if user.username else "<i>(ýok)</i>"
            admin_details.append(f"▫️ {name} ({username}) - {role}")
        except Exception:
            role = "👑 Baş Admin" if admin_id == SUPER_ADMIN_ID else "👮 Admin"
            admin_details.append(f"▪️ Näbelli Ulanyjy (ID: <code>{admin_id}</code>) - {role}")
    
    if admin_details:
        message_text = "⚜️ <b>Bot Adminleriniň Sanawy</b> ⚜️\n\n" + "\n".join(admin_details)
    else:
        message_text = "🚫 Admin sanawy boş."
        
    await callback.message.edit_text(message_text, reply_markup=back_to_admin_markup)
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("del_admin_id:"))
async def confirm_delete_admin(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID: return
    try:
        admin_id_to_delete = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        return await callback.message.edit_text("⚠️ Ýalňyşlyk: Nädogry admin ID.", reply_markup=back_to_admin_markup)

    if await delete_admin_from_db(admin_id_to_delete):
        await callback.message.edit_text(f"🗑️ <code>{admin_id_to_delete}</code> ID-li admin üstünlikli pozuldy.", reply_markup=back_to_admin_markup)
        await callback.answer("Admin pozuldy", show_alert=False)
    else:
        await callback.message.edit_text("⚠️ Admin tapylmady ýa-da pozmakda ýalňyşlyk boldy.", reply_markup=back_to_admin_markup)
        await callback.answer("Admin tapylmady/ýalňyşlyk", show_alert=True)

@router.callback_query(lambda c: c.data == "check_subscription")
async def process_check_subscription(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    vpn_configs = await get_vpn_configs_from_db()

    if not vpn_configs:
        await callback.answer("😔 Gynansak-da, häzirki wagtda elýeterli VPN kody ýok.", show_alert=True)
        return await state.clear()

    unsubscribed_channels = await get_unsubscribed_channels(user_id)
    
    if not unsubscribed_channels:
        vpn_config_text = random.choice(vpn_configs)['config_text']
        text = "🎉 Siz ähli kanallara agza bolduňyz!"
        try:
            await callback.message.edit_text(
                f"{text}\n\n🔑 <b>Siziň VPN koduňyz:</b>\n<pre><code>{vpn_config_text}</code></pre>",
                reply_markup=None
            )
        except TelegramBadRequest: pass 
        await callback.answer(text="✅ Agzalyk tassyklandy!", show_alert=False)
        await state.clear()
    else:
        addlists = await get_addlists_from_db()
        welcome_text = await get_setting_from_db('welcome_message', "👋 <b>Hoş geldiňiz!</b>")
        
        tasks_text_list = []
        keyboard_buttons = []

        for channel in unsubscribed_channels:
            tasks_text_list.append(f"▫️ <a href=\"https://t.me/{str(channel['id']).lstrip('@')}\">{channel['name']}</a>")
            keyboard_buttons.append([InlineKeyboardButton(text=f"{channel['name']}", url=f"https://t.me/{str(channel['id']).lstrip('@')}")])

        for addlist in addlists:
            tasks_text_list.append(f"▫️ <a href=\"{addlist['url']}\">{addlist['name']}</a>")
            keyboard_buttons.append([InlineKeyboardButton(text=f"{addlist['name']}", url=addlist['url'])])
        
        full_message = welcome_text + "\n\nHenizem agza bolunmadyk ýerler bar:\n\n" + "\n".join(tasks_text_list)
        keyboard_buttons.append([InlineKeyboardButton(text="✅ Agza Boldum", callback_data="check_subscription")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

        try:
            await callback.message.edit_text(full_message, reply_markup=keyboard, disable_web_page_preview=True)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                logging.error(f"Error editing message on sub check: {e}")
        
        await callback.answer(text="⚠️ Haýyş edýäris, sanawdaky ähli ýerlere agza boluň!", show_alert=True)

async def main():
    global DB_POOL
    try:
        DB_POOL = await asyncpg.create_pool(dsn=DATABASE_URL)
        if DB_POOL:
            logging.info("Successfully connected to PostgreSQL and connection pool created.")
            await init_db(DB_POOL)
            logging.info("Database initialized.")
        else:
            logging.error("Failed to create database connection pool.")
            return
    except Exception as e:
        logging.critical(f"Failed to connect to PostgreSQL or initialize database: {e}")
        return

    await dp.start_polling(bot)

    if DB_POOL:
        await DB_POOL.close()
        logging.info("PostgreSQL connection pool closed.")

if __name__ == '__main__':
    asyncio.run(main())
