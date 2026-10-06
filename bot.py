import os
import re
import time
import telebot
from dotenv import load_dotenv
from telebot import types
from flask import Flask, request, abort

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")          # bo'sh bo'lsa polling ishlaydi
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

CONTENT = ['text', 'photo', 'document', 'video', 'voice']

BTN_ORDER = "🛍 Buyurtma berish"
BTN_EDIT = "✏️ O'zgartirish"
BTN_CANCEL = "❌ Bekor qilish"

user_state = {}    # user_id -> "ordering" yoki "editing"
orders = {}        # user_id -> adminga ketgan buyurtma xabarining id si
admin_state = {}   # "target" -> admin hozir javob yozayotgan mijoz id si

# ---------- Mijozlar ro'yxati (hammaga rasm yuborish uchun) ----------
USERS_FILE = "users.txt"


def load_users():
    if not os.path.exists(USERS_FILE):
        return set()
    with open(USERS_FILE, "r") as f:
        return {int(x) for x in f.read().split() if x.strip().isdigit()}


known_users = load_users()


def track(user_id):
    """Mijozni ro'yxatga qo'shadi (admin qo'shilmaydi)."""
    if user_id == ADMIN_ID or user_id in known_users:
        return
    known_users.add(user_id)
    with open(USERS_FILE, "a") as f:
        f.write(f"{user_id}\n")


def menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton(BTN_ORDER))
    markup.add(types.KeyboardButton(BTN_EDIT), types.KeyboardButton(BTN_CANCEL))
    return markup


def reply_button(user_id):
    return types.InlineKeyboardButton("✍️ Javob yozish", callback_data=f"reply:{user_id}")


def admin_keyboard(user_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Qabul qilish", callback_data=f"accept:{user_id}"),
        types.InlineKeyboardButton("❌ Rad qilish", callback_data=f"reject:{user_id}"),
    )
    kb.add(reply_button(user_id))
    return kb


def make_header(user, title):
    header = f"{title}\n👤 {user.full_name}"
    if user.username:
        header += f" (@{user.username})"
    header += f"\n🆔 ID: {user.id}\n\n"
    return header


def send_to_admin(message, title):
    """Mijoz xabarini adminga tugmalar bilan alohida xabar qilib yuboradi."""
    header = make_header(message.from_user, title)
    kb = admin_keyboard(message.from_user.id)
    if message.content_type == 'text':
        sent = bot.send_message(ADMIN_ID, header + message.text, reply_markup=kb)
    else:
        sent = bot.copy_message(
            ADMIN_ID, message.chat.id, message.message_id,
            caption=header + (message.caption or ""),
            reply_markup=kb
        )
    return sent.message_id


def remove_admin_buttons(message_id):
    """Eski buyurtma xabaridagi tugmalarni o'chiradi."""
    try:
        bot.edit_message_reply_markup(ADMIN_ID, message_id, reply_markup=None)
    except Exception as e:
        print("Tugmani o'chirishda xato:", e)


@bot.message_handler(commands=['start'])
def start(message):
    track(message.from_user.id)
    user_state.pop(message.from_user.id, None)
    if message.from_user.id == ADMIN_ID:
        admin_state.pop("target", None)
    bot.send_message(
        message.chat.id,
        "Muslima's marketga xush kelibsiz! 🛍\n\n"
        "Buyurtma berish uchun pastdagi tugmani bosing.",
        reply_markup=menu()
    )


# ---------- Admin: javob yozish rejimini bekor qilish ----------
@bot.message_handler(commands=['cancel'], func=lambda m: m.from_user.id == ADMIN_ID)
def admin_cancel(message):
    admin_state.pop("target", None)
    bot.reply_to(message, "Bekor qilindi.")


# ---------- Admin: "Javob yozish" tugmasidan keyingi xabar ----------
@bot.message_handler(
    func=lambda m: (
        m.from_user.id == ADMIN_ID
        and "target" in admin_state
        and not (m.text or "").startswith("/")
    ),
    content_types=CONTENT
)
def admin_reply_mode(message):
    uid = admin_state.pop("target")
    try:
        bot.copy_message(uid, message.chat.id, message.message_id)
        bot.reply_to(message, "✅ Mijozga yuborildi.")
    except Exception as e:
        print("Mijozga yuborishda xato:", e)
        bot.reply_to(message, "⚠️ Mijozga yuborib bo'lmadi (botni bloklagan bo'lishi mumkin).")


