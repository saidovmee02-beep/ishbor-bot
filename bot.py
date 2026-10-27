import os
import logging
import sqlite3
from datetime import datetime
from html import escape

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import markdown

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()  # e.g. @ishtop_vakansiyalar or -100...
DB_PATH = os.getenv("DB_PATH", "ishtop.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")
if not ADMIN_ID:
    raise RuntimeError("Set ADMIN_ID to your Telegram numeric user ID")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot)

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute("""
CREATE TABLE IF NOT EXISTS vacancies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    city TEXT NOT NULL,
    title TEXT NOT NULL,
    salary TEXT NOT NULL,
    phone TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
)
""")
conn.commit()

# Temporary form state: user_id -> {"step": ..., "data": {...}}
forms = {}

def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("🔎 Ish qidirish"), KeyboardButton("➕ E’lon berish"))
    kb.row(KeyboardButton("ℹ️ Bot haqida"))
    return kb

def city_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("Toshkent", "Buxoro", "Samarqand")
    kb.row("Andijon", "Farg‘ona", "Navoiy")
    kb.row("Boshqa", "⬅️ Bekor qilish")
    return kb

def admin_review_keyboard(vacancy_id):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve:{vacancy_id}"),
        InlineKeyboardButton("❌ Rad etish", callback_data=f"reject:{vacancy_id}")
    )
    return kb

def vacancy_text(row, include_id=True):
    prefix = f"<b>#{row['id']} · {escape(row['city'])}</b>\n" if include_id else f"<b>{escape(row['city'])}</b>\n"
    return (
        prefix +
        f"💼 <b>{escape(row['title'])}</b>\n"
        f"💰 Maosh: {escape(row['salary'])}\n"
        f"📞 Aloqa: {escape(row['phone'])}\n\n"
        f"📝 {escape(row['description'])}\n"
        f"🗓 {escape(row['created_at'][:10])}"
    )

async def begin_post(message: types.Message):
    forms[message.from_user.id] = {"step": "city", "data": {}}
    await message.answer("Qaysi shaharda ish bor?", reply_markup=city_keyboard())

@dp.message_handler(commands=["start", "help"])
async def start(message: types.Message):
    await message.answer(
        "👋 <b>IshTop</b> botiga xush kelibsiz!\n\n"
        "Bu yerda vakansiyalarni ko‘rishingiz yoki ish e’loni yuborishingiz mumkin.\n"
        "E’lonlar admin tekshiruvidan keyin kanalga joylanadi.",
        reply_markup=main_menu()
    )

@dp.message_handler(lambda m: m.text == "ℹ️ Bot haqida")
async def about(message: types.Message):
    await message.answer(
        "📌 <b>IshTop</b> — ish izlovchilar va ish beruvchilar uchun xizmat.\n\n"
        "• Vakansiyalarni ko‘rish — bepul\n"
        "• E’lon yuborish — admin tekshiradi\n"
        "• Pullik/ustuvor e’lonlar bo‘yicha admin bilan bog‘laning.",
        reply_markup=main_menu()
    )

@dp.message_handler(lambda m: m.text == "🔎 Ish qidirish")
async def search_jobs(message: types.Message):
    rows = conn.execute(
        "SELECT * FROM vacancies WHERE status='approved' ORDER BY id DESC LIMIT 10"
    ).fetchall()
    if not rows:
        await message.answer("Hozircha tasdiqlangan vakansiyalar yo‘q. Keyinroq yana tekshiring.", reply_markup=main_menu())
        return
    for row in rows:
        await message.answer(vacancy_text(row))
    await message.answer("Oxirgi 10 ta vakansiya ko‘rsatildi.", reply_markup=main_menu())

@dp.message_handler(lambda m: m.text == "➕ E’lon berish")
async def post_job(message: types.Message):
    await begin_post(message)

@dp.message_handler(lambda m: m.text == "⬅️ Bekor qilish")
async def cancel_form(message: types.Message):
    forms.pop(message.from_user.id, None)
    await message.answer("E’lon yuborish bekor qilindi.", reply_markup=main_menu())

