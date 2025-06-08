import asyncio
import logging
import random
import json
from urllib.parse import quote, unquote
import asyncpg
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, InputFile
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
import io
from keep_alive import keep_alive

keep_alive()

logging.basicConfig(level=logging.INFO)

# --- BOTUNUZUN BİLGİLERİNİ GİRİN ---
API_TOKEN = '7399222144:AAE0GP4T-ayz42nlOxDB6xmHLxPMkOePrgY' # BOT TOKEN'İNİZİ BURAYA YAZIN
SUPER_ADMIN_ID = 7853333670 # KENDİ TELEGRAM ID'NİZİ BURAYA YAZIN
DATABASE_URL = "postgresql://htsd_user:csKusK0S8l0l5yXnn6TJZtPaNN9qUGIQ@dpg-d0m6hap5pdvs738v8fq0-a/htsd" # VERİTABANI BAĞLANTI ADRESİNİZ
# ------------------------------------

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
storage = MemoryStorage()
dp = Dispatcher(bot=bot, storage=storage)
router = Router()
dp.include_router(router)

DB_POOL = None

back_to_admin_markup = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⬅️ Admin panele gaýtmak", callback_data="admin_panel_main")]
])

class SubscriptionStates(StatesGroup):
    checking_subscription = State()

# --- YENI ---
# /help komutu ve admin yanıt sistemi için State'ler
class HelpStates(StatesGroup):
    waiting_for_help_message = State()
    waiting_for_admin_reply = State()