# ---------- Admin: buyurtma xabariga reply ----------
@bot.message_handler(
    func=lambda m: m.from_user.id == ADMIN_ID and m.reply_to_message is not None,
    content_types=CONTENT
)
def from_admin(message):
    replied = message.reply_to_message
    text = replied.text or replied.caption or ""
    match = re.search(r"ID: (\d+)", text)

    if not match:
        bot.reply_to(message, "❗ Buyurtma xabariga reply qilib yozing.")
        return

    try:
        bot.copy_message(int(match.group(1)), message.chat.id, message.message_id)
        bot.reply_to(message, "✅ Mijozga yuborildi.")
    except Exception as e:
        print("Mijozga yuborishda xato:", e)
        bot.reply_to(message, "⚠️ Mijozga yuborib bo'lmadi (botni bloklagan bo'lishi mumkin).")


# ---------- Admin: rasm tashlasa -> hamma mijozlarga (tasdiqlash bilan) ----------
@bot.message_handler(
    func=lambda m: m.from_user.id == ADMIN_ID and m.reply_to_message is None,
    content_types=['photo']
)
def admin_photo(message):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Hammaga yuborish", callback_data=f"bc:{message.message_id}"),
        types.InlineKeyboardButton("❌ Bekor", callback_data="bc_no"),
    )
    bot.reply_to(
        message,
        f"📢 Bu rasm {len(known_users)} ta mijozga yuboriladi. Tasdiqlaysizmi?",
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda c: c.data == "bc_no" or c.data.startswith("bc:"))
def broadcast_buttons(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id)
        return

    chat_id = call.message.chat.id
    msg_id_of_prompt = call.message.message_id

    if call.data == "bc_no":
        bot.edit_message_text("❌ Yuborish bekor qilindi.", chat_id, msg_id_of_prompt)
        bot.answer_callback_query(call.id)
        return

    photo_msg_id = int(call.data.split(":")[1])
    bot.answer_callback_query(call.id, "Yuborilmoqda...")
    # Tugmalar yo'qolishi uchun (ikki marta bosilmasin)
    bot.edit_message_text("⏳ Yuborilmoqda...", chat_id, msg_id_of_prompt)

    sent = 0
    failed = 0
    for uid in list(known_users):
        try:
            bot.copy_message(uid, ADMIN_ID, photo_msg_id)
            sent += 1
        except Exception as e:
            print(f"{uid} ga yuborib bo'lmadi:", e)
            failed += 1
        time.sleep(0.05)   # Telegram limitiga tushmaslik uchun

    bot.edit_message_text(
        f"📢 Yuborildi: {sent} ta\n⚠️ Yuborilmadi: {failed} ta",
        chat_id, msg_id_of_prompt
    )


# ---------- Admin: inline tugmalar ----------
@bot.callback_query_handler(func=lambda c: c.data.startswith("reply:"))
def admin_reply_button(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id)
        return

    uid = int(call.data.split(":")[1])
    admin_state["target"] = uid
    bot.answer_callback_query(call.id)
    bot.send_message(
        ADMIN_ID,
        f"✍️ Mijozga javobingizni yozing (🆔 {uid}).\nBekor qilish: /cancel",
        reply_to_message_id=call.message.message_id
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith(("accept:", "reject:")))
def admin_buttons(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id)
        return

    action, uid = call.data.split(":")
    uid = int(uid)

    if action == "accept":
        user_text = "✅ Buyurtmangiz qabul qilindi!"
        status = "✅ Qabul qilindi"
    else:
        user_text = "❌ Afsuski, buyurtmangiz rad etildi."
        status = "❌ Rad etildi"

    try:
        bot.send_message(uid, user_text, reply_markup=menu())
    except Exception as e:
        print("Mijozga yuborishda xato:", e)
        bot.answer_callback_query(call.id, "Mijozga yuborib bo'lmadi", show_alert=True)
        return

    # Buyurtma yakunlandi, mijoz yangisini berishi mumkin
    if orders.get(uid) == call.message.message_id:
        orders.pop(uid)

    # Tugmalar o'rniga natija + "Javob yozish" tugmasi qoladi
    done_kb = types.InlineKeyboardMarkup()
    done_kb.add(types.InlineKeyboardButton(status, callback_data="done"))
    done_kb.add(reply_button(uid))
    try:
        bot.edit_message_reply_markup(
            call.message.chat.id, call.message.message_id, reply_markup=done_kb
        )
    except Exception as e:
        print("Tugmani almashtirishda xato:", e)

    bot.answer_callback_query(call.id, "Mijozga yuborildi")