@dp.message_handler(lambda m: m.from_user.id in forms, content_types=types.ContentTypes.TEXT)
async def collect_form(message: types.Message):
    uid = message.from_user.id
    state = forms.get(uid)
    if not state:
        return
    text = message.text.strip()
    if text == "⬅️ Bekor qilish":
        forms.pop(uid, None)
        await message.answer("Bekor qilindi.", reply_markup=main_menu())
        return

    step = state["step"]
    data = state["data"]

    if step == "city":
        data["city"] = text
        state["step"] = "title"
        await message.answer("Lavozim yoki ish nomini yozing. Masalan: Sotuvchi, Haydovchi, Payvandchi.")
    elif step == "title":
        if len(text) < 2:
            await message.answer("Iltimos, ish nomini aniqroq yozing.")
            return
        data["title"] = text[:100]
        state["step"] = "salary"
        await message.answer("Maoshni yozing. Masalan: 3 000 000 so‘m yoki kelishiladi.")
    elif step == "salary":
        data["salary"] = text[:80]
        state["step"] = "phone"
        await message.answer("Aloqa telefon raqamini yozing.")
    elif step == "phone":
        if len(text) < 7:
            await message.answer("Telefon raqami to‘liq ko‘rinmayapti. Qayta kiriting.")
            return
        data["phone"] = text[:40]
        state["step"] = "description"
        await message.answer("Ish shartlari, grafik va talablarni qisqacha yozing.")
    elif step == "description":
        data["description"] = text[:1200]
        created = datetime.now().strftime("%Y-%m-%d %H:%M")
        cur = conn.execute(
            "INSERT INTO vacancies (user_id, city, title, salary, phone, description, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (uid, data["city"], data["title"], data["salary"], data["phone"], data["description"], created)
        )
        conn.commit()
        vacancy_id = cur.lastrowid
        row = conn.execute("SELECT * FROM vacancies WHERE id=?", (vacancy_id,)).fetchone()
        forms.pop(uid, None)
        await message.answer("✅ E’loningiz admin tekshiruviga yuborildi. Tasdiqlansa, kanalga joylanadi.", reply_markup=main_menu())
        try:
            await bot.send_message(
                ADMIN_ID,
                "🆕 <b>Yangi vakansiya tekshiruv uchun</b>\n\n" + vacancy_text(row) +
                f"\n\n👤 Yuboruvchi ID: <code>{uid}</code>",
                reply_markup=admin_review_keyboard(vacancy_id)
            )
        except Exception:
            logging.exception("Could not send vacancy to admin")

@dp.callback_query_handler(lambda c: c.data and (c.data.startswith("approve:") or c.data.startswith("reject:")))
async def review_vacancy(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Bu amal faqat admin uchun.", show_alert=True)
        return

    action, raw_id = callback.data.split(":")
    vacancy_id = int(raw_id)
    row = conn.execute("SELECT * FROM vacancies WHERE id=?", (vacancy_id,)).fetchone()
    if not row:
        await callback.answer("E’lon topilmadi.", show_alert=True)
        return
    if row["status"] != "pending":
        await callback.answer("Bu e’lon oldin ko‘rib chiqilgan.")
        return

    if action == "approve":
        conn.execute("UPDATE vacancies SET status='approved' WHERE id=?", (vacancy_id,))
        conn.commit()
        approved = conn.execute("SELECT * FROM vacancies WHERE id=?", (vacancy_id,)).fetchone()
        posted = False
        if CHANNEL_ID:
            try:
                await bot.send_message(CHANNEL_ID, vacancy_text(approved, include_id=False))
                posted = True
            except Exception:
                logging.exception("Could not post to channel")
        try:
            await bot.send_message(row["user_id"], "✅ E’loningiz tasdiqlandi." + (" Kanalga joylandi." if posted else ""))
        except Exception:
            pass
        await callback.message.edit_reply_markup()
        await callback.message.answer("✅ E’lon tasdiqlandi." + (" Kanalga joylandi." if posted else " Kanal sozlanmagan yoki joylashda xatolik bo‘ldi."))
        await callback.answer("Tasdiqlandi")
    else:
        conn.execute("UPDATE vacancies SET status='rejected' WHERE id=?", (vacancy_id,))
        conn.commit()
        try:
            await bot.send_message(row["user_id"], "❌ E’loningiz hozircha rad etildi. Ma’lumotlarni tekshirib, qayta yuborishingiz mumkin.")
        except Exception:
            pass
        await callback.message.edit_reply_markup()
        await callback.message.answer("❌ E’lon rad etildi.")
        await callback.answer("Rad etildi")

@dp.message_handler(commands=["stats"])
async def stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    users = conn.execute("SELECT COUNT(DISTINCT user_id) AS n FROM vacancies").fetchone()["n"]
    pending = conn.execute("SELECT COUNT(*) AS n FROM vacancies WHERE status='pending'").fetchone()["n"]
    approved = conn.execute("SELECT COUNT(*) AS n FROM vacancies WHERE status='approved'").fetchone()["n"]
    await message.answer(f"📊 <b>IshTop statistikasi</b>\nE’lon yuborgan foydalanuvchilar: {users}\nKutilmoqda: {pending}\nTasdiqlangan: {approved}")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