class AdminStates(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_name = State()
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
    # --- YENI ---
    # Toplu işlemler için State'ler
    waiting_for_bulk_channel_list = State()
    waiting_for_bulk_delete_list = State()


async def init_db(pool):
    async with pool.acquire() as connection:
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id SERIAL PRIMARY KEY,
                channel_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL
            );
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS addlists (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL
            );
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS vpn_configs (
                id SERIAL PRIMARY KEY,
                config_text TEXT UNIQUE NOT NULL
            );
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id BIGINT PRIMARY KEY
            );
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id BIGINT PRIMARY KEY
            );
        """)
        default_welcome = "👋 <b>Hoş geldiňiz!</b>\n\nVPN Koduny almak üçin, aşakdaky Kanallara Agza boluň we soňra Agza boldum düwmesine basyň."
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
        keyboard_json = json.dumps(keyboard.dict())
        await save_setting_to_db(f'last_{mail_type}_mail_keyboard', keyboard_json)
    else:
        await save_setting_to_db(f'last_{mail_type}_mail_keyboard', 'null')

async def get_last_mail_content(mail_type: str) -> tuple[dict | None, InlineKeyboardMarkup | None]:
    content = None
    keyboard = None

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

    if content_type == 'text':
        return await bot.send_message(chat_id, text, reply_markup=keyboard)
    elif content_type == 'photo':
        return await bot.send_photo(chat_id, file_id, caption=caption, reply_markup=keyboard)
    elif content_type == 'video':
        return await bot.send_video(chat_id, file_id, caption=caption, reply_markup=keyboard)
    elif content_type == 'animation':
        return await bot.send_animation(chat_id, file_id, caption=caption, reply_markup=keyboard)


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
        try:
            await conn.execute("INSERT INTO bot_users (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", user_id)
        except Exception as e:
            logging.error(f"Error adding user {user_id} to DB: {e}")


async def get_admins_from_db():
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM bot_admins")
        return [row['user_id'] for row in rows]

async def add_admin_to_db(user_id: int):
    async with DB_POOL.acquire() as conn:
        try:
            await conn.execute("INSERT INTO bot_admins (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", user_id)
            return True
        except Exception as e:
            logging.error(f"Error adding admin {user_id} to DB: {e}")
            return False

async def delete_admin_from_db(user_id: int):
    async with DB_POOL.acquire() as conn:
        result = await conn.execute("DELETE FROM bot_admins WHERE user_id = $1", user_id)
        return result != "DELETE 0"

async def is_user_admin_in_db(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True
    admins = await get_admins_from_db()
    return user_id in admins

async def create_subscription_task_keyboard(user_id: int) -> InlineKeyboardMarkup:
    channels = await get_channels_from_db()
    addlists = await get_addlists_from_db()
    keyboard_buttons = []

    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel['id'], user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator', 'restricted'] or \
               (member.status == 'restricted' and hasattr(member, 'is_member') and not member.is_member):
                keyboard_buttons.append([
                    InlineKeyboardButton(text=f"{channel['name']}", url=f"https://t.me/{str(channel['id']).lstrip('@')}")
                ])
        except Exception as e:
            logging.error(f"Kanala agzalygy barlamakda ýalňyşlyk {channel['id']} ulanyjy {user_id} üçin: {e}")
            keyboard_buttons.append([
                InlineKeyboardButton(text=f"⚠️ {channel['name']} (barlag ýalňyşlygy)", url=f"https://t.me/{str(channel['id']).lstrip('@')}")
            ])
            continue
    for addlist in addlists:
        keyboard_buttons.append([
            InlineKeyboardButton(text=f"{addlist['name']}", url=addlist['url'])
        ])
    if keyboard_buttons:
        keyboard_buttons.append([
            InlineKeyboardButton(text="✅ Agza Boldum", callback_data="check_subscription")
        ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

async def has_unsubscribed_channels(user_id: int) -> bool:
    channels = await get_channels_from_db()
    if not channels:
        return False
    for channel in channels:
        try:
            chat_identifier = channel['id']
            if not (isinstance(chat_identifier, str) and chat_identifier.startswith('@')):
                try:
                    chat_identifier = int(str(chat_identifier))
                except ValueError:
                    logging.error(f"get_chat_member üçin nädogry kanal ID formaty: {channel['id']}. Geçirilýär.")
                    return True
            member = await bot.get_chat_member(chat_id=chat_identifier, user_id=user_id)
            if member.status == 'restricted':
                if hasattr(member, 'is_member') and not member.is_member:
                    logging.info(f"Ulanyjy {user_id} {channel['id']} kanala AGZA BOLMADYK (ýagdaýy: {member.status}, is_member=False)")
                    return True
            elif member.status not in ['member', 'administrator', 'creator']:
                logging.info(f"Ulanyjy {user_id} {channel['id']} kanala AGZA BOLMADYK (ýagdaýy: {member.status})")
                return True
        except TelegramForbiddenError:
            logging.error(f"TelegramForbiddenError: Bot {channel['id']} kanalyň adminy däl. Howpsuzlyk üçin ulanyjy agza bolmadyk hasaplanýar.")
            return True
        except TelegramBadRequest as e:
            logging.warning(f"Ulanyjy {user_id}-iň {channel['id']} kanala agzalygy barlanda TelegramBadRequest: {e}. Ulanyjy agza bolmadyk hasaplanýar.")
            return True
        except Exception as e:
            logging.warning(f"Ulanyjy {user_id}-iň {channel['id']} kanala agzalygyny barlanda umumy ýalňyşlyk: {e}. Ulanyjy Agza bolmadyk hasaplanýar.")
            return True
    return False

# --- GÜNCELLENDI ---
# Admin paneline yeni düymeler eklendi
def create_admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Bot statistikasy", callback_data="get_stats"),
         InlineKeyboardButton(text="📋 Sanawlary görmek", callback_data="view_lists")],
        [InlineKeyboardButton(text="🚀 Ulanyjylara ibermek", callback_data="start_mailing"),
         InlineKeyboardButton(text="📢 Kanallara ibermek", callback_data="start_channel_mailing")],
        [InlineKeyboardButton(text="➕ Kanal goşmak", callback_data="add_channel"),
         InlineKeyboardButton(text="➖ Kanal pozmak", callback_data="delete_channel")],
        [InlineKeyboardButton(text="➕ Köp kanallary goşmak", callback_data="bulk_add_channel"),
         InlineKeyboardButton(text="➖ Köp kanallary pozmak", callback_data="bulk_delete_channel")],
        [InlineKeyboardButton(text="📁 addlist goşmak", callback_data="add_addlist"),
         InlineKeyboardButton(text="🗑️ addlist pozmak", callback_data="delete_addlist")],
        [InlineKeyboardButton(text="🔑 VPN goşmak", callback_data="add_vpn_config"),
         InlineKeyboardButton(text="🗑️ VPN pozmak", callback_data="delete_vpn_config")],
        [InlineKeyboardButton(text="✏️ Başlangyç haty üýtgetmek", callback_data="change_welcome")]
    ]
    if user_id == SUPER_ADMIN_ID:
        buttons.extend([
            [InlineKeyboardButton(text="👮 Admin goşmak", callback_data="add_admin"), InlineKeyboardButton(text="🚫 Admin pozmak", callback_data="delete_admin")]
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ Admin panelden çykmak", callback_data="exit_admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await add_user_to_db(user_id)

    vpn_configs_full = await get_vpn_configs_from_db()
    vpn_configs = [item['config_text'] for item in vpn_configs_full]

    if not vpn_configs:
        await message.answer("😔 Gynansak-da, häzirki wagtda elýeterli VPN Kodlary ýok. Haýyş edýäris, soňrak synanyşyň.")
        await state.clear()
        return

    user_needs_to_subscribe_to_channels = await has_unsubscribed_channels(user_id)
    channels_exist = bool(await get_channels_from_db())

    if not user_needs_to_subscribe_to_channels:
        vpn_config_text = random.choice(vpn_configs)
        text = "🎉 Siz ähli kanallara Agza boldyňyz! " if channels_exist else "✨ Agza bolanyňyzüçin sagboluň!"
        await message.answer(
            f"{text}\n\n"
            f"🔑 <b>siziň VPN Kodyňyz:</b>\n<pre><code>{vpn_config_text}</code></pre>"
        )
        await state.clear()
    else:
        keyboard = await create_subscription_task_keyboard(user_id)
        welcome_text = await get_setting_from_db('welcome_message', "👋 <b>Hoş geldiňiz!</b>\n\nVPN almak üçin, aşakdaky Kanallara agza boluň we 'Agza boldum' düwmesine basyň.")
        if not keyboard.inline_keyboard:
            if vpn_configs:
                 vpn_config_text = random.choice(vpn_configs)
                 await message.answer(f"✨ Agza bolanyňyz üçin sagboluň!\n\n🔑 <b>Siziň VPN Kodyňyz:</b>\n<pre><code>{vpn_config_text}</code></pre>")
            else:
                 await message.answer("😔 Häzirki wagtda elýeterli VPN kodlary ýok.")
            await state.clear()
        else:
            await message.answer(welcome_text, reply_markup=keyboard)
            await state.set_state(SubscriptionStates.checking_subscription)

# --- YENI ---
# /help komutu
@router.message(Command("help"))
async def help_command(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🆘 <b>Adminlere ýüzlenme</b>\n\n"
        "Admine ibermek isleýän soragyňyzy ýa-da hatyňyzy ýazyň. Hatyňyz adminlere iberiler."
    )
    await state.set_state(HelpStates.waiting_for_help_message)

# --- YENI ---
# Kullanıcının yardım mesajını alıp adminlere ileten fonksiyon
@router.message(HelpStates.waiting_for_help_message)
async def process_help_message(message: types.Message, state: FSMContext):
    await state.clear()

    admins = await get_admins_from_db()
    if SUPER_ADMIN_ID not in admins:
        admins.append(SUPER_ADMIN_ID)

    user = message.from_user
    user_info = f"{user.full_name}"
    if user.username:
        user_info += f" (@{user.username})"

    text_to_admins = (
        f"🆘 <b>Täze kömek haýyşy</b>\n\n"
        f"<b>Kimden:</b> {user_info}\n"
        f"<b>User ID:</b> <code>{user.id}</code>\n\n"
        f"<b>Haty:</b>\n«{message.html_text}»"
    )

    reply_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Jogap bermek", callback_data=f"reply_to_user:{user.id}")]
    ])

    for admin_id in admins:
        try:
            await bot.send_message(admin_id, text_to_admins, reply_markup=reply_markup)
        except (TelegramForbiddenError, TelegramBadRequest):
            logging.warning(f"Admin {admin_id} bloklanandygy sebäpli kömek haty iberilmedi.")
        except Exception as e:
            logging.error(f"Admin {admin_id} üçin kömek hatyny ibermekde näsazlyk: {e}")

    await message.answer("✅ Hatyňyz adminlere üstünlikli iberildi. Gysga wagtda size jogap bererler.")

# --- YENI ---
# Adminin "Yanıtla" düğmesine basmasını işleyen fonksiyon
@router.callback_query(F.data.startswith("reply_to_user:"))
async def prompt_admin_reply(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return

    try:
        user_id_to_reply = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("❌ Ulanyjy ID nädogry.", show_alert=True)
        return

    await state.update_data(user_id_to_reply=user_id_to_reply, original_admin_message_id=callback.message.message_id)
    await callback.message.edit_text(
        f"{callback.message.html_text}\n\n"
        f"✍️ <code>{user_id_to_reply}</code> ID-li ulanyja jogabyňyzy ýazyň:",
        reply_markup=None
    )
    await state.set_state(HelpStates.waiting_for_admin_reply)
    await callback.answer()

# --- YENI ---
# Adminin yanıtını kullanıcıya gönderen fonksiyon
@router.message(HelpStates.waiting_for_admin_reply)
async def send_reply_to_user(message: types.Message, state: FSMContext):
    fsm_data = await state.get_data()
    user_id_to_reply = fsm_data.get("user_id_to_reply")
    original_admin_message_id = fsm_data.get("original_admin_message_id")

    if not user_id_to_reply:
        await message.answer("❌ Näsazlyk, ulanyjy ID tapylmady. Täzeden synanyşyň.")
        await state.clear()
        return

    try:
        await bot.send_message(
            user_id_to_reply,
            "📩 <b>Adminden bir jogap geldi:</b>\n\n"
            f"{message.html_text}"
        )
        await message.answer(f"✅ Jogabyňyz <code>{user_id_to_reply}</code> ID-li ulanyja iberildi.")

        # Orijinal yardım isteği mesajını temizle
        if original_admin_message_id:
            try:
                original_message_text = (await bot.get_chat_history(chat_id=message.chat.id, message_id=original_admin_message_id)).messages[0].html_text
                await bot.edit_message_text(
                    f"{original_message_text}\n\n"
                    f"--- ✅ <i>Jogap berildi</i> ---",
                    chat_id=message.chat.id,
                    message_id=original_admin_message_id
                )
            except Exception as e:
                logging.warning(f"Could not edit original help request message: {e}")

    except (TelegramForbiddenError, TelegramBadRequest):
        await message.answer(f"❌ Jogap iberilmedi. Ulanyjy (<code>{user_id_to_reply}</code>) boty bloklan bolmagy mümkin.")
    except Exception as e:
        await message.answer(f"❌ Jogap iberilende näsazlyk ýüze çykdy: {e}")

    await state.clear()


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
        await callback.message.edit_text(
            "✅ Siz admin panelden çykdyňyz.\n\nAdaty ulanyjy hökmünde täzeden işe başlamak üçin /start giriziň",
            reply_markup=None
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "✅ Siz admin panelden çykdyňyz.\n\nAdaty ulanyjy hökmünde täzeden işe başlamak üçin /start giriziň",
            reply_markup=None
        )
    await callback.answer()

@router.callback_query(lambda c: c.data == "get_stats")
async def get_statistics(callback: types.CallbackQuery):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return

    async with DB_POOL.acquire() as conn:
        user_count = await conn.fetchval("SELECT COUNT(*) FROM bot_users")
        channel_count = await conn.fetchval("SELECT COUNT(*) FROM channels")
        addlist_count = await conn.fetchval("SELECT COUNT(*) FROM addlists")
        vpn_count = await conn.fetchval("SELECT COUNT(*) FROM vpn_configs")
        admin_count = await conn.fetchval("SELECT COUNT(*) FROM bot_admins")

    status_description = "Bot işleýär" if vpn_count > 0 else "VPN KODLARY ÝOK!"
    alert_text = (
        f"📊 Bot statistikasy:\n"
        f"👤 Ulanyjylar: {user_count}\n"
        f"📢 Kanallar: {channel_count}\n"
        f"📁 addlistlar: {addlist_count}\n"
        f"🔑 VPN Kodlary: {vpn_count}\n"
        f"👮 Adminler (goşm.): {admin_count}\n"
        f"⚙️ Ýagdaýy: {status_description}"
    )
    try:
        await callback.answer(text=alert_text, show_alert=True)
    except Exception as e:
        logging.error(f"Statistikany duýduryşda görkezmekde ýalňyşlyk: {e}")
        await callback.answer("⚠️ Statistika görkezmekde ýalňyşlyk.", show_alert=True)

# --- YENI ---
# Listeleme menüsünü gösterir
@router.callback_query(lambda c: c.data == "view_lists")
async def view_lists_callback(callback: types.CallbackQuery):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📢 Kanallary görmek", callback_data="view_channels"),
            InlineKeyboardButton(text="👮 Adminleri görmek", callback_data="view_admins")
        ],
        [
            InlineKeyboardButton(text="📥 Ulanyjylary faýla ýüklemek", callback_data="export_users")
        ],
        [
            InlineKeyboardButton(text="⬅️ Yza", callback_data="admin_panel_main")
        ]
    ])
    await callback.message.edit_text("📋 <b>Sanawlary görmek</b>\n\nGörmek isleýän sanawyňyzy saýlaň:", reply_markup=keyboard)
    await callback.answer()

# --- YENI ---
# Kanalları listeler
@router.callback_query(lambda c: c.data == "view_channels")
async def view_channels_callback(callback: types.CallbackQuery):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return

    channels = await get_channels_from_db()
    if not channels:
        await callback.answer("ℹ️ Botda hiç hili kanal ýok.", show_alert=True)
        return

    message_text = "📢 <b>Bota goşulan kanallar:</b>\n\n"
    for channel in channels:
        name = channel.get('name')
        channel_id = channel.get('id')
        try:
            chat = await bot.get_chat(channel_id)
            link = f" (@{chat.username})" if chat.username else ""
            message_text += f"• <b>{name}</b> - <code>{channel_id}</code>{link}\n"
        except Exception:
            message_text += f"• <b>{name}</b> - <code>{channel_id}</code> (maglumat alynmady)\n"

    await callback.message.edit_text(message_text, reply_markup=back_to_admin_markup, disable_web_page_preview=True)
    await callback.answer()

# --- YENI ---
# Adminleri listeler
@router.callback_query(lambda c: c.data == "view_admins")
async def view_admins_callback(callback: types.CallbackQuery):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return

    admin_ids = await get_admins_from_db()
    all_admins = {SUPER_ADMIN_ID, *admin_ids} # Use a set to avoid duplicates

    if not all_admins:
        await callback.answer("ℹ️ Baş adminden başga admin ýok.", show_alert=True)
        return

    message_text = "👮 <b>Bot adminleri:</b>\n\n"
    for admin_id in all_admins:
        role = "👑 Baş Admin" if admin_id == SUPER_ADMIN_ID else "👮 Admin"
        try:
            user = await bot.get_chat(admin_id)
            user_display = f"<b>{user.full_name}</b>"
            if user.username:
                user_display += f" (@{user.username})"
            message_text += f"• {user_display} - <code>{admin_id}</code> [{role}]\n"
        except Exception:
            message_text += f"• <i>Näbelli Admin</i> - <code>{admin_id}</code> [{role}]\n"

    await callback.message.edit_text(message_text, reply_markup=back_to_admin_markup, disable_web_page_preview=True)
    await callback.answer()

# --- YENI ---
# Kullanıcıları users.json olarak dışa aktarır
@router.callback_query(lambda c: c.data == "export_users")
async def export_users_callback(callback: types.CallbackQuery):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return

    await callback.answer("⏳ Ulanyjy sanawy taýýarlanylýar...", show_alert=False)
    users = await get_users_from_db()

    if not users:
        await callback.answer("ℹ️ Botda hiç hili ulanyjy ýok.", show_alert=True)
        return

    user_data = {"users": users}

    # Create a file in memory
    json_str = json.dumps(user_data, indent=4)
    file_bytes = io.BytesIO(json_str.encode('utf-8'))
    file_bytes.name = 'users.json'

    try:
        await bot.send_document(
            callback.from_user.id,
            InputFile(file_bytes),
            caption=f"✅ Ähli <b>{len(users)}</b> sany ulanyjynyň sanawy `users.json` faýlynda."
        )
    except Exception as e:
        await callback.message.answer(f"❌ Faýl iberilende näsazlyk: {e}")


# --- YENI ---
# Toplu kanal ekleme istemi
@router.callback_query(lambda c: c.data == "bulk_add_channel")
async def bulk_add_channel_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    await callback.message.edit_text(
        "➕ <b>Köp kanallary goşmak</b> ➕\n\n"
        "Goşmak isleýän kanallaryňyzyň sanawyny aşakdaky formatda iberiň (her kanal täze setirde):\n"
        "<code>@kanal_ady - Kanal Ady</code>\n"
        "<code>-10012345678 - Hususy Kanal Ady</code>",
        reply_markup=back_to_admin_markup
    )
    await state.set_state(AdminStates.waiting_for_bulk_channel_list)
    await callback.answer()

# --- YENI ---
# Toplu kanal ekleme işlemini gerçekleştirir
@router.message(AdminStates.waiting_for_bulk_channel_list)
async def process_bulk_channel_list(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    await state.clear()
    lines = message.text.strip().split('\n')
    status_msg = await message.answer(f"⏳ <b>{len(lines)}</b> sany kanaly barlap başlaýarys...")

    success_list = []
    error_list = []
    channels_in_db = [ch['id'] for ch in await get_channels_from_db()]

    for i, line in enumerate(lines):
        await status_msg.edit_text(f"⏳ Kanal {i+1}/{len(lines)} barlanýar: <code>{line.split(' - ')[0]}</code>")
        if ' - ' not in line:
            error_list.append(f"<code>{line}</code> - Ýalňyş format (arada ' - ' bolmaly)")
            continue

        channel_id, name = [part.strip() for part in line.split(' - ', 1)]

        # ID format kontrolü
        if not (channel_id.startswith('@') or (channel_id.startswith('-100') and channel_id[1:].replace('-', '', 1).isdigit())):
            error_list.append(f"<code>{channel_id}</code> - Ýalňyş ID formaty")
            continue

        # Zaten ekli mi kontrolü
        if channel_id in channels_in_db:
            error_list.append(f"<code>{channel_id}</code> - Eýýäm sanawda bar")
            continue

        # Bot admin mi kontrolü
        try:
            bot_member = await bot.get_chat_member(chat_id=channel_id, user_id=bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                error_list.append(f"<code>{channel_id}</code> - Bot admin däl")
                continue
        except Exception:
            error_list.append(f"<code>{channel_id}</code> - Barlap bolmady (ID ýalňyş ýa-da bot agza däl)")
            continue

        # Veritabanına ekleme
        if await add_channel_to_db(channel_id, name):
            success_list.append(f"<b>{name}</b> (<code>{channel_id}</code>)")
            channels_in_db.append(channel_id) # Tekrar kontrol etmemek için ekle
        else:
            error_list.append(f"<code>{channel_id}</code> - DB ýalňyşlygy")

    success_text = "✅ <b>Üstünlikli goşulanlar:</b>\n" + "\n".join(success_list) if success_list else ""
    error_text = "❌ <b>Goşulyp bilinmedikler:</b>\n" + "\n".join(error_list) if error_list else ""

    final_report = f" Rapor:\n\n{success_text}\n\n{error_text}".strip()
    await status_msg.edit_text(final_report, reply_markup=back_to_admin_markup)

# --- YENI ---
# Toplu kanal silme istemi
@router.callback_query(lambda c: c.data == "bulk_delete_channel")
async def bulk_delete_channel_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    await callback.message.edit_text(
        "➖ <b>Köp kanallary pozmak</b> ➖\n\n"
        "Pozmak isleýän kanallaryňyzyň ID-lerini (<code>@username</code> ýa-da <code>-100...</code>) her setire birini ýazyp iberiň.",
        reply_markup=back_to_admin_markup
    )
    await state.set_state(AdminStates.waiting_for_bulk_delete_list)
    await callback.answer()

# --- YENI ---
# Toplu kanal silme işlemini gerçekleştirir
@router.message(AdminStates.waiting_for_bulk_delete_list)
async def process_bulk_delete_list(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    await state.clear()
    ids_to_delete = message.text.strip().split('\n')
    status_msg = await message.answer(f"⏳ <b>{len(ids_to_delete)}</b> sany kanaly pozup başlaýarys...")

    success_count = 0
    fail_list = []

    for i, channel_id in enumerate(ids_to_delete):
        channel_id = channel_id.strip()
        await status_msg.edit_text(f"⏳ Kanal {i+1}/{len(ids_to_delete)} pozulýar: <code>{channel_id}</code>")
        if await delete_channel_from_db(channel_id):
            success_count += 1
        else:
            fail_list.append(f"<code>{channel_id}</code>")

    success_text = f"✅ <b>{success_count}</b> sany kanal üstünlikli pozuldy."
    error_text = f"❌ <b>Pozulyp bilinmedikler (tapylmady):</b>\n" + "\n".join(fail_list) if fail_list else ""

    final_report = f" Rapor:\n\n{success_text}\n{error_text}".strip()
    await status_msg.edit_text(final_report, reply_markup=back_to_admin_markup)


def parse_buttons_from_text(text: str) -> types.InlineKeyboardMarkup | None:
    lines = text.strip().split('\n')
    keyboard_buttons = []
    for line in lines:
        if ' - ' not in line:
            continue
        parts = line.split(' - ', 1)
        btn_text = parts[0].strip()
        btn_url = parts[1].strip()
        if btn_text and (btn_url.startswith('https://') or btn_url.startswith('http://')):
            keyboard_buttons.append([types.InlineKeyboardButton(text=btn_text, url=btn_url)])
    if not keyboard_buttons:
        return None
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

async def process_mailing_content(message: Message, state: FSMContext, mail_type: str):
    content = {}
    if message.photo:
        content = {
            'type': 'photo',
            'file_id': message.photo[-1].file_id,
            'caption': message.caption
        }
    elif message.video:
        content = {
            'type': 'video',
            'file_id': message.video.file_id,
            'caption': message.caption
        }
    elif message.animation:
        content = {
            'type': 'animation',
            'file_id': message.animation.file_id,
            'caption': message.caption
        }
    elif message.text:
        content = {
            'type': 'text',
            'text': message.html_text
        }
    else:
        await message.answer("⚠️ Bu habar görnüşi goldanmaýar. Tekst, surat, wideo ýa-da GIF iberiň.")
        return

    await state.update_data(mailing_content=content)

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = message.chat.id

    try:
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

    if mail_type == "user":
        await state.set_state(AdminStates.waiting_for_mailing_confirmation)
    else:
        await state.set_state(AdminStates.waiting_for_channel_mailing_confirmation)


async def execute_user_broadcast(admin_message: types.Message, mailing_content: dict, mailing_keyboard: types.InlineKeyboardMarkup | None):
    users_to_mail = await get_users_from_db()

    if not users_to_mail:
        await admin_message.edit_text("👥 Ibermek üçin ulanyjylar ýok.", reply_markup=back_to_admin_markup)
        return

    await admin_message.edit_text(f"⏳ <b>{len(users_to_mail)}</b> sany ulanyja ibermek başlanýar...", reply_markup=None)

    success_count = 0
    fail_count = 0
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


@router.callback_query(lambda c: c.data == "start_mailing")
async def start_mailing_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id): return

    last_content, _ = await get_last_mail_content("user")

    keyboard_buttons = [[InlineKeyboardButton(text="➕ Täze habar döretmek", callback_data="create_new_user_mail")]]
    if last_content:
        keyboard_buttons.insert(0, [InlineKeyboardButton(text="🔄 Soňky habary ulanmak", callback_data="repeat_last_user_mail")])

    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Yza", callback_data="admin_panel_main")])

    await callback.message.edit_text(
        "📬 <b>Ulanyjylara Iberiş</b> 📬\n\nBir hereket saýlaň:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    )
    await state.set_state(AdminStates.waiting_for_user_mail_action)
    await callback.answer()


@router.callback_query(AdminStates.waiting_for_user_mail_action)
async def process_user_mail_action(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data
    if action == "create_new_user_mail":
        await callback.message.edit_text(
            "✍️ Ibermek isleýän habaryňyzy (tekst, surat, wideo ýa-da GIF) iberiň.",
            reply_markup=back_to_admin_markup
        )
        await state.update_data(admin_message_id=callback.message.message_id)
        await state.set_state(AdminStates.waiting_for_mailing_message)
    elif action == "repeat_last_user_mail":
        content, keyboard = await get_last_mail_content("user")
        if not content:
            await callback.answer("⚠️ Soňky habar tapylmady.", show_alert=True)
            return

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


@router.message(AdminStates.waiting_for_mailing_message, F.content_type.in_({'text', 'photo', 'video', 'animation'}))
async def process_user_mailing_message(message: Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    await process_mailing_content(message, state, "user")


@router.callback_query(AdminStates.waiting_for_mailing_confirmation)
async def process_user_mailing_confirmation(callback: types.CallbackQuery, state: FSMContext):
    fsm_data = await state.get_data()
    mailing_content = fsm_data.get('mailing_content')
    mailing_keyboard = fsm_data.get('mailing_keyboard')

    try:
        await bot.delete_message(callback.from_user.id, fsm_data.get('admin_message_id'))
        await bot.delete_message(callback.from_user.id, fsm_data.get('preview_message_id'))
    except (TelegramBadRequest, KeyError): pass

    if not mailing_content:
        await bot.send_message(callback.from_user.id, "⚠️ Ýalňyşlyk: habar tapylmady.", reply_markup=back_to_admin_markup)
        await state.clear()
        return

    if callback.data in ["user_mail_confirm_send", "user_mail_confirm_send_repeated"]:
        msg_for_broadcast = await bot.send_message(callback.from_user.id, "⏳...")
        await execute_user_broadcast(msg_for_broadcast, mailing_content, mailing_keyboard)
        await state.clear()
    elif callback.data == "user_mail_confirm_add_buttons":
        msg = await bot.send_message(
            callback.from_user.id,
            "🔗 <b>Düwmeleri goşmak</b> 🔗\n\nFormat: <code>Tekst - https://salgy.com</code>\nHer düwme täze setirde.",
            reply_markup=back_to_admin_markup
        )
        await state.update_data(admin_message_id=msg.message_id)
        await state.set_state(AdminStates.waiting_for_mailing_buttons)
    await callback.answer()


@router.message(AdminStates.waiting_for_mailing_buttons)
async def process_user_mailing_buttons(message: Message, state: FSMContext):
    keyboard = parse_buttons_from_text(message.text)
    if not keyboard:
        await message.answer("⚠️ Nädogry format! Täzeden synanyşyň.")
        return

    await message.delete()
    fsm_data = await state.get_data()
    mailing_content = fsm_data.get('mailing_content')

    try: await bot.delete_message(message.chat.id, fsm_data.get('admin_message_id'))
    except (TelegramBadRequest, KeyError): pass

    msg_for_broadcast = await bot.send_message(message.chat.id, "⏳...")
    await execute_user_broadcast(msg_for_broadcast, mailing_content, keyboard)
    await state.clear()


async def execute_channel_broadcast(admin_message: types.Message, mailing_content: dict, mailing_keyboard: types.InlineKeyboardMarkup | None):
    channels_to_mail = await get_channels_from_db()
    if not channels_to_mail:
        await admin_message.edit_text("📢 Ibermek üçin kanallar ýok.", reply_markup=back_to_admin_markup)
        return

    await admin_message.edit_text(f"⏳ <b>{len(channels_to_mail)}</b> sany kanala ibermek başlanýar...", reply_markup=None)

    success_count = 0
    fail_count = 0
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

    await callback.message.edit_text(
        "📢 <b>Kanallara Iberiş</b> 📢\n\nBir hereket saýlaň:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    )
    await state.set_state(AdminStates.waiting_for_channel_mail_action)
    await callback.answer()


@router.callback_query(AdminStates.waiting_for_channel_mail_action)
async def process_channel_mail_action(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data
    if action == "create_new_channel_mail":
        await callback.message.edit_text(
            "✍️ Ibermek isleýän habaryňyzy (tekst, surat, wideo ýa-da GIF) iberiň.",
            reply_markup=back_to_admin_markup
        )
        await state.update_data(admin_message_id=callback.message.message_id)
        await state.set_state(AdminStates.waiting_for_channel_mailing_message)
    elif action == "repeat_last_channel_mail":
        content, keyboard = await get_last_mail_content("channel")
        if not content:
            await callback.answer("⚠️ Soňky habar tapylmady.", show_alert=True)
            return

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


@router.message(AdminStates.waiting_for_channel_mailing_message, F.content_type.in_({'text', 'photo', 'video', 'animation'}))
async def process_channel_mailing_message(message: Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    await process_mailing_content(message, state, "channel")


@router.callback_query(AdminStates.waiting_for_channel_mailing_confirmation)
async def process_channel_mailing_confirmation(callback: types.CallbackQuery, state: FSMContext):
    fsm_data = await state.get_data()
    mailing_content = fsm_data.get('mailing_content')
    mailing_keyboard = fsm_data.get('mailing_keyboard')

    try:
        await bot.delete_message(callback.from_user.id, fsm_data.get('admin_message_id'))
        await bot.delete_message(callback.from_user.id, fsm_data.get('preview_message_id'))
    except (TelegramBadRequest, KeyError): pass

    if not mailing_content:
        await bot.send_message(callback.from_user.id, "⚠️ Ýalňyşlyk: habar tapylmady.", reply_markup=back_to_admin_markup)
        await state.clear()
        return

    if callback.data in ["channel_mail_confirm_send", "channel_mail_confirm_send_repeated"]:
        msg_for_broadcast = await bot.send_message(callback.from_user.id, "⏳...")
        await execute_channel_broadcast(msg_for_broadcast, mailing_content, mailing_keyboard)
        await state.clear()
    elif callback.data == "channel_mail_confirm_add_buttons":
        msg = await bot.send_message(
            callback.from_user.id,
            "🔗 <b>Düwmeleri goşmak</b> 🔗\n\nFormat: <code>Tekst - https://salgy.com</code>\nHer düwme täze setirde.",
            reply_markup=back_to_admin_markup
        )
        await state.update_data(admin_message_id=msg.message_id)
        await state.set_state(AdminStates.waiting_for_channel_mailing_buttons)
    await callback.answer()


@router.message(AdminStates.waiting_for_channel_mailing_buttons)
async def process_channel_mailing_buttons(message: Message, state: FSMContext):
    keyboard = parse_buttons_from_text(message.text)
    if not keyboard:
        await message.answer("⚠️ Nädogry format! Täzeden synanyşyň.")
        return

    await message.delete()
    fsm_data = await state.get_data()
    mailing_content = fsm_data.get('mailing_content')

    try: await bot.delete_message(message.chat.id, fsm_data.get('admin_message_id'))
    except (TelegramBadRequest, KeyError): pass

    msg_for_broadcast = await bot.send_message(message.chat.id, "⏳...")
    await execute_channel_broadcast(msg_for_broadcast, mailing_content, keyboard)
    await state.clear()


@router.callback_query(lambda c: c.data == "add_channel")
async def process_add_channel_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    await callback.message.edit_text(
        "📡 <b>Kanal Goşmak</b> 📡\n\n"
        "Kanalyň ID-sini giriziň (meselem, <code>@PublicChannel</code>) ýa-da şahsy kanalyň ID-sini (meselem, <code>-1001234567890</code>).\n\n"
        "<i>Bot, agzalar barada maglumat almak hukugy bilen kanala administrator hökmünde goşulmaly.</i>\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")]])
    )
    await state.update_data(admin_message_id=callback.message.message_id, admin_chat_id=callback.message.chat.id)
    await state.set_state(AdminStates.waiting_for_channel_id)
    await callback.answer()


@router.message(AdminStates.waiting_for_channel_id)
async def process_channel_id(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    channel_id_input = message.text.strip()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    original_prompt_id = (
        "📡 <b>Kanal Goşmak: ID</b> 📡\n\n"
        "Kanalyň ID-sini giriziň (<code>@PublicChannel</code> ýa-da <code>-100...</code>).\n"
        "<i>Bot kanalda administrator bolmaly.</i>"
    )
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not admin_message_id or not admin_chat_id:
        await bot.send_message(message.chat.id, "⚠️ Ýagdaý ýalňyşlygy. Admin panelden täzeden synanyşyň.", reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    if not (channel_id_input.startswith('@') or (channel_id_input.startswith('-100') and channel_id_input[1:].replace('-', '', 1).isdigit())):
        await bot.edit_message_text(
            f"⚠️ <b>Ýalňyşlyk:</b> Nädogry kanal ID formaty.\n\n{original_prompt_id}",
            chat_id=admin_chat_id, message_id=admin_message_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row])
        )
        return

    channels_in_db = await get_channels_from_db()
    if any(str(ch['id']) == str(channel_id_input) for ch in channels_in_db):
        await bot.edit_message_text(f"⚠️ Bu kanal (<code>{channel_id_input}</code>) eýýäm sanawda bar.\n\n{original_prompt_id}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    try:
        chat_to_check_str = channel_id_input
        chat_to_check = int(chat_to_check_str) if not chat_to_check_str.startswith('@') else chat_to_check_str

        bot_member = await bot.get_chat_member(chat_id=chat_to_check, user_id=bot.id)
        if bot_member.status not in ['administrator', 'creator']:
            await bot.edit_message_text(
                "⚠️ <b>Ýalňyşlyk:</b> Bot bu kanalyň administratory däl (ýa-da gatnaşyjylar barada maglumat almak hukugy ýok).\n"
                "Haýyş edýäris, boty kanala zerur hukuklar bilen administrator hökmünde goşuň we täzeden synanyşyň.",
                chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup
            )
            await state.clear()
            return
    except ValueError:
        await bot.edit_message_text(
            f"⚠️ <b>Ýalňyşlyk:</b> Şahsy kanalyň ID-si san bolmaly (meselem, <code>-1001234567890</code>).\n\n{original_prompt_id}",
            chat_id=admin_chat_id, message_id=admin_message_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row])
        )
        return
    except TelegramBadRequest as e:
        logging.error(f"TelegramBadRequest при проверке статуса бота в канале {channel_id_input}: {e}")
        error_detail = str(e)
        specific_guidance = ""
        if "member list is inaccessible" in error_detail.lower():
            specific_guidance = ("<b>Maslahat:</b> Botuň 'Çaty dolandyryp bilmek' ýa-da ş.m., gatnaşyjylaryň sanawyny almaga mümkinçilik berýän hukugynyň bardygyna göz ýetiriň. Käbir ýagdaýlarda, eger kanal çat bilen baglanyşykly bolsa, hukuklar miras alnyp bilner.")
        elif "chat not found" in error_detail.lower():
            specific_guidance = "<b>Maslahat:</b> Kanal ID-siniň dogry girizilendigine we kanalyň bardygyna göz ýetiriň. Jemgyýetçilik kanallary üçin @username, şahsy kanallar üçin bolsa sanly ID ( -100 bilen başlaýan) ulanyň."
        elif "bot is not a member of the channel" in error_detail.lower() or "user not found" in error_detail.lower():
             specific_guidance = "<b>Maslahat:</b> Bot görkezilen kanalyň agzasy däl. Haýyş edýäris, ilki boty kanala goşuň."
        await bot.edit_message_text(
            f"⚠️ <b>Botyň kanaldaky ýagdaýyny barlamakda ýalňyşlyk:</b>\n<code>{error_detail}</code>\n\n"
            f"{specific_guidance}\n\n"
            "ID-niň dogrudygyny, botyň kanala goşulandygyny we zerur administrator hukuklarynyň bardygyny barlaň.",
            chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup
        )
        await state.clear()
        return
    except Exception as e:
        logging.error(f"ýalňyşlyk {channel_id_input}: {e}")
        await bot.edit_message_text(
            f"⚠️ <b>Botyň kanaldaky ýagdaýyny barlamakda garaşylmadyk ýalňyşlyk:</b> <code>{e}</code>.\n"
            "ID-niň dogrudygyny, botyň kanala goşulandygyny we administrator hukuklarynyň bardygyny barlaň.",
            chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup
        )
        await state.clear()
        return

    await state.update_data(channel_id=channel_id_input)
    await bot.edit_message_text(
        "✏️ Indi bu kanal üçin <b>görkezilýän ady</b> giriziň (meselem, <i>TKM VPNLAR</i>):",
        chat_id=admin_chat_id, message_id=admin_message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row])
    )
    await state.set_state(AdminStates.waiting_for_channel_name)


@router.message(AdminStates.waiting_for_channel_name)
async def save_channel(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    channel_name = message.text.strip()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    channel_id_str = fsm_data.get('channel_id')
    original_prompt_name = "✏️ Kanal üçin <b>görkezilýän ady</b> giriziň (meselem, <i>Tehnologiýa Habarlary</i>):"
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not all([admin_message_id, admin_chat_id, channel_id_str]):
        err_msg_text = "⚠️ Ýagdaý ýalňyşlygy (zerur maglumatlar ýok). Kanaly täzeden goşmagy synanyşyň."
        if admin_message_id and admin_chat_id:
            try:
                await bot.edit_message_text(err_msg_text, chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
            except TelegramBadRequest:
                 await bot.send_message(admin_chat_id, err_msg_text, reply_markup=back_to_admin_markup)
        else:
            await bot.send_message(message.chat.id, err_msg_text, reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    if not channel_name:
        await bot.edit_message_text(f"⚠️ Kanal ady boş bolup bilmez.\n\n{original_prompt_name}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    success = await add_channel_to_db(channel_id_str, channel_name)
    if success:
        await bot.edit_message_text(f"✅ <b>{channel_name}</b> kanaly (<code>{channel_id_str}</code>) üstünlikli goşuldy!", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    else:
        await bot.edit_message_text(f"⚠️ <b>{channel_name}</b> kanalyny (<code>{channel_id_str}</code>) goşmak başartmady. Mümkin, ol eýýäm bar ýa-da maglumatlar bazasynda ýalňyşlyk boldy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()


@router.callback_query(lambda c: c.data == "delete_channel")
async def process_delete_channel_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return

    channels = await get_channels_from_db()

    if not channels:
        await callback.message.edit_text("🗑️ Kanallaryň sanawy boş. Pozmak üçin hiç zat ýok.", reply_markup=back_to_admin_markup)
        await callback.answer()
        return

    keyboard_buttons = [
        [InlineKeyboardButton(text=f"{channel['name']} ({channel['id']})", callback_data=f"del_channel:{channel['id']}")] for channel in channels
    ]
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")])

    await callback.message.edit_text("🔪 <b>Kanal Pozmak</b> 🔪\n\nSanawdan pozmak üçin kanaly saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))
    await callback.answer()


@router.callback_query(lambda c: c.data == "admin_panel_main")
async def back_to_admin_panel(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return

    admin_reply_markup = create_admin_keyboard(callback.from_user.id)
    try:
        await callback.message.edit_text(
            "⚙️ <b>Admin-panel</b>\n\nBir hereket saýlaň:",
            reply_markup=admin_reply_markup
        )
    except TelegramBadRequest:
        await callback.message.answer(
             "⚙️ <b>Admin-panel</b>\n\nBir hereket saýlaň:",
            reply_markup=admin_reply_markup
        )
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
    await state.clear()
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("del_channel:"))
async def confirm_delete_channel(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    channel_id_to_delete_str = callback.data.split(":", 1)[1]

    deleted = await delete_channel_from_db(channel_id_to_delete_str)

    if deleted:
        await callback.message.edit_text(f"🗑️ Kanal (<code>{channel_id_to_delete_str}</code>) üstünlikli pozuldy.", reply_markup=back_to_admin_markup)
        await callback.answer("Kanal pozuldy", show_alert=False)
    else:
        await callback.message.edit_text("⚠️ Kanal tapylmady ýa-da pozmakda ýalňyşlyk ýüze çykdy.", reply_markup=back_to_admin_markup)
        await callback.answer("Kanal tapylmady ýa-da ýalňyşlyk", show_alert=True)


@router.callback_query(lambda c: c.data == "add_addlist")
async def process_add_addlist_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    await callback.message.edit_text(
        "🔗 <b>addlist Goşmak (Addlist)</b> 🔗\n\n"
        "addlistnyň URL-ni giriziň (meselem, <code>https://t.me/addlist/xxxxxx</code>).\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")]])
    )
    await state.update_data(admin_message_id=callback.message.message_id, admin_chat_id=callback.message.chat.id)
    await state.set_state(AdminStates.waiting_for_addlist_url)
    await callback.answer()


@router.message(AdminStates.waiting_for_addlist_url)
async def process_addlist_url(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    addlist_url = message.text.strip()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    original_prompt_url = "🔗 <b>addlist Goşmak: URL</b> 🔗\n\naddlistnyň URL-ni giriziň (<code>https://t.me/addlist/xxxx</code>)."
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not admin_message_id or not admin_chat_id:
        await bot.send_message(message.chat.id, "⚠️ Ýagdaý ýalňyşlygy. Täzeden synanyşyň.", reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    if not addlist_url.startswith("https://t.me/addlist/"):
        await bot.edit_message_text(
            f"⚠️ <b>Ýalňyşlyk:</b> URL <code>https://t.me/addlist/</code> bilen başlamaly.\n\n{original_prompt_url}",
            chat_id=admin_chat_id, message_id=admin_message_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row])
        )
        return

    addlists_in_db = await get_addlists_from_db()
    if any(al['url'] == addlist_url for al in addlists_in_db):
        await bot.edit_message_text(f"⚠️ Bu addlist (<code>{addlist_url}</code>) eýýäm goşulan.\n\n{original_prompt_url}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    await state.update_data(addlist_url=addlist_url)
    await bot.edit_message_text(
        "✏️ Indi bu addlist üçin <b>görkezilýän ady</b> giriziň (meselem, <i>Peýdaly Kanallar</i>):",
        chat_id=admin_chat_id, message_id=admin_message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row])
    )
    await state.set_state(AdminStates.waiting_for_addlist_name)


@router.message(AdminStates.waiting_for_addlist_name)
async def save_addlist_name(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    addlist_name = message.text.strip()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    addlist_url = fsm_data.get('addlist_url')
    original_prompt_name = "✏️ addlist üçin <b>görkezilýän ady</b> giriziň (meselem, <i>Peýdaly Kanallar</i>):"
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not all([admin_message_id, admin_chat_id, addlist_url]):
        err_msg_text = "⚠️ Ýagdaý ýalňyşlygy (URL ýok). addlistny täzeden goşmagy synanyşyň."
        if admin_message_id and admin_chat_id:
             try:
                await bot.edit_message_text(err_msg_text, chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
             except TelegramBadRequest:
                await bot.send_message(admin_chat_id, err_msg_text, reply_markup=back_to_admin_markup)
        else:
            await bot.send_message(message.chat.id, err_msg_text, reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    if not addlist_name:
        await bot.edit_message_text(f"⚠️ addlist ady boş bolup bilmez.\n\n{original_prompt_name}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    success = await add_addlist_to_db(addlist_name, addlist_url)
    if success:
        await bot.edit_message_text(f"✅ <b>{addlist_name}</b> addlistsy (<code>{addlist_url}</code>) üstünlikli goşuldy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    else:
        await bot.edit_message_text(f"⚠️ <b>{addlist_name}</b> addlistsy (<code>{addlist_url}</code>) goşmak başartmady. Mümkin, ol eýýäm bar ýa-da maglumatlar bazasynda ýalňyşlyk boldy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()


@router.callback_query(lambda c: c.data == "delete_addlist")
async def process_delete_addlist_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return

    addlists = await get_addlists_from_db()

    if not addlists:
        await callback.message.edit_text("🗑️ addlistlaryň (Addlists) sanawy boş. Pozmak üçin hiç zat ýok.", reply_markup=back_to_admin_markup)
        await callback.answer()
        return

    keyboard_buttons = [
        [InlineKeyboardButton(text=f"{al['name']} ({al['url'][:30]}...)", callback_data=f"del_addlist_id:{al['db_id']}")]
        for al in addlists
    ]
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")])

    await callback.message.edit_text("🔪 <b>addlist Pozmak (Addlist)</b> 🔪\n\nPozmak üçin addlist saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("del_addlist_id:"))
async def confirm_delete_addlist(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return

    try:
        addlist_db_id_to_delete = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.message.edit_text("⚠️ Ýalňyşlyk: Nädogry addlist ID-si.", reply_markup=back_to_admin_markup)
        await callback.answer("ID ýalňyşlygy", show_alert=True)
        return

    addlists = await get_addlists_from_db()
    addlist_to_delete = next((al for al in addlists if al['db_id'] == addlist_db_id_to_delete), None)

    if addlist_to_delete:
        deleted = await delete_addlist_from_db(addlist_db_id_to_delete)
        if deleted:
            await callback.message.edit_text(f"🗑️ <b>{addlist_to_delete['name']}</b> addlistsy üstünlikli pozuldy.", reply_markup=back_to_admin_markup)
            await callback.answer("addlist pozuldy", show_alert=False)
        else:
            await callback.message.edit_text("⚠️ addlistny maglumatlar bazasyndan pozmakda ýalňyşlyk.", reply_markup=back_to_admin_markup)
            await callback.answer("Pozmak ýalňyşlygy", show_alert=True)
    else:
        await callback.message.edit_text("⚠ addlist tapylmady ýa-da eýýäm pozuldy.", reply_markup=back_to_admin_markup)
        await callback.answer("addlist tapylmady", show_alert=True)

@router.callback_query(lambda c: c.data == "add_vpn_config")
async def process_add_vpn_config_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    await callback.message.edit_text(
        "🔑 <b>VPN Kody Goşmak</b> 🔑\n\n"
        "VPN <b>kodyny</b> iberiň. Ol bolşy ýaly saklanar we ulanyja <code>Şeýle görnuşde</code> berler.\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")]])
    )
    await state.update_data(admin_message_id=callback.message.message_id, admin_chat_id=callback.message.chat.id)
    await state.set_state(AdminStates.waiting_for_vpn_config)
    await callback.answer()


@router.message(AdminStates.waiting_for_vpn_config)
async def save_vpn_config(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    vpn_config_text = message.text.strip()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    original_prompt_vpn = "🔑 <b>VPN kodyny Goşmak: Kodyň Teksti</b> 🔑\n\nVPN kodyny iberiň."
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not admin_message_id or not admin_chat_id:
        await bot.send_message(message.chat.id, "⚠️ Ýagdaý ýalňyşlygy. Täzeden synanyşyň.", reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    if not vpn_config_text:
        await bot.edit_message_text(f"⚠️ VPN kody boş bolup bilmez.\n\n{original_prompt_vpn}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    success = await add_vpn_config_to_db(vpn_config_text)
    if success:
        await bot.edit_message_text("✅ VPN kody üstünlikli goşuldy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    else:
        await bot.edit_message_text("⚠️ VPN kodyny goşmak başartmady. Mümkin, ol eýýäm bar ýa-da maglumatlar bazasynda ýalňyşlyk boldy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()

@router.callback_query(lambda c: c.data == "delete_vpn_config")
async def process_delete_vpn_config_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return

    vpn_configs = await get_vpn_configs_from_db()

    if not vpn_configs:
        await callback.message.edit_text("🗑️ VPN kody sanawy boş. Pozmak üçin hiç zat ýok.", reply_markup=back_to_admin_markup)
        await callback.answer()
        return

    keyboard_buttons = [
        [InlineKeyboardButton(text=f"Konfig #{i+1} ({item['config_text'][:25]}...)", callback_data=f"del_vpn_id:{item['db_id']}")]
        for i, item in enumerate(vpn_configs)
    ]
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")])

    await callback.message.edit_text("🔪 <b>VPN Kodyny Pozmak</b> 🔪\n\nPozmak üçin kody saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("del_vpn_id:"))
async def confirm_delete_vpn_config(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return

    try:
        config_db_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.message.edit_text("⚠️ Ýalňyşlyk: Nädogry kod ID-si.", reply_markup=back_to_admin_markup)
        await callback.answer("ID ýalňyşlygy", show_alert=True)
        return

    all_configs = await get_vpn_configs_from_db()
    config_to_delete = next((c for c in all_configs if c['db_id'] == config_db_id), None)

    deleted = await delete_vpn_config_from_db(config_db_id)
    if deleted:
        preview = f"({config_to_delete['config_text'][:20]}...)" if config_to_delete else ""
        await callback.message.edit_text(f"🗑️ VPN kody {preview} üstünlikli pozuldy.", reply_markup=back_to_admin_markup)
        await callback.answer("VPN Kody pozuldy", show_alert=False)
    else:
        await callback.message.edit_text("⚠️ Kod tapylmady, eýýäm pozuldy ýa-da maglumatlar bazasynda ýalňyşlyk boldy.", reply_markup=back_to_admin_markup)
        await callback.answer("Kod tapylmady/ýalňyşlyk", show_alert=True)

@router.callback_query(lambda c: c.data == "change_welcome")
async def process_change_welcome_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return

    current_welcome = await get_setting_from_db("welcome_message", "<i>Häzirki Başlangyç haty ýok.</i>")
    await callback.message.edit_text(
        f"📝 <b>Başlangyç hatyny Üýtgetmek</b> 📝\n\n"
        f"Häzirki başlangyç haty:\n"
        f"<blockquote>{current_welcome}</blockquote>\n"
        f"Täze başlangyç hatyny giriziň."
        f"Formatlamak üçin HTML teglerini ulanyp bilersiňiz (meselem, <b>galyň</b>, <i>kursiw</i>, <a href='https://example.com'>salgy</a>, <code>kod</code>).\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")]])
    )
    await state.update_data(admin_message_id=callback.message.message_id, admin_chat_id=callback.message.chat.id)
    await state.set_state(AdminStates.waiting_for_welcome_message)
    await callback.answer()


@router.message(AdminStates.waiting_for_welcome_message)
async def save_welcome_message(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    new_welcome_message = message.html_text
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not admin_message_id or not admin_chat_id:
        await bot.send_message(message.chat.id, "⚠️ Ýagdaý ýalňyşlygy. Täzeden synanyşyň.", reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    if not new_welcome_message or not new_welcome_message.strip():
        current_welcome = await get_setting_from_db("welcome_message", "<i>başlangyç haty ýok.</i>")
        await bot.edit_message_text(
            f"⚠️ <b>Ýalňyşlyk:</b> Başlangyç haty boş bolup bilmez.\n"
            f"Häzirki Başlangyç haty:\n<blockquote>{current_welcome}</blockquote>\n\n"
            f"Täze başlangyç hatyny giriziň ýa-da amaly ýatyryň.",
            chat_id=admin_chat_id, message_id=admin_message_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]),
        )
        return

    await save_setting_to_db('welcome_message', new_welcome_message)
    await bot.edit_message_text("✅ Başlangyç hat üstünlikli täzelendi!", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()


@router.callback_query(lambda c: c.data == "add_admin")
async def add_admin_prompt(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer("⛔ Bu funksiýa diňe baş admin üçin elýeterlidir.", show_alert=True)
        return
    await callback.message.edit_text(
        "👮 <b>Admin Goşmak</b> 👮\n\n"
        "Admin bellemek isleýän ulanyjyňyzyň Telegram User ID-sini giriziň.\n"
        "<i>User ID-ni @userinfobot ýa-da @getmyid_bot ýaly botlardan bilip bilersiňiz.</i>\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")]])
    )
    await state.update_data(admin_message_id=callback.message.message_id, admin_chat_id=callback.message.chat.id)
    await state.set_state(AdminStates.waiting_for_admin_id_to_add)
    await callback.answer()


@router.message(AdminStates.waiting_for_admin_id_to_add)
async def process_add_admin_id(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID: return
    new_admin_id_str = message.text.strip()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    original_prompt_admin_id = (
        "👮 <b>Admin Goşmak: User ID</b> 👮\n\n"
        "Telegram User ID-ni (san) giriziň.\n"
        "<i>User ID-ni @userinfobot ýaly botlardan bilip bilersiňiz.</i>"
    )
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not admin_message_id or not admin_chat_id:
        await bot.send_message(message.chat.id, "⚠️ Ýagdaý ýalňyşlygy. Täzeden synanyşyň.", reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    try:
        new_admin_id = int(new_admin_id_str)
    except ValueError:
        await bot.edit_message_text(f"⚠️ <b>Ýalňyşlyk:</b> User ID san bolmaly.\n\n{original_prompt_admin_id}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    if new_admin_id == SUPER_ADMIN_ID:
        await bot.edit_message_text(f"⚠️ Baş admin eýýäm ähli hukuklara eýe.\n\n{original_prompt_admin_id}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    current_admins = await get_admins_from_db()
    if new_admin_id in current_admins:
        await bot.edit_message_text(f"⚠️ <code>{new_admin_id}</code> ID-li ulanyjy eýýäm admin.\n\n{original_prompt_admin_id}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    success = await add_admin_to_db(new_admin_id)
    if success:
        await bot.edit_message_text(f"✅ <code>{new_admin_id}</code> ID-li ulanyjy üstünlikli admin bellenildi!", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    else:
        await bot.edit_message_text(f"⚠️ <code>{new_admin_id}</code> ID-li admini goşmak başartmady. Maglumatlar bazasy ýalňyşlygy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()


@router.callback_query(lambda c: c.data == "delete_admin")
async def delete_admin_prompt(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer("⛔ Bu funksiýa diňe baş admin üçin elýeterlidir.", show_alert=True)
        return

    admins_in_db = await get_admins_from_db()

    if not admins_in_db:
        await callback.message.edit_text("🚫 Goşmaça adminleriň sanawy boş. Pozmak üçin hiç kim ýok.", reply_markup=back_to_admin_markup)
        await callback.answer()
        return

    keyboard_buttons = []
    for admin_id in admins_in_db:
        try:
            user = await bot.get_chat(admin_id)
            display_name = f"{user.full_name} ({admin_id})"
        except Exception:
            display_name = f"Admin ({admin_id}) - ady alynmady"
        keyboard_buttons.append([InlineKeyboardButton(text=display_name, callback_data=f"del_admin_id:{admin_id}")])

    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")])
    await callback.message.edit_text("🔪 <b>Admin Pozmak</b> 🔪\n\nHukuklaryny yzyna almak üçin admini saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("del_admin_id:"))
async def confirm_delete_admin(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer("⛔ Bu funksiýa diňe baş admin üçin elýeterlidir.", show_alert=True)
        return

    try:
        admin_id_to_delete = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.message.edit_text("⚠️ Ýalňyşlyk: Pozmak üçin nädogry admin ID-si.", reply_markup=back_to_admin_markup)
        await callback.answer("ID ýalňyşlygy", show_alert=True)
        return

    deleted = await delete_admin_from_db(admin_id_to_delete)
    if deleted:
        await callback.message.edit_text(f"🗑️ <code>{admin_id_to_delete}</code> ID-li admin üstünlikli pozuldy.", reply_markup=back_to_admin_markup)
        await callback.answer("Admin pozuldy", show_alert=False)
    else:
        await callback.message.edit_text("⚠️ Admin tapylmady, eýýäm pozuldy ýa-da maglumatlar bazasy ýalňyşlygy.", reply_markup=back_to_admin_markup)
        await callback.answer("Admin tapylmady/ýalňyşlyk", show_alert=True)


@router.callback_query(lambda c: c.data == "check_subscription")
async def process_check_subscription(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    vpn_configs_full = await get_vpn_configs_from_db()
    vpn_configs_texts = [item['config_text'] for item in vpn_configs_full]

    if not vpn_configs_texts:
        try:
            await callback.message.edit_text("😔 Gynansak-da, häzirki wagtda elýeterli VPN kody ýok. Haýyş edýäris, soňrak synanyşyň.")
        except TelegramBadRequest:
            await callback.answer(text="😔 Elýeterli VPN kody ýok. Soňrak synanyşyň.", show_alert=True)
        await state.clear()
        return

    user_still_needs_to_subscribe = await has_unsubscribed_channels(user_id)
    channels_configured = bool(await get_channels_from_db())

    if not user_still_needs_to_subscribe:
        vpn_config_text = random.choice(vpn_configs_texts)
        text = "🎉 Siz ähli kanallara agza bolduňyz." if channels_configured else "✨ Agza bolanyňyz üçin sagboluň"
        try:
            await callback.message.edit_text(
                f"{text}\n\n"
                f"🔑 <b>Siziň VPN koduňyz:</b>\n<pre><code>{vpn_config_text}</code></pre>",
                reply_markup=None
            )
            await callback.answer(text="✅ Agzalyk barlandy!", show_alert=False)
        except TelegramBadRequest:
             await callback.answer(text="✅ Agzalyk barlandy!", show_alert=False)
        await state.clear()
    else:
        new_keyboard = await create_subscription_task_keyboard(user_id)
        welcome_text_db = await get_setting_from_db('welcome_message', "👋 VPN kodyny almak üçin, aşakdaky kanallara agza boluň:")

        message_needs_update = False
        if callback.message:
            if (callback.message.html_text != welcome_text_db) or \
               (new_keyboard != callback.message.reply_markup):
                 message_needs_update = True

            if message_needs_update:
                try:
                    await callback.message.edit_text(welcome_text_db, reply_markup=new_keyboard)
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e).lower():
                        pass
                    else:
                        logging.error(f"agzalygy barlanda habary redaktirlemekde ýalňyşlyk: {e}")
        await callback.answer(
            text="⚠️ Haýyş edýäris, ähli görkezilen kanallara agza boluň we täzeden synanşyň",
            show_alert=True
        )

async def main():
    global DB_POOL
    try:
        DB_POOL = await asyncpg.create_pool(dsn=DATABASE_URL)
        if DB_POOL:
            logging.info("Successfully connected to PostgreSQL and connection pool created.")
            await init_db(DB_POOL)
            logging.info("Database initialized (tables created if they didn't exist).")
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
])

class SubscriptionStates(StatesGroup):
    checking_subscription = State()

class AdminStates(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_name = State()
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
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id SERIAL PRIMARY KEY,
                channel_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL
            );
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS addlists (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL
            );
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS vpn_configs (
                id SERIAL PRIMARY KEY,
                config_text TEXT UNIQUE NOT NULL
            );
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id BIGINT PRIMARY KEY
            );
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id BIGINT PRIMARY KEY
            );
        """)
        default_welcome = "👋 <b>Hoş geldiňiz!</b>\n\nVPN Koduny almak üçin, aşakdaky Kanallara Agza boluň we soňra Agza boldum düwmesine basyň."
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
    """Сохраняет контент и клавиатуру последней рассылки."""
    content_json = json.dumps(content)
    await save_setting_to_db(f'last_{mail_type}_mail_content', content_json)
    
    if keyboard:
        keyboard_json = json.dumps(keyboard.dict())
        await save_setting_to_db(f'last_{mail_type}_mail_keyboard', keyboard_json)
    else:
        await save_setting_to_db(f'last_{mail_type}_mail_keyboard', 'null')