@bot.callback_query_handler(func=lambda c: c.data == "done")
def done_button(call):
    bot.answer_callback_query(call.id, "Bu buyurtma yakunlangan")


# ---------- Mijoz tugmalari ----------
@bot.message_handler(func=lambda m: m.text == BTN_ORDER)
def btn_order(message):
    uid = message.from_user.id
    track(uid)
    if uid in orders:
        bot.send_message(
            message.chat.id,
            "Sizda faol buyurtma bor. Uni o'zgartirish yoki bekor qilish mumkin.",
            reply_markup=menu()
        )
        return
    user_state[uid] = "ordering"
    bot.send_message(message.chat.id, "Buyurtma qilmoqchi bo'lgan narsalaringizni yozing 👇")


@bot.message_handler(func=lambda m: m.text == BTN_EDIT)
def btn_edit(message):
    uid = message.from_user.id
    if uid not in orders:
        bot.send_message(message.chat.id, "Sizda faol buyurtma yo'q. Avval buyurtma bering.", reply_markup=menu())
        return
    user_state[uid] = "editing"
    bot.send_message(message.chat.id, "Yangi buyurtmangizni to'liq yozing 👇")


@bot.message_handler(func=lambda m: m.text == BTN_CANCEL)
def btn_cancel(message):
    uid = message.from_user.id
    user_state.pop(uid, None)

    if uid not in orders:
        bot.send_message(message.chat.id, "Sizda faol buyurtma yo'q.", reply_markup=menu())
        return

    order_msg_id = orders.pop(uid)
    remove_admin_buttons(order_msg_id)
    try:
        bot.send_message(
            ADMIN_ID,
            f"❌ Mijoz buyurtmani bekor qildi.\n🆔 ID: {uid}",
            reply_to_message_id=order_msg_id
        )
    except Exception as e:
        print("Adminga yuborishda xato:", e)

    bot.send_message(message.chat.id, "❌ Buyurtmangiz bekor qilindi.", reply_markup=menu())


# ---------- Mijozning buyurtma matni ----------
@bot.message_handler(
    func=lambda m: m.from_user.id != ADMIN_ID and user_state.get(m.from_user.id) in ("ordering", "editing"),
    content_types=CONTENT
)
def from_user(message):
    uid = message.from_user.id
    track(uid)
    editing = user_state.get(uid) == "editing"
    title = "✏️ O'zgartirilgan buyurtma" if editing else "📦 Yangi buyurtma"

    try:
        old_msg_id = orders.get(uid)
        orders[uid] = send_to_admin(message, title)
        if editing and old_msg_id:
            remove_admin_buttons(old_msg_id)   # eski buyurtma tugmalari o'chadi
        user_state.pop(uid, None)
        bot.send_message(
            message.chat.id,
            "⏳ Buyurtmangiz adminga yuborildi. Admin javobini kuting.",
            reply_markup=menu()
        )
    except Exception as e:
        print("Adminga yuborishda xato:", e)
        bot.send_message(message.chat.id, "⚠️ Hozir yuborib bo'lmadi. Keyinroq urinib ko'ring.")


# ---------- Admin tugmasiz va reply'siz yozsa ----------
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID, content_types=CONTENT)
def admin_no_reply(message):
    bot.reply_to(
        message,
        "❗ Mijozga javob berish uchun buyurtma tagidagi ✍️ Javob yozish tugmasini "
        "bosing yoki buyurtma xabariga Reply qiling.\n"
        "📢 Hammaga xabar yuborish uchun rasm tashlang."
    )


# ---------- Tugmasiz yozilgan mijoz xabari ----------
@bot.message_handler(func=lambda m: m.from_user.id != ADMIN_ID, content_types=CONTENT)
def fallback(message):
    track(message.from_user.id)
    bot.send_message(
        message.chat.id,
        "Buyurtma berish uchun pastdagi 🛍 tugmani bosing.",
        reply_markup=menu()
    )


# ---------- Flask ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        abort(403)
    update = telebot.types.Update.de_json(request.get_data().decode('UTF-8'))
    bot.process_new_updates([update])
    return 'ok', 200


@app.route('/')
def index():
    return "Bot ishlayapti"


if __name__ == '__main__':
    bot.remove_webhook()
    if WEBHOOK_URL:
        bot.set_webhook(url=f"{WEBHOOK_URL}/webhook", secret_token=WEBHOOK_SECRET)
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
    else:
        bot.infinity_polling()