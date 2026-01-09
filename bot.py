import logging
import re
import socket
import base64
import requests
import whois
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from keep_alive import keep_alive

keep_alive()

# --- YAPILANDIRMA VE TOKENLER ---
TELEGRAM_TOKEN = "8256915637:AAHOjwML8mP9AIj-c4C87fkpwiGW7rEiOc8"
LLAMA_API_KEY = 'ad33259d-2144-4a10-9dd9-4127d40ce933'
LLAMA_API_URL = 'https://api.sambanova.ai/v1/chat/completions'

# --- LOGLAMA ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- RSA ANAHTARLARI (HAPP DEKOD İÇİN) ---
KEY_1 = """-----BEGIN RSA PRIVATE KEY-----
MIICXwIBAAKBgQCxsS7PUq1biQlVD92rf6eXKr9oG1/SrYx3qWahZP+Jq35m4Wb/
Z+mB6eBWrPzJ/zZpZLWLQorcvOKt+sLaCHyH1HLNkti4jlaEQX6x97XgBm8GK08+
lLLWquFDhWRNxsrfzJyNdpVopzBRmCJKTc8ObYyPbrv9T35a8Kd5WqjnUwIDAQAB
AoGBAJoqe85skPPF5U7jwRM2YhUJhZ+xgGWtJR3834pPslWjcLuZ/F7DrRiF7ZnF
5FztDCxMsCXuycPSLWl9EulQS5mrL/fnwpK2jVE8O1Em9RsBOOrWwzuZnAuooRIb
/8zC0fvH2oGkk60zSKycMe69uvYUDjhvULX2Spjmf9CS9/HhAkEA3I797En/DrpA
Zz6NM4GqZ1mkH0kEX/kAHLP1lBgYL1kVK455EG/ecJkMJmtK7A+fWw0N0IcxrpYA
bbOAo19vjwJBAM4+0MAZ8TIZUk6Rs2gYUo04A6mYUy5MWtRa9pyFIgD71oHDR+1j
rnPLqQyCj0tfbZBc1iVgsisJBpocC8sKaf0CQQDRNd3Mxb/nY2p1xJLBmaxezlvs
xSEePB4MG/PFXzmJqBF5uHJD0imIWtR4mOt/ka4R+wbwl1zcAzMy28MYtQ0nAkEA
uUILWML0uL+uAw01TeerH1aVU52T+h5z6BPdOTMNHD0arWywCzhi13i03JvaAyYw
0F/Tq7dz0txEpeFTZopwMQJBANnHbzB87/xTjDQA4/L8sSU8m0vM1nRWmJIaAC94
pcM+KDGLnbBhWrvZGy8Zg8vQwNvdvCLvylk0jVTTFqW3ibM=
-----END RSA PRIVATE KEY-----"""

KEY_2 = """-----BEGIN RSA PRIVATE KEY-----
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
-----END RSA PRIVATE KEY-----"""