async def get_last_mail_content(mail_type: str) -> tuple[dict | None, InlineKeyboardMarkup | None]:
    """Загружает контент и клавиатуру последней рассылки."""
    content = None
    keyboard = None
    
    content_json = await get_setting_from_db(f'last_{mail_type}_mail_content')
    if content_json:
        content = json.loads(content_json)
        
    keyboard_json = await get_setting_from_db(f'last_{mail_type}_mail_keyboard')
    if keyboard_json and keyboard_json != 'null':
        keyboard_data = json.loads(keyboard_json)
        keyboard = InlineKeyboardMarkup.model_validate(keyboard_data)
        
    return content, keyboard

async def send_mail_preview(chat_id: int, content: dict, keyboard: InlineKeyboardMarkup | None = None):
    """Отправляет предпросмотр сообщения (текст или медиа)."""
    content_type = content.get('type')
    caption = content.get('caption')
    text = content.get('text')
    file_id = content.get('file_id')

    if content_type == 'text':
        return await bot.send_message(chat_id, text, reply_markup=keyboard)
    elif content_type == 'photo':
        return await bot.send_photo(chat_id, file_id, caption=caption, reply_markup=keyboard)
    elif content_type == 'video':
        return await bot.send_video(chat_id, file_id, caption=caption, reply_markup=keyboard)
    elif content_type == 'animation':
        return await bot.send_animation(chat_id, file_id, caption=caption, reply_markup=keyboard)


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
        try:
            await conn.execute("INSERT INTO bot_users (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", user_id)
        except Exception as e:
            logging.error(f"Error adding user {user_id} to DB: {e}")


