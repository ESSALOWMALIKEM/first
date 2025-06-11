import asyncio
import logging
import random
import json
from urllib.parse import quote, unquote
import asyncpg
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from keep_alive import keep_alive

keep_alive()

logging.basicConfig(level=logging.INFO)

API_TOKEN = '7790968356:AAGYEPi9cpgovtWmuzV98GYXjRAorWOIsGQ'
SUPER_ADMIN_ID = 7877979174  # Lütfen buraya kendi Super Admin ID'nizi girin

DATABASE_URL = "postgresql://htsd_user:NdJwX21r3kuJDcUNZasIGf4M55wHJSXB@dpg-d12im26mcj7s73fd8aug-a/htsd_fxdx"


bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
storage = MemoryStorage()
dp = Dispatcher(bot=bot, storage=storage)
router = Router()
dp.include_router(router)

DB_POOL = None

back_to_admin_markup = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⬅️ Admin panele gaýtmak", callback_data="admin_panel_main")]
])

# FSM States
class SubscriptionStates(StatesGroup):
    checking_subscription = State()

class ContactAdmin(StatesGroup):
    waiting_for_message = State()

class AdminStates(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_name = State()
    waiting_for_multiple_channels = State() # Yeni durum
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


# --- VERİTABANI FONKSİYONLARI ---
async def init_db(pool):
    async with pool.acquire() as connection:
        # Mevcut tablolar...
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
        # Varsayılan hoş geldin mesajı
        default_welcome = "👋 <b>Hoş geldiňiz!</b>\n\nVPN Koduny almak üçin, aşakdaky Kanallara Agza boluň we soňra Agza boldum düwmesine basyň."
        await connection.execute(
            "INSERT INTO bot_settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
            'welcome_message', default_welcome
        )

# DB Helper fonksiyonları (get_setting, save_setting, vs.) olduğu gibi kalır
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
    """Отправляет предпросмотр сообщения (текст, медиа или документ)."""
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
    elif content_type == 'document': # YENİ: Dosya gönderme
        return await bot.send_document(chat_id, file_id, caption=caption, reply_markup=keyboard)


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
        admin_list = [row['user_id'] for row in rows]
        if SUPER_ADMIN_ID not in admin_list:
            admin_list.append(SUPER_ADMIN_ID)
        return admin_list


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

# --- YARDIMCI FONKSİYONLAR ---
async def create_subscription_task_keyboard(user_id: int) -> InlineKeyboardMarkup:
    # Bu fonksiyon olduğu gibi kalabilir
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
    # Bu fonksiyon olduğu gibi kalabilir
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
        [InlineKeyboardButton(text="📡 Kanallary Yönet", callback_data="manage_channels")], # DEĞİŞTİ
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


# --- KULLANICI-ADMİN MESAJLAŞMA SİSTEMİ ---

@router.message(Command("mesaj"))
async def message_admin_start(message: types.Message, state: FSMContext):
    """Kullanıcının adminlere mesaj gönderme sürecini başlatır."""
    await state.clear()
    await message.answer(
        "✍️ Adminlere göndermek isleýän habaryňyzy ýazyň.\n\n"
        "Habaryňyz ähli adminlere iberiler. /start buýrugyny ýazyp, bu ýagdaýdan çykyp bilersiňiz.",
        reply_markup=None
    )
    await state.set_state(ContactAdmin.waiting_for_message)

@router.message(ContactAdmin.waiting_for_message)
async def forward_message_to_admins(message: types.Message, state: FSMContext):
    """Kullanıcının mesajını tüm adminlere iletir."""
    admins = await get_admins_from_db()
    if not admins:
        await message.answer("😔 Gynansak-da, häzirki wagtda jogap berjek admin ýok.")
        await state.clear()
        return

    # Kullanıcıya mesajının gönderildiğine dair onay ver
    await message.answer("✅ Habaryňyz adminlere iberildi. Jogap gelmegine garaşyň.")
    
    # Mesajı tüm adminlere ilet
    from_user = message.from_user
    for admin_id in admins:
        try:
            # Mesajı forward et ve admin için bilgilendirici bir başlık ekle
            await bot.forward_message(
                chat_id=admin_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            # Ayrı bir metinle kimden geldiğini ve nasıl cevap verileceğini belirt
            await bot.send_message(
                admin_id,
                f"👤 <b>Täze Habar</b>\n"
                f"<b>Kimden:</b> {from_user.full_name}\n"
                f"<b>User ID:</b> <code>{from_user.id}</code>\n\n"
                f"<i>Bu habara jogap bermek üçin Telegram-yň 'Jogap ber' (Reply) aýratynlygyny ulanyň.</i>"
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            logging.warning(f"Admin {admin_id} ile iletişim kurulamadı veya engellendi.")
        except Exception as e:
            logging.error(f"Admine {admin_id} mesaj iletilirken hata oluştu: {e}")
    
    await state.clear()

async def is_admin_reply(message: Message, bot: Bot):
    """Filtre: Mesajın bir admin tarafından kullanıcıya yanıt olup olmadığını kontrol eder."""
    if not message.reply_to_message:
        return False
    # Yanıtlanan mesaj bot tarafından mı gönderilmiş?
    if message.reply_to_message.from_user.id != bot.id:
        return False
    # Yanıtlayan kişi admin mi?
    if not await is_user_admin_in_db(message.from_user.id):
        return False
    # Yanıtlanan mesaj, bir kullanıcıdan gelen ve forward edilen bir mesaj mı?
    # Bunu kontrol etmek için, botun gönderdiği açıklama metnini arayabiliriz.
    replied_text = message.reply_to_message.text or ""
    if "👤 Täze Habar" in replied_text and "User ID:" in replied_text:
        return True
    return False

@router.message(is_admin_reply)
async def reply_from_admin_to_user(message: types.Message):
    """Adminin yanıtını alır ve ilgili kullanıcıya gönderir."""
    replied_text = message.reply_to_message.text
    try:
        # User ID'yi metinden çıkar
        user_id_str = replied_text.split("User ID:")[1].strip().split("\n")[0]
        user_id = int(user_id_str)
    except (IndexError, ValueError) as e:
        logging.error(f"Yanıtlanan mesajdan user_id çıkarılamadı: {e}\nMetin: {replied_text}")
        await message.reply("⚠️ Bu habardan ulanyjy ID-sini almak başartmady. Ulanyja gönüden-göni jogap beriň.")
        return

    try:
        # Adminin mesajını kullanıcıya gönder
        await bot.send_message(
            chat_id=user_id,
            text=f"📨 <b>Admindan Jogap</b> 📨\n\n{message.html_text}"
        )
        # Admine de onayı gönder
        await message.reply("✅ Jogabyňyz ulanyja üstünlikli iberildi.")
    except (TelegramForbiddenError, TelegramBadRequest):
        await message.reply(f"⚠️ Bu ulanyja (ID: {user_id}) habar ibermek başartmady. Mümkin, ol boty bloklady.")
    except Exception as e:
        await message.reply(f"⚠️ Habar iberilende näbelli bir ýalňyşlyk ýüze çykdy: {e}")


# --- TEMEL KOMUTLAR (/start, /admin) ---
@router.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    # Bu fonksiyon büyük ölçüde aynı kalabilir
    user_id = message.from_user.id
    await add_user_to_db(user_id)
    await state.clear() # Önceki durumları temizle

    # ... (geri kalan start mantığı aynı)
    vpn_configs_full = await get_vpn_configs_from_db()
    vpn_configs = [item['config_text'] for item in vpn_configs_full]

    if not vpn_configs:
        await message.answer("😔 Gynansak-da, häzirki wagtda elýeterli VPN Kodlary ýok. Haýyş edýäris, soňrak synanyşyň.")
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
    else:
        keyboard = await create_subscription_task_keyboard(user_id)
        welcome_text = await get_setting_from_db('welcome_message', "👋 <b>Hoş geldiňiz!</b>\n\nVPN almak üçin, aşakdaky Kanallara agza boluň we 'Agza boldum' düwmesine basyň.")
        if not keyboard.inline_keyboard:
             if vpn_configs:
                 vpn_config_text = random.choice(vpn_configs)
                 await message.answer(f"✨ Agza bolanyňyz üçin sagboluň!\n\n🔑 <b>Siziň VPN Kodyňyz:</b>\n<pre><code>{vpn_config_text}</code></pre>")
             else:
                 await message.answer("😔 Häzirki wagtda elýeterli VPN kodlary ýok.")
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


# --- ADMIN PANELİ HANDLERLARI ---

@router.callback_query(lambda c: c.data == "exit_admin_panel")
async def exit_admin_panel_handler(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    await state.clear()
    try:
        await callback.message.edit_text(
            "✅ Siz admin panelden çykdyňyz.\n\n"
            "Adaty ulanyjy hökmünde täzeden işe başlamak üçin /start giriziň. "
            "Adminlere habar ibermek üçin /mesaj giriziň.",
            reply_markup=None
        )
    except TelegramBadRequest:
        await callback.message.answer(
             "✅ Siz admin panelden çykdyňyz.\n\n"
            "Adaty ulanyjy hökmünde täzeden işe başlamak üçin /start giriziň. "
            "Adminlere habar ibermek üçin /mesaj giriziň.",
            reply_markup=None
        )
    await callback.answer()

@router.callback_query(lambda c: c.data == "get_stats")
async def get_statistics(callback: types.CallbackQuery):
    # Bu fonksiyon olduğu gibi kalabilir
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    
    async with DB_POOL.acquire() as conn:
        user_count = await conn.fetchval("SELECT COUNT(*) FROM bot_users")
        channel_count = await conn.fetchval("SELECT COUNT(*) FROM channels")
        addlist_count = await conn.fetchval("SELECT COUNT(*) FROM addlists")
        vpn_count = await conn.fetchval("SELECT COUNT(*) FROM vpn_configs")
        # Super admini saymadan diğer adminleri say
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


# --- KANAL YÖNETİMİ (YENİ SİSTEM) ---

@router.callback_query(lambda c: c.data == "manage_channels")
async def manage_channels_prompt(callback: types.CallbackQuery):
    """Admin'e tekli veya çoklu kanal ekleme seçeneği sunar."""
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Tek Kanal Ekle", callback_data="add_single_channel")],
        [InlineKeyboardButton(text="➕➕ Toplu Kanal Ekle", callback_data="add_multiple_channels")],
        [InlineKeyboardButton(text="➖ Kanal Poz", callback_data="delete_channel")],
        [InlineKeyboardButton(text="⬅️ Admin panele gaýtmak", callback_data="admin_panel_main")]
    ])
    
    await callback.message.edit_text(
        "📡 <b>Kanallary Dolandyrmak</b> 📡\n\n"
        "Aşakdaky amallardan birini saýlaň:",
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(lambda c: c.data == "add_single_channel")
async def process_add_channel_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Tekli kanal ekleme sürecini başlatır."""
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    await callback.message.edit_text(
        "📡 <b>Tek Kanal Goşmak</b> 📡\n\n"
        "Kanalyň ID-sini giriziň (meselem, <code>@PublicChannel</code>) ýa-da şahsy kanalyň ID-sini (meselem, <code>-1001234567890</code>).\n\n"
        "<i>Bot, agzalar barada maglumat almak hukugy bilen kanala administrator hökmünde goşulmaly.</i>\n",
        reply_markup=back_to_admin_markup
    )
    await state.update_data(admin_message_id=callback.message.message_id, admin_chat_id=callback.message.chat.id)
    await state.set_state(AdminStates.waiting_for_channel_id)
    await callback.answer()

@router.callback_query(lambda c: c.data == "add_multiple_channels")
async def process_add_multiple_channels_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Çoklu kanal ekleme sürecini başlatır."""
    if not await is_user_admin_in_db(callback.from_user.id):
        await callback.answer("⛔ Giriş gadagan.", show_alert=True)
        return
    await callback.message.edit_text(
        "📡 <b>Toplu Kanal Goşmak</b> 📡\n\n"
        "Goşmak isleýän kanallaryňyzy her setire bir kanal gelecek şekilde aşakdaky formatda giriziň:\n\n"
        "<code>Kanal_ID,Görüncek Ady</code>\n\n"
        "<b>Meselem:</b>\n"
        "<code>@my_channel,Meniň Kanalym</code>\n"
        "<code>-10012345678,Meniň Hususy Kanalym</code>\n\n"
        "<i>Her kanal üçin bot administrator bolmaly.</i>",
        reply_markup=back_to_admin_markup
    )
    await state.set_state(AdminStates.waiting_for_multiple_channels)
    await callback.answer()


@router.message(AdminStates.waiting_for_multiple_channels)
async def process_multiple_channels(message: types.Message, state: FSMContext):
    """Çoklu kanal girdisini işler ve veritabanına ekler."""
    if not await is_user_admin_in_db(message.from_user.id): return
    
    lines = message.text.strip().split('\n')
    added_count = 0
    failed_channels = []

    status_message = await message.answer("⏳ Kanallar barlanýar we goşulýar, garaşyň...")

    for line in lines:
        try:
            channel_id, channel_name = map(str.strip, line.split(',', 1))
        except ValueError:
            failed_channels.append(f"<code>{line}</code> (Nädogry format)")
            continue

        # ID format kontrolü
        if not (channel_id.startswith('@') or (channel_id.startswith('-100') and channel_id[1:].isdigit())):
            failed_channels.append(f"<code>{channel_id}</code> (Nädogry ID formaty)")
            continue
        
        # Bot admin mi kontrolü
        try:
            bot_member = await bot.get_chat_member(chat_id=channel_id, user_id=bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                failed_channels.append(f"<code>{channel_id}</code> (Bot admin däl)")
                continue
        except Exception:
            failed_channels.append(f"<code>{channel_id}</code> (Kanal tapylmady ýa-da barlamak başartmady)")
            continue
        
        # Veritabanına ekleme
        success = await add_channel_to_db(channel_id, channel_name)
        if success:
            added_count += 1
        else:
            failed_channels.append(f"<code>{channel_id}</code> (Eýýäm bar ýa-da DB ýalňyşlygy)")

    report_text = f"✅ <b>Toplu Kanal Goşmak Tamamlandy</b>\n\n" \
                  f"👍 Üstünlikli Goşulan: <b>{added_count}</b>\n" \
                  f"👎 Başarısyz Bolan: <b>{len(failed_channels)}</b>"
    
    if failed_channels:
        report_text += "\n\n<b>Başarısyz bolan kanallar:</b>\n" + "\n".join(failed_channels)

    await status_message.edit_text(report_text, reply_markup=back_to_admin_markup)
    await state.clear()


# --- DUYURU (MAILING) SİSTEMİ (DOSYA DESTEĞİ EKLENDİ) ---
def parse_buttons_from_text(text: str) -> types.InlineKeyboardMarkup | None:
    # Bu fonksiyon olduğu gibi kalabilir
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
    Duyuru için içeriği işleyen evrensel fonksiyon.
    Metin, fotoğraf, video, GIF ve DOKÜMAN kabul eder.
    """
    content = {}
    if message.photo:
        content = {'type': 'photo', 'file_id': message.photo[-1].file_id, 'caption': message.caption}
    elif message.video:
        content = {'type': 'video', 'file_id': message.video.file_id, 'caption': message.caption}
    elif message.animation:
        content = {'type': 'animation', 'file_id': message.animation.file_id, 'caption': message.caption}
    elif message.document: # YENİ: Dosya içeriği
        content = {'type': 'document', 'file_id': message.document.file_id, 'caption': message.caption}
    elif message.text:
        content = {'type': 'text', 'text': message.html_text}
    else:
        await message.answer("⚠️ Bu habar görnüşi goldanmaýar. Tekst, surat, wideo, GIF ýa-da DOKUMENT iberiň.")
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

@router.message(AdminStates.waiting_for_mailing_message, F.content_type.in_({'text', 'photo', 'video', 'animation', 'document'})) # DEĞİŞTİ
async def process_user_mailing_message(message: Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    await process_mailing_content(message, state, "user")

@router.message(AdminStates.waiting_for_channel_mailing_message, F.content_type.in_({'text', 'photo', 'video', 'animation', 'document'})) # DEĞİŞTİ
async def process_channel_mailing_message(message: Message, state: FSMContext):
    if not await is_user_admin_in_db(message.from_user.id): return
    await process_mailing_content(message, state, "channel")

# Geri kalan kod (eski kanal ekleme mantığı hariç) büyük ölçüde aynı kalabilir.
# ...
# Bu noktadan sonra, orijinal dosyanızdaki
# process_channel_id'den başlayarak save_channel'a kadar olan
# tekli kanal ekleme fonksiyonları,
# duyuru (mailing) fonksiyonları (execute_user_broadcast, start_mailing_prompt, vb.),
# addlist yönetimi (process_add_addlist_prompt, vb.),
# VPN yönetimi (process_add_vpn_config_prompt, vb.),
# admin ekleme/silme (add_admin_prompt, vb.)
# ve ana `main` döngüsü gibi geri kalan tüm fonksiyonları
# buraya kopyalayabilirsiniz. Onlarda istenen bir değişiklik bulunmamaktadır.
# Sadece yukarıdaki değişiklikleri entegre etmek yeterlidir.
# Okunabilirlik için, geri kalan fonksiyonları aşağıya ekliyorum.


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
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Admin panele gaýtmak", callback_data="admin_panel_main")]

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
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[cancel_button_row]])
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
    cancel_button_row = [InlineKeyboardButton(text="⬅️ Admin panele gaýtmak", callback_data="admin_panel_main")]

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
        await bot.edit_message_text(f"⚠️ Kanal ady boş bolup bilmez.\n\n{original_prompt_name}", chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[cancel_button_row]]))
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

# ... (Kalan tüm fonksiyonlar: addlist, vpn, welcome message, admin management, mailing logic, subscription check, etc.)
# ... Orijinal dosyanızdaki bu fonksiyonları buraya yapıştırabilirsiniz.
# ... Değişiklik gerektiren tüm kısımlar yukarıda güncellenmiştir.
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
            "✍️ Ibermek isleýän habaryňyzy (tekst, surat, wideo, GIF ýa-da dokument) iberiň.",
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
            "✍️ Ibermek isleýän habaryňyzy (tekst, surat, wideo, GIF ýa-da dokument) iberiň.",
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
# ...
# Buradan itibaren geri kalan tüm orijinal fonksiyonlar (addlist, vpn, welcome, admin ekleme/silme, subscription check vb.)
# olduğu gibi kalabilir ve çalışmaya devam edecektir.
# ...

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

# Diğer tüm yardımcı fonksiyonlar (addlist, vpn, welcome, admin yönetimi vs.)
# Değiştirilmeden kalabilir.
# ... (add_addlist_prompt, save_addlist_name, delete_addlist_prompt...)
# ... (add_vpn_config_prompt, save_vpn_config, delete_vpn_config_prompt...)
# ... (change_welcome_prompt, save_welcome_message...)
# ... (add_admin_prompt, process_add_admin_id, delete_admin_prompt...)


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