KEY_3 = """-----BEGIN RSA PRIVATE KEY-----
MIIJJwIBAAKCAgEAlBetA0wjbaj+h7oJ/d/hpNrXvAcuhOdFGEFcfCxSWyLzWk4S
AQ05gtaEGZyetTax2uqagi9HT6lapUSUe2S8nMLJf5K+LEs9TYrhhBdx/B0BGahA
+lPJa7nUwp7WfUmSF4hir+xka5ApHjzkAQn6cdG6FKtSPgq1rYRPd1jRf2maEHwi
P/e/jqdXLPP0SFBjWTMt/joUDgE7v/IGGB0LQ7mGPAlgmxwUHVqP4bJnZ//5sNLx
WMjtYHOYjaV+lixNSfhFM3MdBndjpkmgSfmgD5uYQYDL29TDk6Eu+xetUEqry8yS
PjUbNWdDXCglQWMxDGjaqYXMWgxBA1UKjUBWwbgr5yKTJ7mTqhlYEC9D5V/LOnKd
6pTSvaMxkHXwk8hBWvUNWAxzAf5JZ7EVE3jt0j682+/hnmL/hymUE44yMG1gCcWv
SpB3BTlKoMnl4yrTakmdkbASeFRkN3iMRewaIenvMhzJh1fq7xwX94otdd5eLB2v
RFavrnhOcN2JJAkKTnx9dwQwFpGEkg+8U613+Tfm/f82l56fFeoFN98dD2mUFLFZ
oeJ5CG81ZeXrH83niI0joX7rtoAZIPWzq3Y1Zb/Zq+kK2hSIhphY172Uvs8X2Qp2
ac9UoTPM71tURsA9IvPNvUwSIo/aKlX5KE3IVE0tje7twWXL5Gb1sfcXRzsCAwEA
AQKCAgAK3VHMFCHlQaiqvHNPNMWRGp0JJl27Ulw3U1Q9p+LC3OWNknyvpxC5EJPQ
bTUXhlO2A9AiDOXmaj5EMavTAaj0tzWhLlrVVQ/CSJYS4sVyAY67GyTpOIxmYtPB
E3YY6vTU1SSoU2dqnMDnfwAbM2g0QXatXYRDGPYLLNHHp7R27IBpBTJeDwb2qEA1
BBC/3WXsfVy6cfhWrrB7fH4F9tuEtG+sp+N2fbDcFnDH1hbQAm+HEXKzWMpRcSmX
+rQ2wDlLW/N3utI+TzP4Vx5zTuT3QCsDYzeRgSJ4CjMwKKSGZ3QDF5cDCVJdsJ24
fRl+mpBWoLqqBS7gzFVYsTx88GNs5jl9D7ZndIEOKYhtA00NgF+0N1Vs7IbgfoBf
wABSFoiukBcre2NvJ4jVxApy09IiN6E/HBZ/qhH3q+1k9nLFgzH9VsBXuucgjlSF
XzVLLQilfsd7LEaX8ytGDAiAC3RLbIhDRX3ruv0ufRSwhUoGd4ps+cgHrKGUGqz4
pdjOzWFNTzpTTYuxkoMbklI+HIFQcstNLW0mryBcWhldqLhYNGH5w4fX+J/wkxbH
1Yh9slPWT+WX69/l9myysscXxSlev9Ycty4rNWt9kohNHvBd5ZxlePD5ngTmCZ2P
jisUS1Kvmy9rjzRjP2qNoxmXmTbp3QJymuF1RjtRHxlqHGVlgQKCAQEA0S/SnC+B
UlUxxCVQ+qNE8FAe5EWdNgSlz1ep5NGcOBUgpFStHJBGdzSc1Ht6MuBd+2Gqfzi4
6CR5BbyaC9i3P0X4347wKjrzPQ39l1kGideRKEKMAbmj2SdaU7kYWFhddurGssp4
xzojNG0BYkR/0kEnHeCu/RJ6HVwv5K5vyhYsAwKeWeTS3T06KElgy4uNNRRAqI9Z
JamrU7ZfIQ7YBHsCWlgFwx7Hu7rQS8dOPmd4TW0Xs32yEDfDymw98e4kxNME01Z9
Q55uShLwXo4g+wp/6SYL363OyR/MqSAW66IthPqz6WnJ37hmk2SZsUip9tBHPdJy
vACHeNR9SP4VMwKCAQEAtTvMeW0QvNWK7+VM2cnm2viFPpqGWDaccI6Zct/Qb6cO
05xdRtarm/QjM3vXjjN4ALj4gPkz014oPEcHJe5Y6ma1tGmy01cltvYoUsfxYHX2
jUiaI9EmmOIR/9gSiAZn+P9RjNx9Q/hHT9ul+H5FnitC9wV0TZ7egu3ROKuZ7t5E
hdogO5lC8qUn6GrVIdj9eDAGkHWdO6v3cqYuP6cV6yiBOK2CikW+MnLC8yXGwvWX
7iW4/2f0xBP+NWgXPzZu627FC8EDmZv8TEGppd5RsJNcQOraXnq7foEzHCB2MsvJ
rDbHAmTqKaWKzoxR+dzJOSt1sHbhNXoKKnsEqd112QKCAQAcq2c8DK62sAJwFYUx
tKrAHNr/AiN3wc9PyX35ZFj6vrqIiypmncdqkwVjgcDPtDxtNYd+hDGjb0w+4whh
00PaIibnzNlRkF7B4Wb+FS92ONsmH2i828p++ovAqb+SbBnzMF4nJuTCuU8V4lKs
OyMhl9hame6htKST3Yya1OVxVvSVPQii3V+g/sE3wEbJ3shtm+b4sxzOsqBOitIi
37vvcURzSVkQ0ukg64uctyYcG2Y7hlYXPYToAByPY6Jhw/e6GgmxRUtJty76a/oR
m30dquS4+YPrFhEfM4KDM2iwxrtiXFHIDb2jMcytKr59s63Hq+f3qx4aciAfCVBa
bqhNAoIBAFZl8p20k/Uh7EFfVBrDeO3M6mCk9ATbzAqQwLCV6F1CC/xvn7wknN0V
Ly7dDC77dGsLw1Rg+Qb77TyHM+4uSW89lcQzW5ALDKzDfwevz++HbQl/ohQPIlJh
++i3DmaQf0KiHTOE7abYls6ITQBA2lmEEEGI9SAH69YJH+PfUtwgVBRnn1QqRVM9
zt+rBn5DXtrMMmTt3Q5UdfvPI18u/XEE902Y0hGvG/Qa57tYt/+7azmZ/C6uVW6g
hWDahbKZ9ZkBTqjC1D+HsGh+KS0s5k7CgYllLMM7yWSOnVn8U7z1j+gsmQUYLNW7
2IeNN4thaQB7Knj8w3JmArCrwtZkAEkCggEANfI5YqEYgq/Mt4NeTTHG5PoRuy1c
RzJLB8QCRF5O2GLij/jl61zSdbeczsNqJzufnxKx49Okkesy9xKVAcT2QMJ55V38
wekpJk0p3wdEhgdBLhOO6kY6R9dhy74e8LFDERH/MfRuvOhBcLqjGb6xGnedf3yy
IFm5Mt4aWOVxLyqUQGF76Dj+PQXjwmQBjxsgxrBAf2UVm/4eb8aX/2xlWDjJ8eXX
R+4PaoA7jR4tsfW7z0iYqA+GUQ0zTcINJdoSTbypxkT8iVQI3VAWcKILnNcoZS4Q
1n9PKHp8L9qHLGlIgt2jOpwKaYDChgoJI5+9WJFarSi7yX1pBXgMfD7aHA==
-----END RSA PRIVATE KEY-----"""