async def get_admins_from_db():
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM bot_admins")
        return [row['user_id'] for row in rows]

async def add_admin_to_db(user_id: int):
    async with DB_POOL.acquire() as conn:
        try:
            await conn.execute("INSERT INTO bot_admins (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", user_id)
            return True
        except Exception as e:
            logging.error(f"Error adding admin {user_id} to DB: {e}")
            return False

async def delete_admin_from_db(user_id: int):
    async with DB_POOL.acquire() as conn:
        result = await conn.execute("DELETE FROM bot_admins WHERE user_id = $1", user_id)
        return result != "DELETE 0"

async def is_user_admin_in_db(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True
    admins = await get_admins_from_db()
    return user_id in admins

async def create_subscription_task_keyboard(user_id: int) -> InlineKeyboardMarkup:
    channels = await get_channels_from_db()
    addlists = await get_addlists_from_db()
    keyboard_buttons = []

    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel['id'], user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator', 'restricted'] or \
               (member.status == 'restricted' and hasattr(member, 'is_member') and not member.is_member):
                keyboard_buttons.append([
                    InlineKeyboardButton(text=f"{channel['name']}", url=f"https://t.me/{str(channel['id']).lstrip('@')}")
                ])
        except Exception as e:
            logging.error(f"Kanala agzalygy barlamakda ýalňyşlyk {channel['id']} ulanyjy {user_id} üçin: {e}")
            keyboard_buttons.append([
                InlineKeyboardButton(text=f"⚠️ {channel['name']} (barlag ýalňyşlygy)", url=f"https://t.me/{str(channel['id']).lstrip('@')}")
            ])
            continue
    for addlist in addlists:
        keyboard_buttons.append([
            InlineKeyboardButton(text=f"{addlist['name']}", url=addlist['url'])
        ])
    if keyboard_buttons:
        keyboard_buttons.append([
            InlineKeyboardButton(text="✅ Agza Boldum", callback_data="check_subscription")
        ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

async def has_unsubscribed_channels(user_id: int) -> bool:
    channels = await get_channels_from_db()
    if not channels:
        return False
    for channel in channels:
        try:
            chat_identifier = channel['id']
            if not (isinstance(chat_identifier, str) and chat_identifier.startswith('@')):
                try:
                    chat_identifier = int(str(chat_identifier))
                except ValueError:
                    logging.error(f"get_chat_member üçin nädogry kanal ID formaty: {channel['id']}. Geçirilýär.")
                    return True
            member = await bot.get_chat_member(chat_id=chat_identifier, user_id=user_id)
            if member.status == 'restricted':
                if hasattr(member, 'is_member') and not member.is_member:
                    logging.info(f"Ulanyjy {user_id} {channel['id']} kanala AGZA BOLMADYK (ýagdaýy: {member.status}, is_member=False)")
                    return True
            elif member.status not in ['member', 'administrator', 'creator']:
                logging.info(f"Ulanyjy {user_id} {channel['id']} kanala AGZA BOLMADYK (ýagdaýy: {member.status})")
                return True
        except TelegramForbiddenError:
            logging.error(f"TelegramForbiddenError: Bot {channel['id']} kanalyň adminy däl. Howpsuzlyk üçin ulanyjy agza bolmadyk hasaplanýar.")
            return True
        except TelegramBadRequest as e:
            logging.warning(f"Ulanyjy {user_id}-iň {channel['id']} kanala agzalygy barlanda TelegramBadRequest: {e}. Ulanyjy agza bolmadyk hasaplanýar.")
            return True
        except Exception as e:
            logging.warning(f"Ulanyjy {user_id}-iň {channel['id']} kanala agzalygyny barlanda umumy ýalňyşlyk: {e}. Ulanyjy Agza bolmadyk hasaplanýar.")
            return True
    return False

def create_admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Bot statistikasy", callback_data="get_stats")],
        [InlineKeyboardButton(text="🚀 Ulanyjylara ibermek", callback_data="start_mailing"),
         InlineKeyboardButton(text="📢 Kanallara ibermek", callback_data="start_channel_mailing")],
        [InlineKeyboardButton(text="➕ Kanal goşmak", callback_data="add_channel"), InlineKeyboardButton(text="➖ Kanal pozmak", callback_data="delete_channel")],
        [InlineKeyboardButton(text="📁 addlist goşmak", callback_data="add_addlist"), InlineKeyboardButton(text="🗑️ addlist pozmak", callback_data="delete_addlist")],
        [InlineKeyboardButton(text="🔑 VPN goşmak", callback_data="add_vpn_config"), InlineKeyboardButton(text="🗑️ VPN pozmak", callback_data="delete_vpn_config")],
        [InlineKeyboardButton(text="✏️ Başlangyç haty üýtgetmek", callback_data="change_welcome")]
    ]
    if user_id == SUPER_ADMIN_ID:
        buttons.extend([
            [InlineKeyboardButton(text="👮 Admin goşmak", callback_data="add_admin"), InlineKeyboardButton(text="🚫 Admin pozmak", callback_data="delete_admin")]
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ Admin panelden çykmak", callback_data="exit_admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await add_user_to_db(user_id)

    vpn_configs_full = await get_vpn_configs_from_db()
    vpn_configs = [item['config_text'] for item in vpn_configs_full]

    if not vpn_configs:
        await message.answer("😔 Gynansak-da, häzirki wagtda elýeterli VPN Kodlary ýok. Haýyş edýäris, soňrak synanyşyň.")
        await state.clear()
        return

    user_needs_to_subscribe_to_channels = await has_unsubscribed_channels(user_id)
    channels_exist = bool(await get_channels_from_db())

    if not user_needs_to_subscribe_to_channels:
        vpn_config_text = random.choice(vpn_configs)
        text = "🎉 Siz ähli kanallara Agza boldyňyz! " if channels_exist else "✨ Agza bolanyňyzüçin sagboluň!"
        await message.answer(
            f"{text}\n\n"
            f"🔑 <b>siziň VPN Kodyňyz:</b>\n<pre><code>{vpn_config_text}</code></pre>"
        )
        await state.clear()
    else:
        keyboard = await create_subscription_task_keyboard(user_id)
        welcome_text = await get_setting_from_db('welcome_message', "👋 <b>Hoş geldiňiz!</b>\n\nVPN almak üçin, aşakdaky Kanallara agza boluň we 'Agza boldum' düwmesine basyň.")
        if not keyboard.inline_keyboard:
            if vpn_configs:
                 vpn_config_text = random.choice(vpn_configs)
                 await message.answer(f"✨ Agza bolanyňyz üçin sagboluň!\n\n🔑 <b>Siziň VPN Kodyňyz:</b>\n<pre><code>{vpn_config_text}</code></pre>")
            else:
                 await message.answer("😔 Häzirki wagtda elýeterli VPN kodlary ýok.")
            await state.clear()
        else:
            await message.answer(welcome_text, reply_markup=keyboard)
            await state.set_state(SubscriptionStates.checking_subscription)

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
        await callback.message.edit_text(
            "✅ Siz admin panelden çykdyňyz.\n\nAdaty ulanyjy hökmünde täzeden işe başlamak üçin /start giriziň",
            reply_markup=None
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "✅ Siz admin panelden çykdyňyz.\n\nAdaty ulanyjy hökmünde täzeden işe başlamak üçin /start giriziň",
            reply_markup=None
        )
    await callback.answer()

@router.callback_query(lambda c: c.data == "get_stats")
async def get_statistics(callback: types.CallbackQuery):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    
    async with DB_POOL.acquire() as conn:
        user_count = await conn.fetchval("SELECT COUNT(*) FROM bot_users")
        channel_count = await conn.fetchval("SELECT COUNT(*) FROM channels")
        addlist_count = await conn.fetchval("SELECT COUNT(*) FROM addlists")
        vpn_count = await conn.fetchval("SELECT COUNT(*) FROM vpn_configs")
        admin_count = await conn.fetchval("SELECT COUNT(*) FROM bot_admins")

    status_description = "Bot işleýär" if vpn_count > 0 else "VPN KODLARY ÝOK!"
    alert_text = (
        f"📊 Bot statistikasy:\n"
        f"👤 Ulanyjylar: {user_count}\n"
        f"📢 Kanallar: {channel_count}\n"
        f"📁 addlistlar: {addlist_count}\n"
        f"🔑 VPN Kodlary: {vpn_count}\n"
        f"👮 Adminler (goşm.): {admin_count}\n"
        f"⚙️ Ýagdaýy: {status_description}"
    )
    try:
        await callback.answer(text=alert_text, show_alert=True)
    except Exception as e:
        logging.error(f"Statistikany duýduryşda görkezmekde ýalňyşlyk: {e}")
        await callback.answer("⚠️ Statistika görkezmekde ýalňyşlyk.", show_alert=True)


def parse_buttons_from_text(text: str) -> types.InlineKeyboardMarkup | None:
    lines = text.strip().split('\n')
    keyboard_buttons = []
    for line in lines:
        if ' - ' not in line:
            continue
        parts = line.split(' - ', 1)
        btn_text = parts[0].strip()
        btn_url = parts[1].strip()
        if btn_text and (btn_url.startswith('https://') or btn_url.startswith('http://')):
            keyboard_buttons.append([types.InlineKeyboardButton(text=btn_text, url=btn_url)])
    if not keyboard_buttons:
        return None
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

async def process_mailing_content(message: Message, state: FSMContext, mail_type: str):
    """
    Универсальный обработчик контента для рассылки.
    Принимает текст, фото, видео, GIF.
    """
    content = {}
    if message.photo:
        content = {
            'type': 'photo',
            'file_id': message.photo[-1].file_id,
            'caption': message.caption
        }
    elif message.video:
        content = {
            'type': 'video',
            'file_id': message.video.file_id,
            'caption': message.caption
        }
    elif message.animation:
        content = {
            'type': 'animation',
            'file_id': message.animation.file_id,
            'caption': message.caption
        }
    elif message.text:
        content = {
            'type': 'text',
            'text': message.html_text
        }
    else:
        await message.answer("⚠️ Bu habar görnüşi goldanmaýar. Tekst, surat, wideo ýa-da GIF iberiň.")
        return

    await state.update_data(mailing_content=content)
    
    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = message.chat.id

    try:
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

    if mail_type == "user":
        await state.set_state(AdminStates.waiting_for_mailing_confirmation)
    else:
        await state.set_state(AdminStates.waiting_for_channel_mailing_confirmation)


async def execute_user_broadcast(admin_message: types.Message, mailing_content: dict, mailing_keyboard: types.InlineKeyboardMarkup | None):
    users_to_mail = await get_users_from_db()
    
    if not users_to_mail:
        await admin_message.edit_text("👥 Ibermek üçin ulanyjylar ýok.", reply_markup=back_to_admin_markup)
        return

    await admin_message.edit_text(f"⏳ <b>{len(users_to_mail)}</b> sany ulanyja ibermek başlanýar...", reply_markup=None)

    success_count = 0
    fail_count = 0
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


@router.callback_query(lambda c: c.data == "start_mailing")
async def start_mailing_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id): return
    
    last_content, _ = await get_last_mail_content("user")
    
    keyboard_buttons = [[InlineKeyboardButton(text="➕ Täze habar döretmek", callback_data="create_new_user_mail")]]
    if last_content:
        keyboard_buttons.insert(0, [InlineKeyboardButton(text="🔄 Soňky habary ulanmak", callback_data="repeat_last_user_mail")])
    
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Yza", callback_data="admin_panel_main")])
    
    await callback.message.edit_text(
        "📬 <b>Ulanyjylara Iberiş</b> 📬\n\nBir hereket saýlaň:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    )
    await state.set_state(AdminStates.waiting_for_user_mail_action)
    await callback.answer()


@router.callback_query(AdminStates.waiting_for_user_mail_action)
async def process_user_mail_action(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data
    if action == "create_new_user_mail":
        await callback.message.edit_text(
            "✍️ Ibermek isleýän habaryňyzy (tekst, surat, wideo ýa-da GIF) iberiň.",
            reply_markup=back_to_admin_markup
        )
        await state.update_data(admin_message_id=callback.message.message_id)
        await state.set_state(AdminStates.waiting_for_mailing_message)
    elif action == "repeat_last_user_mail":
        content, keyboard = await get_last_mail_content("user")
        if not content:
            await callback.answer("⚠️ Soňky habar tapylmady.", show_alert=True)
            return

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


@router.message(AdminStates.waiting_for_mailing_message, F.content_type.in_({'text', 'photo', 'video', 'animation'}))
async def process_user_mailing_message(message: Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    await process_mailing_content(message, state, "user")


@router.callback_query(AdminStates.waiting_for_mailing_confirmation)
async def process_user_mailing_confirmation(callback: types.CallbackQuery, state: FSMContext):
    fsm_data = await state.get_data()
    mailing_content = fsm_data.get('mailing_content')
    mailing_keyboard = fsm_data.get('mailing_keyboard')
    
    try:
        await bot.delete_message(callback.from_user.id, fsm_data.get('admin_message_id'))
        await bot.delete_message(callback.from_user.id, fsm_data.get('preview_message_id'))
    except (TelegramBadRequest, KeyError): pass

    if not mailing_content:
        await bot.send_message(callback.from_user.id, "⚠️ Ýalňyşlyk: habar tapylmady.", reply_markup=back_to_admin_markup)
        await state.clear()
        return

    if callback.data in ["user_mail_confirm_send", "user_mail_confirm_send_repeated"]:
        msg_for_broadcast = await bot.send_message(callback.from_user.id, "⏳...")
        await execute_user_broadcast(msg_for_broadcast, mailing_content, mailing_keyboard)
        await state.clear()
    elif callback.data == "user_mail_confirm_add_buttons":
        msg = await bot.send_message(
            callback.from_user.id,
            "🔗 <b>Düwmeleri goşmak</b> 🔗\n\nFormat: <code>Tekst - https://salgy.com</code>\nHer düwme täze setirde.",
            reply_markup=back_to_admin_markup
        )
        await state.update_data(admin_message_id=msg.message_id)
        await state.set_state(AdminStates.waiting_for_mailing_buttons)
    await callback.answer()


@router.message(AdminStates.waiting_for_mailing_buttons)
async def process_user_mailing_buttons(message: Message, state: FSMContext):
    keyboard = parse_buttons_from_text(message.text)
    if not keyboard:
        await message.answer("⚠️ Nädogry format! Täzeden synanyşyň.")
        return
    
    await message.delete()
    fsm_data = await state.get_data()
    mailing_content = fsm_data.get('mailing_content')
    
    try: await bot.delete_message(message.chat.id, fsm_data.get('admin_message_id'))
    except (TelegramBadRequest, KeyError): pass

    msg_for_broadcast = await bot.send_message(message.chat.id, "⏳...")
    await execute_user_broadcast(msg_for_broadcast, mailing_content, keyboard)
    await state.clear()


async def execute_channel_broadcast(admin_message: types.Message, mailing_content: dict, mailing_keyboard: types.InlineKeyboardMarkup | None):
    channels_to_mail = await get_channels_from_db()
    if not channels_to_mail:
        await admin_message.edit_text("📢 Ibermek üçin kanallar ýok.", reply_markup=back_to_admin_markup)
        return

    await admin_message.edit_text(f"⏳ <b>{len(channels_to_mail)}</b> sany kanala ibermek başlanýar...", reply_markup=None)

    success_count = 0
    fail_count = 0
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

    await callback.message.edit_text(
        "📢 <b>Kanallara Iberiş</b> 📢\n\nBir hereket saýlaň:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    )
    await state.set_state(AdminStates.waiting_for_channel_mail_action)
    await callback.answer()


@router.callback_query(AdminStates.waiting_for_channel_mail_action)
async def process_channel_mail_action(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data
    if action == "create_new_channel_mail":
        await callback.message.edit_text(
            "✍️ Ibermek isleýän habaryňyzy (tekst, surat, wideo ýa-da GIF) iberiň.",
            reply_markup=back_to_admin_markup
        )
        await state.update_data(admin_message_id=callback.message.message_id)
        await state.set_state(AdminStates.waiting_for_channel_mailing_message)
    elif action == "repeat_last_channel_mail":
        content, keyboard = await get_last_mail_content("channel")
        if not content:
            await callback.answer("⚠️ Soňky habar tapylmady.", show_alert=True)
            return

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


@router.message(AdminStates.waiting_for_channel_mailing_message, F.content_type.in_({'text', 'photo', 'video', 'animation'}))
async def process_channel_mailing_message(message: Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    await process_mailing_content(message, state, "channel")


@router.callback_query(AdminStates.waiting_for_channel_mailing_confirmation)
async def process_channel_mailing_confirmation(callback: types.CallbackQuery, state: FSMContext):
    fsm_data = await state.get_data()
    mailing_content = fsm_data.get('mailing_content')
    mailing_keyboard = fsm_data.get('mailing_keyboard')
    
    try:
        await bot.delete_message(callback.from_user.id, fsm_data.get('admin_message_id'))
        await bot.delete_message(callback.from_user.id, fsm_data.get('preview_message_id'))
    except (TelegramBadRequest, KeyError): pass

    if not mailing_content:
        await bot.send_message(callback.from_user.id, "⚠️ Ýalňyşlyk: habar tapylmady.", reply_markup=back_to_admin_markup)
        await state.clear()
        return

    if callback.data in ["channel_mail_confirm_send", "channel_mail_confirm_send_repeated"]:
        msg_for_broadcast = await bot.send_message(callback.from_user.id, "⏳...")
        await execute_channel_broadcast(msg_for_broadcast, mailing_content, mailing_keyboard)
        await state.clear()
    elif callback.data == "channel_mail_confirm_add_buttons":
        msg = await bot.send_message(
            callback.from_user.id,
            "🔗 <b>Düwmeleri goşmak</b> 🔗\n\nFormat: <code>Tekst - https://salgy.com</code>\nHer düwme täze setirde.",
            reply_markup=back_to_admin_markup
        )
        await state.update_data(admin_message_id=msg.message_id)
        await state.set_state(AdminStates.waiting_for_channel_mailing_buttons)
    await callback.answer()


@router.message(AdminStates.waiting_for_channel_mailing_buttons)
async def process_channel_mailing_buttons(message: Message, state: FSMContext):
    keyboard = parse_buttons_from_text(message.text)
    if not keyboard:
        await message.answer("⚠️ Nädogry format! Täzeden synanyşyň.")
        return
    
    await message.delete()
    fsm_data = await state.get_data()
    mailing_content = fsm_data.get('mailing_content')

    try: await bot.delete_message(message.chat.id, fsm_data.get('admin_message_id'))
    except (TelegramBadRequest, KeyError): pass
    
    msg_for_broadcast = await bot.send_message(message.chat.id, "⏳...")
    await execute_channel_broadcast(msg_for_broadcast, mailing_content, keyboard)
    await state.clear()


@router.callback_query(lambda c: c.data == "add_channel")
async def process_add_channel_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    await callback.message.edit_text(
        "📡 <b>Kanal Goşmak</b> 📡\n\n"
        "Kanalyň ID-sini giriziň (meselem, <code>@PublicChannel</code>) ýa-da şahsy kanalyň ID-sini (meselem, <code>-1001234567890</code>).\n\n"
        "<i>Bot, agzalar barada maglumat almak hukugy bilen kanala administrator hökmünde goşulmaly.</i>\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")]])
    )
    await state.update_data(admin_message_id=callback.message.message_id, admin_chat_id=callback.message.chat.id)
    await state.set_state(AdminStates.waiting_for_channel_id)
    await callback.answer()


@router.message(AdminStates.waiting_for_channel_id)
async def process_channel_id(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    channel_id_input = message.text.strip()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    original_prompt_id = (
        "📡 <b>Kanal Goşmak: ID</b> 📡\n\n"
        "Kanalyň ID-sini giriziň (<code>@PublicChannel</code> ýa-da <code>-100...</code>).\n"
        "<i>Bot kanalda administrator bolmaly.</i>"
    )
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not admin_message_id or not admin_chat_id:
        await bot.send_message(message.chat.id, "⚠️ Ýagdaý ýalňyşlygy. Admin panelden täzeden synanyşyň.", reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    if not (channel_id_input.startswith('@') or (channel_id_input.startswith('-100') and channel_id_input[1:].replace('-', '', 1).isdigit())):
        await bot.edit_message_text(
            f"⚠️ <b>Ýalňyşlyk:</b> Nädogry kanal ID formaty.\n\n{original_prompt_id}",
            chat_id=admin_chat_id, message_id=admin_message_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row])
        )
        return

    channels_in_db = await get_channels_from_db()
    if any(str(ch['id']) == str(channel_id_input) for ch in channels_in_db):
        await bot.edit_message_text(f"⚠️ Bu kanal (<code>{channel_id_input}</code>) eýýäm sanawda bar.\n\n{original_prompt_id}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    try:
        chat_to_check_str = channel_id_input
        chat_to_check = int(chat_to_check_str) if not chat_to_check_str.startswith('@') else chat_to_check_str
        
        bot_member = await bot.get_chat_member(chat_id=chat_to_check, user_id=bot.id)
        if bot_member.status not in ['administrator', 'creator']:
            await bot.edit_message_text(
                "⚠️ <b>Ýalňyşlyk:</b> Bot bu kanalyň administratory däl (ýa-da gatnaşyjylar barada maglumat almak hukugy ýok).\n"
                "Haýyş edýäris, boty kanala zerur hukuklar bilen administrator hökmünde goşuň we täzeden synanyşyň.",
                chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup
            )
            await state.clear()
            return
    except ValueError:
        await bot.edit_message_text(
            f"⚠️ <b>Ýalňyşlyk:</b> Şahsy kanalyň ID-si san bolmaly (meselem, <code>-1001234567890</code>).\n\n{original_prompt_id}",
            chat_id=admin_chat_id, message_id=admin_message_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row])
        )
        return
    except TelegramBadRequest as e:
        logging.error(f"TelegramBadRequest при проверке статуса бота в канале {channel_id_input}: {e}")
        error_detail = str(e)
        specific_guidance = ""
        if "member list is inaccessible" in error_detail.lower():
            specific_guidance = ("<b>Maslahat:</b> Botuň 'Çaty dolandyryp bilmek' ýa-da ş.m., gatnaşyjylaryň sanawyny almaga mümkinçilik berýän hukugynyň bardygyna göz ýetiriň. Käbir ýagdaýlarda, eger kanal çat bilen baglanyşykly bolsa, hukuklar miras alnyp bilner.")
        elif "chat not found" in error_detail.lower():
            specific_guidance = "<b>Maslahat:</b> Kanal ID-siniň dogry girizilendigine we kanalyň bardygyna göz ýetiriň. Jemgyýetçilik kanallary üçin @username, şahsy kanallar üçin bolsa sanly ID ( -100 bilen başlaýan) ulanyň."
        elif "bot is not a member of the channel" in error_detail.lower() or "user not found" in error_detail.lower():
             specific_guidance = "<b>Maslahat:</b> Bot görkezilen kanalyň agzasy däl. Haýyş edýäris, ilki boty kanala goşuň."
        await bot.edit_message_text(
            f"⚠️ <b>Botyň kanaldaky ýagdaýyny barlamakda ýalňyşlyk:</b>\n<code>{error_detail}</code>\n\n"
            f"{specific_guidance}\n\n"
            "ID-niň dogrudygyny, botyň kanala goşulandygyny we zerur administrator hukuklarynyň bardygyny barlaň.",
            chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup
        )
        await state.clear()
        return
    except Exception as e:
        logging.error(f"ýalňyşlyk {channel_id_input}: {e}")
        await bot.edit_message_text(
            f"⚠️ <b>Botyň kanaldaky ýagdaýyny barlamakda garaşylmadyk ýalňyşlyk:</b> <code>{e}</code>.\n"
            "ID-niň dogrudygyny, botyň kanala goşulandygyny we administrator hukuklarynyň bardygyny barlaň.",
            chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup
        )
        await state.clear()
        return

    await state.update_data(channel_id=channel_id_input)
    await bot.edit_message_text(
        "✏️ Indi bu kanal üçin <b>görkezilýän ady</b> giriziň (meselem, <i>TKM VPNLAR</i>):",
        chat_id=admin_chat_id, message_id=admin_message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row])
    )
    await state.set_state(AdminStates.waiting_for_channel_name)


@router.message(AdminStates.waiting_for_channel_name)
async def save_channel(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    channel_name = message.text.strip()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    channel_id_str = fsm_data.get('channel_id')
    original_prompt_name = "✏️ Kanal üçin <b>görkezilýän ady</b> giriziň (meselem, <i>Tehnologiýa Habarlary</i>):"
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not all([admin_message_id, admin_chat_id, channel_id_str]):
        err_msg_text = "⚠️ Ýagdaý ýalňyşlygy (zerur maglumatlar ýok). Kanaly täzeden goşmagy synanyşyň."
        if admin_message_id and admin_chat_id:
            try:
                await bot.edit_message_text(err_msg_text, chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
            except TelegramBadRequest:
                 await bot.send_message(admin_chat_id, err_msg_text, reply_markup=back_to_admin_markup)
        else:
            await bot.send_message(message.chat.id, err_msg_text, reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    if not channel_name:
        await bot.edit_message_text(f"⚠️ Kanal ady boş bolup bilmez.\n\n{original_prompt_name}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    success = await add_channel_to_db(channel_id_str, channel_name)
    if success:
        await bot.edit_message_text(f"✅ <b>{channel_name}</b> kanaly (<code>{channel_id_str}</code>) üstünlikli goşuldy!", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    else:
        await bot.edit_message_text(f"⚠️ <b>{channel_name}</b> kanalyny (<code>{channel_id_str}</code>) goşmak başartmady. Mümkin, ol eýýäm bar ýa-da maglumatlar bazasynda ýalňyşlyk boldy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()


@router.callback_query(lambda c: c.data == "delete_channel")
async def process_delete_channel_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    
    channels = await get_channels_from_db()

    if not channels:
        await callback.message.edit_text("🗑️ Kanallaryň sanawy boş. Pozmak üçin hiç zat ýok.", reply_markup=back_to_admin_markup)
        await callback.answer()
        return

    keyboard_buttons = [
        [InlineKeyboardButton(text=f"{channel['name']} ({channel['id']})", callback_data=f"del_channel:{channel['id']}")] for channel in channels
    ]
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")])

    await callback.message.edit_text("🔪 <b>Kanal Pozmak</b> 🔪\n\nSanawdan pozmak üçin kanaly saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))
    await callback.answer()


@router.callback_query(lambda c: c.data == "admin_panel_main")
async def back_to_admin_panel(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    
    admin_reply_markup = create_admin_keyboard(callback.from_user.id)
    try:
        await callback.message.edit_text(
            "⚙️ <b>Admin-panel</b>\n\nBir hereket saýlaň:",
            reply_markup=admin_reply_markup
        )
    except TelegramBadRequest:
        await callback.message.answer(
             "⚙️ <b>Admin-panel</b>\n\nBir hereket saýlaň:",
            reply_markup=admin_reply_markup
        )
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
    await state.clear()
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("del_channel:"))
async def confirm_delete_channel(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    channel_id_to_delete_str = callback.data.split(":", 1)[1]

    deleted = await delete_channel_from_db(channel_id_to_delete_str)

    if deleted:
        await callback.message.edit_text(f"🗑️ Kanal (<code>{channel_id_to_delete_str}</code>) üstünlikli pozuldy.", reply_markup=back_to_admin_markup)
        await callback.answer("Kanal pozuldy", show_alert=False)
    else:
        await callback.message.edit_text("⚠️ Kanal tapylmady ýa-da pozmakda ýalňyşlyk ýüze çykdy.", reply_markup=back_to_admin_markup)
        await callback.answer("Kanal tapylmady ýa-da ýalňyşlyk", show_alert=True)


@router.callback_query(lambda c: c.data == "add_addlist")
async def process_add_addlist_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    await callback.message.edit_text(
        "🔗 <b>addlist Goşmak (Addlist)</b> 🔗\n\n"
        "addlistnyň URL-ni giriziň (meselem, <code>https://t.me/addlist/xxxxxx</code>).\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")]])
    )
    await state.update_data(admin_message_id=callback.message.message_id, admin_chat_id=callback.message.chat.id)
    await state.set_state(AdminStates.waiting_for_addlist_url)
    await callback.answer()


@router.message(AdminStates.waiting_for_addlist_url)
async def process_addlist_url(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    addlist_url = message.text.strip()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    original_prompt_url = "🔗 <b>addlist Goşmak: URL</b> 🔗\n\naddlistnyň URL-ni giriziň (<code>https://t.me/addlist/xxxx</code>)."
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not admin_message_id or not admin_chat_id:
        await bot.send_message(message.chat.id, "⚠️ Ýagdaý ýalňyşlygy. Täzeden synanyşyň.", reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    if not addlist_url.startswith("https://t.me/addlist/"):
        await bot.edit_message_text(
            f"⚠️ <b>Ýalňyşlyk:</b> URL <code>https://t.me/addlist/</code> bilen başlamaly.\n\n{original_prompt_url}",
            chat_id=admin_chat_id, message_id=admin_message_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row])
        )
        return

    addlists_in_db = await get_addlists_from_db()
    if any(al['url'] == addlist_url for al in addlists_in_db):
        await bot.edit_message_text(f"⚠️ Bu addlist (<code>{addlist_url}</code>) eýýäm goşulan.\n\n{original_prompt_url}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    await state.update_data(addlist_url=addlist_url)
    await bot.edit_message_text(
        "✏️ Indi bu addlist üçin <b>görkezilýän ady</b> giriziň (meselem, <i>Peýdaly Kanallar</i>):",
        chat_id=admin_chat_id, message_id=admin_message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row])
    )
    await state.set_state(AdminStates.waiting_for_addlist_name)


@router.message(AdminStates.waiting_for_addlist_name)
async def save_addlist_name(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    addlist_name = message.text.strip()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    addlist_url = fsm_data.get('addlist_url')
    original_prompt_name = "✏️ addlist üçin <b>görkezilýän ady</b> giriziň (meselem, <i>Peýdaly Kanallar</i>):"
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not all([admin_message_id, admin_chat_id, addlist_url]):
        err_msg_text = "⚠️ Ýagdaý ýalňyşlygy (URL ýok). addlistny täzeden goşmagy synanyşyň."
        if admin_message_id and admin_chat_id:
             try:
                await bot.edit_message_text(err_msg_text, chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
             except TelegramBadRequest:
                await bot.send_message(admin_chat_id, err_msg_text, reply_markup=back_to_admin_markup)
        else:
            await bot.send_message(message.chat.id, err_msg_text, reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    if not addlist_name:
        await bot.edit_message_text(f"⚠️ addlist ady boş bolup bilmez.\n\n{original_prompt_name}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    success = await add_addlist_to_db(addlist_name, addlist_url)
    if success:
        await bot.edit_message_text(f"✅ <b>{addlist_name}</b> addlistsy (<code>{addlist_url}</code>) üstünlikli goşuldy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    else:
        await bot.edit_message_text(f"⚠️ <b>{addlist_name}</b> addlistsy (<code>{addlist_url}</code>) goşmak başartmady. Mümkin, ol eýýäm bar ýa-da maglumatlar bazasynda ýalňyşlyk boldy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()


@router.callback_query(lambda c: c.data == "delete_addlist")
async def process_delete_addlist_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    
    addlists = await get_addlists_from_db()

    if not addlists:
        await callback.message.edit_text("🗑️ addlistlaryň (Addlists) sanawy boş. Pozmak üçin hiç zat ýok.", reply_markup=back_to_admin_markup)
        await callback.answer()
        return

    keyboard_buttons = [
        [InlineKeyboardButton(text=f"{al['name']} ({al['url'][:30]}...)", callback_data=f"del_addlist_id:{al['db_id']}")]
        for al in addlists
    ]
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")])

    await callback.message.edit_text("🔪 <b>addlist Pozmak (Addlist)</b> 🔪\n\nPozmak üçin addlist saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("del_addlist_id:"))
async def confirm_delete_addlist(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    
    try:
        addlist_db_id_to_delete = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.message.edit_text("⚠️ Ýalňyşlyk: Nädogry addlist ID-si.", reply_markup=back_to_admin_markup)
        await callback.answer("ID ýalňyşlygy", show_alert=True)
        return

    addlists = await get_addlists_from_db()
    addlist_to_delete = next((al for al in addlists if al['db_id'] == addlist_db_id_to_delete), None)

    if addlist_to_delete:
        deleted = await delete_addlist_from_db(addlist_db_id_to_delete)
        if deleted:
            await callback.message.edit_text(f"🗑️ <b>{addlist_to_delete['name']}</b> addlistsy üstünlikli pozuldy.", reply_markup=back_to_admin_markup)
            await callback.answer("addlist pozuldy", show_alert=False)
        else:
            await callback.message.edit_text("⚠️ addlistny maglumatlar bazasyndan pozmakda ýalňyşlyk.", reply_markup=back_to_admin_markup)
            await callback.answer("Pozmak ýalňyşlygy", show_alert=True)
    else:
        await callback.message.edit_text("⚠ addlist tapylmady ýa-da eýýäm pozuldy.", reply_markup=back_to_admin_markup)
        await callback.answer("addlist tapylmady", show_alert=True)

@router.callback_query(lambda c: c.data == "add_vpn_config")
async def process_add_vpn_config_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    await callback.message.edit_text(
        "🔑 <b>VPN Kody Goşmak</b> 🔑\n\n"
        "VPN <b>kodyny</b> iberiň. Ol bolşy ýaly saklanar we ulanyja <code>Şeýle görnuşde</code> berler.\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")]])
    )
    await state.update_data(admin_message_id=callback.message.message_id, admin_chat_id=callback.message.chat.id)
    await state.set_state(AdminStates.waiting_for_vpn_config)
    await callback.answer()


@router.message(AdminStates.waiting_for_vpn_config)
async def save_vpn_config(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    vpn_config_text = message.text.strip()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    original_prompt_vpn = "🔑 <b>VPN kodyny Goşmak: Kodyň Teksti</b> 🔑\n\nVPN kodyny iberiň."
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not admin_message_id or not admin_chat_id:
        await bot.send_message(message.chat.id, "⚠️ Ýagdaý ýalňyşlygy. Täzeden synanyşyň.", reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    if not vpn_config_text:
        await bot.edit_message_text(f"⚠️ VPN kody boş bolup bilmez.\n\n{original_prompt_vpn}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    success = await add_vpn_config_to_db(vpn_config_text)
    if success:
        await bot.edit_message_text("✅ VPN kody üstünlikli goşuldy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    else:
        await bot.edit_message_text("⚠️ VPN kodyny goşmak başartmady. Mümkin, ol eýýäm bar ýa-da maglumatlar bazasynda ýalňyşlyk boldy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()

@router.callback_query(lambda c: c.data == "delete_vpn_config")
async def process_delete_vpn_config_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    
    vpn_configs = await get_vpn_configs_from_db()

    if not vpn_configs:
        await callback.message.edit_text("🗑️ VPN kody sanawy boş. Pozmak üçin hiç zat ýok.", reply_markup=back_to_admin_markup)
        await callback.answer()
        return

    keyboard_buttons = [
        [InlineKeyboardButton(text=f"Konfig #{i+1} (<code>{item['config_text'][:25]}...</code>)", callback_data=f"del_vpn_id:{item['db_id']}")] 
        for i, item in enumerate(vpn_configs)
    ]
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")])

    await callback.message.edit_text("🔪 <b>VPN Kodyny Pozmak</b> 🔪\n\nPozmak üçin kody saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("del_vpn_id:"))
async def confirm_delete_vpn_config(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    
    try:
        config_db_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.message.edit_text("⚠️ Ýalňyşlyk: Nädogry kod ID-si.", reply_markup=back_to_admin_markup)
        await callback.answer("ID ýalňyşlygy", show_alert=True)
        return
    
    all_configs = await get_vpn_configs_from_db()
    config_to_delete = next((c for c in all_configs if c['db_id'] == config_db_id), None)
    
    deleted = await delete_vpn_config_from_db(config_db_id)
    if deleted:
        preview = f"(<code>...{config_to_delete['config_text'][:20]}...</code>)" if config_to_delete else ""
        await callback.message.edit_text(f"🗑️ VPN kody {preview} üstünlikli pozuldy.", reply_markup=back_to_admin_markup)
        await callback.answer("VPN Kody pozuldy", show_alert=False)
    else:
        await callback.message.edit_text("⚠️ Kod tapylmady, eýýäm pozuldy ýa-da maglumatlar bazasynda ýalňyşlyk boldy.", reply_markup=back_to_admin_markup)
        await callback.answer("Kod tapylmady/ýalňyşlyk", show_alert=True)

@router.callback_query(lambda c: c.data == "change_welcome")
async def process_change_welcome_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    
    current_welcome = await get_setting_from_db("welcome_message", "<i>Häzirki Başlangyç haty ýok.</i>")
    await callback.message.edit_text(
        f"📝 <b>Başlangyç hatyny Üýtgetmek</b> 📝\n\n"
        f"Häzirki başlangyç haty:\n"
        f"<blockquote>{current_welcome}</blockquote>\n"
        f"Täze başlangyç hatyny giriziň."
        f"Formatlamak üçin HTML teglerini ulanyp bilersiňiz (meselem, <b>galyň</b>, <i>kursiw</i>, <a href='https://example.com'>salgy</a>, <code>kod</code>).\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")]])
    )
    await state.update_data(admin_message_id=callback.message.message_id, admin_chat_id=callback.message.chat.id)
    await state.set_state(AdminStates.waiting_for_welcome_message)
    await callback.answer()


@router.message(AdminStates.waiting_for_welcome_message)
async def save_welcome_message(message: types.Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    new_welcome_message = message.html_text
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not admin_message_id or not admin_chat_id:
        await bot.send_message(message.chat.id, "⚠️ Ýagdaý ýalňyşlygy. Täzeden synanyşyň.", reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    if not new_welcome_message or not new_welcome_message.strip():
        current_welcome = await get_setting_from_db("welcome_message", "<i>başlangyç haty ýok.</i>")
        await bot.edit_message_text(
            f"⚠️ <b>Ýalňyşlyk:</b> Başlangyç haty boş bolup bilmez.\n"
            f"Häzirki Başlangyç haty:\n<blockquote>{current_welcome}</blockquote>\n\n"
            f"Täze başlangyç hatyny giriziň ýa-da amaly ýatyryň.",
            chat_id=admin_chat_id, message_id=admin_message_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]),
        )
        return

    await save_setting_to_db('welcome_message', new_welcome_message)
    await bot.edit_message_text("✅ Başlangyç hat üstünlikli täzelendi!", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()


@router.callback_query(lambda c: c.data == "add_admin")
async def add_admin_prompt(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer("⛔ Bu funksiýa diňe baş admin üçin elýeterlidir.", show_alert=True)
        return
    await callback.message.edit_text(
        "👮 <b>Admin Goşmak</b> 👮\n\n"
        "Admin bellemek isleýän ulanyjyňyzyň Telegram User ID-sini giriziň.\n"
        "<i>User ID-ni @userinfobot ýa-da @getmyid_bot ýaly botlardan bilip bilersiňiz.</i>\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")]])
    )
    await state.update_data(admin_message_id=callback.message.message_id, admin_chat_id=callback.message.chat.id)
    await state.set_state(AdminStates.waiting_for_admin_id_to_add)
    await callback.answer()


@router.message(AdminStates.waiting_for_admin_id_to_add)
async def process_add_admin_id(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID: return
    new_admin_id_str = message.text.strip()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    fsm_data = await state.get_data()
    admin_message_id = fsm_data.get('admin_message_id')
    admin_chat_id = fsm_data.get('admin_chat_id')
    original_prompt_admin_id = (
        "👮 <b>Admin Goşmak: User ID</b> 👮\n\n"
        "Telegram User ID-ni (san) giriziň.\n"
        "<i>User ID-ni @userinfobot ýaly botlardan bilip bilersiňiz.</i>"
    )
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Ýatyr we yzyna", callback_data="admin_panel_main")]

    if not admin_message_id or not admin_chat_id:
        await bot.send_message(message.chat.id, "⚠️ Ýagdaý ýalňyşlygy. Täzeden synanyşyň.", reply_markup=create_admin_keyboard(message.from_user.id))
        await state.clear()
        return

    try:
        new_admin_id = int(new_admin_id_str)
    except ValueError:
        await bot.edit_message_text(f"⚠️ <b>Ýalňyşlyk:</b> User ID san bolmaly.\n\n{original_prompt_admin_id}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    if new_admin_id == SUPER_ADMIN_ID:
        await bot.edit_message_text(f"⚠️ Baş admin eýýäm ähli hukuklara eýe.\n\n{original_prompt_admin_id}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    current_admins = await get_admins_from_db()
    if new_admin_id in current_admins:
        await bot.edit_message_text(f"⚠️ <code>{new_admin_id}</code> ID-li ulanyjy eýýäm admin.\n\n{original_prompt_admin_id}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_button_row]))
        return

    success = await add_admin_to_db(new_admin_id)
    if success:
        await bot.edit_message_text(f"✅ <code>{new_admin_id}</code> ID-li ulanyjy üstünlikli admin bellenildi!", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    else:
        await bot.edit_message_text(f"⚠️ <code>{new_admin_id}</code> ID-li admini goşmak başartmady. Maglumatlar bazasy ýalňyşlygy.", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=back_to_admin_markup)
    await state.clear()


@router.callback_query(lambda c: c.data == "delete_admin")
async def delete_admin_prompt(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer("⛔ Bu funksiýa diňe baş admin üçin elýeterlidir.", show_alert=True)
        return

    admins_in_db = await get_admins_from_db()

    if not admins_in_db:
        await callback.message.edit_text("🚫 Goşmaça adminleriň sanawy boş. Pozmak üçin hiç kim ýok.", reply_markup=back_to_admin_markup)
        await callback.answer()
        return

    keyboard_buttons = []
    for admin_id in admins_in_db:
        try:
            user = await bot.get_chat(admin_id)
            display_name = f"{user.full_name} (<code>{admin_id}</code>)" if user.full_name else f"Admin (<code>{admin_id}</code>)"
        except Exception:
            display_name = f"Admin (<code>{admin_id}</code>) - <i>ady almak başartmady</i>"
        keyboard_buttons.append([InlineKeyboardButton(text=display_name, callback_data=f"del_admin_id:{admin_id}")])

    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Admin menýusyna gaýt", callback_data="admin_panel_main")])
    await callback.message.edit_text("🔪 <b>Admin Pozmak</b> 🔪\n\nHukuklaryny yzyna almak üçin admini saýlaň:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("del_admin_id:"))
async def confirm_delete_admin(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer("⛔ Bu funksiýa diňe baş admin üçin elýeterlidir.", show_alert=True)
        return

    try:
        admin_id_to_delete = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.message.edit_text("⚠️ Ýalňyşlyk: Pozmak üçin nädogry admin ID-si.", reply_markup=back_to_admin_markup)
        await callback.answer("ID ýalňyşlygy", show_alert=True)
        return

    deleted = await delete_admin_from_db(admin_id_to_delete)
    if deleted:
        await callback.message.edit_text(f"🗑️ <code>{admin_id_to_delete}</code> ID-li admin üstünlikli pozuldy.", reply_markup=back_to_admin_markup)
        await callback.answer("Admin pozuldy", show_alert=False)
    else:
        await callback.message.edit_text("⚠️ Admin tapylmady, eýýäm pozuldy ýa-da maglumatlar bazasy ýalňyşlygy.", reply_markup=back_to_admin_markup)
        await callback.answer("Admin tapylmady/ýalňyşlyk", show_alert=True)


@router.callback_query(lambda c: c.data == "check_subscription")
async def process_check_subscription(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    vpn_configs_full = await get_vpn_configs_from_db()
    vpn_configs_texts = [item['config_text'] for item in vpn_configs_full]

    if not vpn_configs_texts:
        try:
            await callback.message.edit_text("😔 Gynansak-da, häzirki wagtda elýeterli VPN kody ýok. Haýyş edýäris, soňrak synanyşyň.")
        except TelegramBadRequest:
            await callback.answer(text="😔 Elýeterli VPN kody ýok. Soňrak synanyşyň.", show_alert=True)
        await state.clear()
        return

    user_still_needs_to_subscribe = await has_unsubscribed_channels(user_id)
    channels_configured = bool(await get_channels_from_db())

    if not user_still_needs_to_subscribe:
        vpn_config_text = random.choice(vpn_configs_texts)
        text = "🎉 Siz ähli kanallara agza bolduňyz." if channels_configured else "✨ Agza bolanyňyz üçin sagboluň"
        try:
            await callback.message.edit_text(
                f"{text}\n\n"
                f"🔑 <b>Siziň VPN koduňyz:</b>\n<pre><code>{vpn_config_text}</code></pre>",
                reply_markup=None
            )
            await callback.answer(text="✅ Agzalyk barlandy!", show_alert=False)
        except TelegramBadRequest:
             await callback.answer(text="✅ Agzalyk barlandy!", show_alert=False)
        await state.clear()
    else:
        new_keyboard = await create_subscription_task_keyboard(user_id)
        welcome_text_db = await get_setting_from_db('welcome_message', "👋 VPN kodyny almak üçin, aşakdaky kanallara agza boluň:")

        message_needs_update = False
        if callback.message:
            if (callback.message.html_text != welcome_text_db) or \
               (new_keyboard != callback.message.reply_markup):
                 message_needs_update = True

            if message_needs_update:
                try:
                    await callback.message.edit_text(welcome_text_db, reply_markup=new_keyboard)
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e).lower():
                        pass
                    else:
                        logging.error(f"agzalygy barlanda habary redaktirlemekde ýalňyşlyk: {e}")
        await callback.answer(
            text="⚠️ Haýyş edýäris, ähli görkezilen kanallara agza boluň we täzeden synanşyň",
            show_alert=True
        )

async def main():
    global DB_POOL
    try:
        DB_POOL = await asyncpg.create_pool(dsn=DATABASE_URL)
        if DB_POOL:
            logging.info("Successfully connected to PostgreSQL and connection pool created.")
            await init_db(DB_POOL)
            logging.info("Database initialized (tables created if they didn't exist).")
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