KEY_4 = """-----BEGIN RSA PRIVATE KEY-----
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
-----END RSA PRIVATE KEY-----"""

# --- CONVERSATION STATES (GHOST NAME) ---
ILK_ISIM, IKINCI_ISIM = range(2)

# --- YARDIMCI FONKSİYONLAR ---

def is_ip_address(text):
    try:
        socket.inet_aton(text)
        return True
    except socket.error:
        return False

def clean_data(data):
    if isinstance(data, list):
        return ", ".join([str(x) for x in data if x])
    if data is None:
        return "Bilinenok"
    return str(data)

async def chat_with_llama(user_message: str):
    headers = {
        "Authorization": f"Bearer {LLAMA_API_KEY}",
        "Content-Type": "application/json"
    }
    request_body = {
        "model": "Meta-Llama-3.3-70B-Instruct",
        "messages": [
            {"role": "system", "content": "Senin adın Ghost Ai. Yardımsever bir yapay zekasın. Yanıtlarında Markdown kullanmaya özen göster."},
            {"role": "user", "content": user_message}
        ],
        "max_completion_tokens": 10000
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(LLAMA_API_URL, headers=headers, json=request_body, timeout=60.0)
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
        except Exception as e:
            return f"❌ API Error: {str(e)}"

# --- KOMUT HANDLERLARI ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 **Salam! Men Ghost Helper Bot.**\n"
        "Şu funksiýalary ýerine ýetirip biler:\n\n"
        "1️⃣ **Happ Decrypt:** `happ://crypt...` ssylkalaryny awtomatiki döwmek.\n\n"
        "2️⃣ **IP WhoIS:** Diňe IP adresini ýazsaňyz (meselem `8.8.8.8`) maglumat almak.\n\n"
        "3️⃣ **Ters Unikode:** Adyňyzy ters ýazylan unikode etmek üçin `/ghost` komandasyny ýazyn.\n\n"
        "4️⃣ **Domain Whois:** `/whois google.com` görnüşinde domenleri barlap bilersiňiz.\n\n"
        "5️⃣ **AI Sorag:** Başga islendik zady ýazsaňyz, Ghost AI bilen gürleşersiňiz."
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)

# --- GHOST NAME MANIPULATION ---

async def ghost_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salam, adyňyzy ghost ýazgy line ýaly ters unikod etmek üçin ilki bilen **ýazgydan soň görünjek bölegi** ýazyň (line):", parse_mode='HTML')
    return ILK_ISIM

async def ilk_bolum_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ilk'] = update.message.text
    await update.message.reply_text("Indi birinji bölegi **ýazgydan öň görünjek** (ghost) bölegi ýazyň:", parse_mode='HTML')
    return IKINCI_ISIM

async def ikinci_bolum_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ikinci = update.message.text
    ilk = context.user_data['ilk']
    RLI = "\u2067"
    manipule_edilmis = f"{RLI}{RLI}{RLI}{ilk}{RLI}{ikinci}"

    await update.message.reply_text(f"✅ Siziň adyňyz indi {ilk} yazgy {ikinci} görnüşde bolar!")

    keyboard = [[InlineKeyboardButton("📋 Şuňa bas", switch_inline_query_current_chat=manipule_edilmis)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Bot username pozup taýýarlanan ady 'Hepsini seç' edip saýlap goýuň:\n\n<code>{manipule_edilmis}</code>",
        parse_mode='HTML',
        reply_markup=reply_markup
    )
    return ConversationHandler.END

async def ghost_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Proses ýatyryldy.")
    return ConversationHandler.END

# --- WHOIS & IP & DECRYPT & AI (MERKEZİ MANTIK) ---

async def whois_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Kullanıcı /whois google.com dediğinde çalışır
    if not context.args:
        await update.message.reply_text("❌ Domen ady giriziň. Örn: `/whois google.com`", parse_mode=ParseMode.MARKDOWN)
        return

    query = context.args[0]
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    try:
        w = whois.whois(query)
        if not w.domain_name:
             await update.message.reply_text(f"❌ **{query}** üçin maglumat çekilmedi.")
             return

        sonuc = (
            f"🌐 **Domain maglumatlary**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏷 **Domain:** `{clean_data(w.domain_name)}`\n"
            f"🏢 **Registrar:** `{clean_data(w.registrar)}`\n"
            f"📅 **Ýazylan senesi:** {clean_data(w.creation_date)}\n"
            f"⌛ **Dynyş wagty:** {clean_data(w.expiration_date)}\n"
            f"🌍 **Ýurt:** {clean_data(w.country)}\n"
            f"⚙️ **Name Servers:**\n`{clean_data(w.name_servers)}`"
        )
        await update.message.reply_text(sonuc, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ Hat: {str(e)}")

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Bu fonksiyon gelen mesajı analiz eder ve yönlendirir:
    1. HAPP URL -> Decrypt
    2. IP Adresi -> IP Lookup
    3. Diğer -> AI Chat
    """
    text = update.message.text.strip()
    
    # 1. DURUM: HAPP DEKOD (happ://crypt...)
    if text.startswith("happ://crypt"):
        await handle_decryption(update, context, text)
        return

    # 2. DURUM: IP ADRESİ
    # Eğer metin sadece bir IP adresi ise
    if is_ip_address(text):
        await handle_ip_lookup(update, context, text)
        return

    # 3. DURUM: AI CHAT (Varsayılan)
    # Eğer yukarıdakiler değilse AI'ya gönder
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    ai_response = await chat_with_llama(text)
    try:
        await update.message.reply_text(ai_response, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text(ai_response) # Markdown hatası olursa düz metin

async def handle_ip_lookup(update, context, ip):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    loading_msg = await update.message.reply_text(f"🔍 `{ip}` IP barlanylýar...", parse_mode=ParseMode.MARKDOWN)
    
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,regionName,city,zip,lat,lon,timezone,isp,org,as,query")
        data = response.json()

        if data['status'] == 'fail':
            await loading_msg.edit_text("❌ Ýalňys IP adresi.")
            return

        google_maps_link = f"https://www.google.com/maps/search/?api=1&query={data['lat']},{data['lon']}"
        sonuc = (
            f"📡 **IP barada maglumat**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🖥 **IP:** `{data['query']}`\n"
            f"🌍 **Lokasiya:** {data['country']} ({data['countryCode']})\n"
            f"🏙 **Şäher/ýer:** {data['regionName']} / {data['city']}\n"
            f"📮 **Post Kod:** {data['zip']}\n"
            f"🏢 **ISP:** {data['isp']}\n"
            f"🏢 **Organizasya:** {data['org']}\n"
            f"📍 [Kartadan Lokasiýany Tap]({google_maps_link})"
        )
        await loading_msg.edit_text(sonuc, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=False)
    except Exception as e:
         await loading_msg.edit_text(f"❌ Hata: {str(e)}")

async def handle_decryption(update, context, encrypted_text):
    key_pem = None
    prefix_length = 0

    if encrypted_text.startswith("happ://crypt4/"):
        key_pem = KEY_4
        prefix_length = len("happ://crypt4/")
    elif encrypted_text.startswith("happ://crypt3/"):
        key_pem = KEY_3
        prefix_length = len("happ://crypt3/")
    elif encrypted_text.startswith("happ://crypt2/"):
        key_pem = KEY_2
        prefix_length = len("happ://crypt2/")
    elif encrypted_text.startswith("happ://crypt/"):
        key_pem = KEY_1
        prefix_length = len("happ://crypt/")
    else:
        await update.message.reply_text("❌ Tanımsız happ formatı.")
        return

    data_to_decrypt = encrypted_text[prefix_length:]

    try:
        encrypted_bytes = base64.b64decode(data_to_decrypt)
        rsa_key = RSA.import_key(key_pem)
        cipher = PKCS1_v1_5.new(rsa_key)
        sentinel = b"DECRYPTION_FAILED"
        decrypted_bytes = cipher.decrypt(encrypted_bytes, sentinel)

        if decrypted_bytes == sentinel:
            await update.message.reply_text("❌ Döwip bolmady @ghost_fsociety yüz tutuň.")
            return

        result = decrypted_bytes.decode('utf-8')
        await update.message.reply_text(f"✅ Döwülen ssylka:\n\n`{result}`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Ýalňyşlyk:\n{str(e)}")

# --- MAIN ---

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Conversation Handler (Ghost Name - En yüksek öncelik)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('ghost', ghost_start)],
        states={
            ILK_ISIM: [MessageHandler(filters.TEXT & ~filters.COMMAND, ilk_bolum_al)],
            IKINCI_ISIM: [MessageHandler(filters.TEXT & ~filters.COMMAND, ikinci_bolum_al)],
        },
        fallbacks=[CommandHandler('cancel', ghost_cancel)],
    )
    app.add_handler(conv_handler)

    # Standart Komutlar
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("whois", whois_command))

    # Genel Mesaj Handler (IP, Happ ve AI Router)
    # filters.TEXT & ~filters.COMMAND -> Komut olmayan tüm metinleri yakalar
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))

    print("Ghost Unified Bot Aktif...")
    app.run_polling()

if __name__ == '__main__':
    main()
