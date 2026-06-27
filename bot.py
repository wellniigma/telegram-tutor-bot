import asyncio
import logging
import os
import json
import random
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
ADMIN_ID = 810699186
PAYMENT_URL = "https://example.com"
DAY_QUOTES = [
    "Даже если кажется, что ничего не запоминается — мозг работает",
    "Отдых — часть подготовки, а не её враг",
    "Если никто в тебя не верит — удиви даже себя",
    "Не обязательно двигаться быстро. Главное -- не останавливаться",
    "А мы за стадом не идём. Мы его пасём епт",
    "Господи, дай твоей сотке случиться, это будет оооч вайбово",
    "Ни шагу вперед",
    "Писать пробные на 90+ это нишево",
    "Ты определенно точно тупо поступишь в вуз мечты",
    "Много хочешь и правильно",
]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

google_credentials = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
creds = Credentials.from_service_account_info(google_credentials, scopes=SCOPES)
gc = gspread.authorize(creds)

spreadsheet = gc.open_by_key(SPREADSHEET_ID)

attendance_sheet = spreadsheet.worksheet("Посещаемость")
balances_sheet = spreadsheet.worksheet("Балансы")
settings_sheet = spreadsheet.worksheet("Настройки")
archive_sheet = spreadsheet.worksheet("Архив")


def find_student(telegram_id: int):
    rows = attendance_sheet.get_all_records()

    for row in rows:
        if str(row.get("ID ученика", "")).strip() == str(telegram_id):
            return row

    return None


def get_lesson_price(group_name, duration):
    rows = settings_sheet.get_all_records()

    for row in rows:
        if str(row.get("Формат", "")).strip() == str(group_name).strip():
            value = row.get(str(duration))

            if value not in ("", None, "-"):
                return int(value)

    return 0


def get_student_balance(telegram_id):
    rows = balances_sheet.get_all_records()

    for row in rows:
        if str(row.get("ID ученика", "")).strip() == str(telegram_id):
            value = row.get("Баланс", 0)

            if value in ("", None):
                return 0

            return float(value)

    return 0


def format_money(amount):
    amount = int(float(amount))
    return f"{amount:,}".replace(",", " ") + " ₽"


WEEKDAYS = {
    "понедельник": 0,
    "вторник": 1,
    "среда": 2,
    "четверг": 3,
    "пятница": 4,
    "суббота": 5,
    "воскресенье": 6,
}


def get_current_week_monday():
    today = datetime.now()
    return today - timedelta(days=today.weekday())


def get_lesson_date(column_name):
    name = str(column_name).strip().lower()

    if name in WEEKDAYS:
        monday = get_current_week_monday()
        lesson_date = monday + timedelta(days=WEEKDAYS[name])
        return lesson_date.strftime("%d.%m.%Y")

    return str(column_name)

def build_history(student):
    lessons = []

    group_name = student.get("Группа")
    duration = student.get("Длительность")

    lesson_price = get_lesson_price(group_name, duration)

    chargeable_total = 0

    skip_columns = [
        "ID ученика",
        "Имя ученика",
        "Группа",
        "Длительность",
        "Макс. кол-во занятий",
    ]

    for column, value in student.items():
        if column in skip_columns:
            continue

        value = str(value).strip()

        if value == "":
            continue

        if value == "1":
            lessons.append(
                {
                    "date": get_lesson_date(column),
                    "title": "Проведено",
                    "price": lesson_price,
                    "need_pay": True,
                }
            )
            chargeable_total += lesson_price

        elif value == "$":
            lessons.append(
                {
                    "date": get_lesson_date(column),
                    "title": "Дополнительное занятие / перенос",
                    "price": lesson_price,
                    "need_pay": True,
                }
            )
            chargeable_total += lesson_price

        elif value == "-":
            lessons.append(
                {
                   "date": get_lesson_date(column),
                    "title": "Поздняя отмена",
                    "price": lesson_price,
                    "need_pay": True,
                }
            )
            chargeable_total += lesson_price

        elif value == "0":
            lessons.append(
                {
                   "date": get_lesson_date(column),
                    "title": "Отмена заранее",
                    "price": 0,
                    "need_pay": False,
                }
            )

    return lessons, chargeable_total

def archive_current_week():
    rows = attendance_sheet.get_all_records()
    headers = attendance_sheet.row_values(1)

    archive_rows = []
    cells_to_clear = []

    created_at = datetime.now().strftime("%d.%m.%Y %H:%M")

    for row_number, row in enumerate(rows, start=2):
        student_id = row.get("ID ученика", "")
        name = row.get("Имя ученика", "")
        group = row.get("Группа", "")
        duration = row.get("Длительность", "")
        lesson_price = get_lesson_price(group, duration)

        for col_number, header in enumerate(headers, start=1):
            header_clean = str(header).strip()
            day_name = header_clean.lower()

            if day_name not in WEEKDAYS:
                continue

            mark = str(row.get(header_clean, "")).strip()

            if mark == "":
                continue

            if mark == "1":
                lesson_type = "Проведено"
                price = lesson_price
            elif mark == "$":
                lesson_type = "Дополнительное занятие / перенос"
                price = lesson_price
            elif mark == "-":
                lesson_type = "Поздняя отмена"
                price = lesson_price
            elif mark == "0":
                lesson_type = "Отмена заранее"
                price = 0
            else:
                continue

            archive_rows.append([
                student_id,
                name,
                group,
                duration,
                get_lesson_date(day_name),
                day_name,
                mark,
                price,
                lesson_type,
                created_at
            ])

            cells_to_clear.append((row_number, col_number))

    if archive_rows:
        archive_sheet.append_rows(archive_rows, value_input_option="USER_ENTERED")

    for row_number, col_number in cells_to_clear:
        attendance_sheet.update_cell(row_number, col_number, "")

    return len(archive_rows)


def admin_menu():
    kb = InlineKeyboardBuilder()

    kb.button(text="👥 Все ученики", callback_data="admin_students")
    kb.button(text="➕ Добавить ученика", callback_data="add_student")

    kb.button(text="📢 Рассылка", callback_data="broadcast_start")
    kb.button(text="👥 Список должников", callback_data="admin_debts")

    kb.button(text="📊 Статистика", callback_data="admin_stats")
    kb.button(text="📂 Перенести неделю в Архив", callback_data="archive_week")

    kb.button(text="🏠 В главное меню", callback_data="menu")

    kb.adjust(2, 2, 2, 1)

    return kb.as_markup()


def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Прошедшие занятия", callback_data="history")
    kb.button(text="💳 Оплатить занятия", callback_data="payment")
    kb.button(text="💌 Цитата дня", callback_data="quote_day")
    kb.adjust(1)
    return kb.as_markup()


def back_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 В главное меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def get_main_text():
    return (
        "Привет! Теперь у тебя есть личный кабинет. Взрослый момент\n\n"
        "Я очень полезный бот, который поможет:\n\n"
        "📝 Посмотреть историю занятий\n"
        "💳 Проверить баланс и оплатить занятия\n"
        "📨 Получать уведомления о занятиях, оплате и важной информации от Алиюшки"
    )


@dp.message(Command("start"))
async def start(message: Message):
    student = find_student(message.from_user.id)

    if not student:
        await message.answer(
            "Босс пока не познакомил меня с вами 🥺\n\n"
            f"Ваш ID: {message.from_user.id}\n\n"
            "Свяжитесь с Алиюшкой",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    await message.answer(
        get_main_text(),
        reply_markup=main_menu()
    )


@dp.callback_query(F.data == "menu")
async def menu(callback: CallbackQuery):
    await callback.message.edit_text(get_main_text(), reply_markup=main_menu())
    await callback.answer()


LESSONS_PER_PAGE = 4


LESSONS_PER_PAGE = 4


def build_history_text(user_id, page=0):
    student = find_student(user_id)

    if not student:
        return (
            "Босс пока не познакомил меня с вами 🥺\n\n"
            f"Ваш ID: {user_id}\n\n"
            "Свяжитесь с Алиюшкой"
        ), back_menu()

    lessons, chargeable_total = build_history(student)
    balance = get_student_balance(user_id)
    debt = max(chargeable_total - balance, 0)

    if not lessons:
        return "👩🏻‍💻 История занятий\n\nПока тут пусто.", back_menu()

    remaining_balance = balance
    prepared = []

    for item in lessons:
        title = item["title"]

        if title == "Отмена заранее":
            title = "Отмена заранее, респект"
        elif title == "Дополнительное занятие / перенос":
            title = "Доп. занятие / перенос"

        if item["need_pay"]:
            if remaining_balance >= item["price"]:
                payment_status = "🟢 Оплачено"
                remaining_balance -= item["price"]
            else:
                payment_status = "🟡 Ждёт оплаты"
        else:
            payment_status = "⚪ Не оплачивается"

        prepared.append({
            **item,
            "title": title,
            "payment_status": payment_status
        })

    total_pages = max((len(prepared) - 1) // LESSONS_PER_PAGE + 1, 1)
    page = max(0, min(page, total_pages - 1))

    start = page * LESSONS_PER_PAGE
    end = start + LESSONS_PER_PAGE
    page_items = prepared[start:end]

    text = "👩🏻‍💻 История занятий\n\n━━━━━━━━━━━━━━\n\n"

    for item in page_items:
        text += (
            f"{item['payment_status']}\n\n"
            f"{item['date']} · {item['title']}\n"
            f"{format_money(item['price'])}\n\n"
            "━━━━━━━━━━━━━━\n\n"
        )

    text += (
        f"💳 Баланс: {format_money(balance)}\n"
        f"🧾 К оплате: {format_money(debt)}\n\n"
        f"── Страница {page + 1} / {total_pages} ──"
    )

    kb = InlineKeyboardBuilder()

    kb.button(text="⬅️", callback_data=f"history_page:{page - 1}")
    kb.button(text="➡️", callback_data=f"history_page:{page + 1}")
    kb.button(text="🔝 В начало списка", callback_data="history_page:0")
    kb.button(text="🏠 В главное меню", callback_data="menu")

    kb.adjust(2, 1, 1)

    return text, kb.as_markup()

@dp.callback_query(F.data == "quote_day")
async def quote_day(callback: CallbackQuery):
    quote = random.choice(DAY_QUOTES)

    await callback.message.edit_text(
        f"💌 Цитата дня\n\n"
        f"{quote}",
        reply_markup=main_menu()
    )

    await callback.answer()

@dp.callback_query(F.data == "history")
async def history(callback: CallbackQuery):
    text, keyboard = build_history_text(callback.from_user.id, 0)

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("history_page:"))
async def history_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])

    text, keyboard = build_history_text(callback.from_user.id, page)

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()

@dp.callback_query(F.data == "payment")
async def payment(callback: CallbackQuery):
    student = find_student(callback.from_user.id)

    if not student:
        await callback.message.edit_text(
            "Босс пока не познакомил меня с вами 🥺\n\n"
            f"Ваш ID: {callback.from_user.id}\n\n"
            "Свяжитесь с Алиюшкой",
            reply_markup=back_menu(),
        )
        await callback.answer()
        return

    lessons, chargeable_total = build_history(student)
    balance = get_student_balance(callback.from_user.id)
    debt = max(chargeable_total - balance, 0)

    text = "💳 Оплатить занятия\n\n"

    if debt <= 0:
        text += (
            "Все четко, долгов нет\n\n"
            f"Ваш баланс: {format_money(balance)}"
        )
    else:
        text += "Ожидают оплаты:\n\n"

        remaining_balance = balance
        number = 1

        for item in lessons:
            if not item["need_pay"]:
                continue

            if remaining_balance >= item["price"]:
                remaining_balance -= item["price"]
                continue

            text += (
                f"{number}. {item['date']} · "
                f"{item['title']} · "
                f"{format_money(item['price'])}\n"
            )
            number += 1

        text += f"\nВаш баланс: {format_money(balance)}"
        text += f"\nК оплате: {format_money(debt)}"

    kb = InlineKeyboardBuilder()

    kb.button(
        text="💳 Пополнить счёт (указать сумму)",
        callback_data="pay_custom",
    )

    if debt > 0:
        kb.button(
            text=f"💳 Пополнить счёт на {format_money(debt)}",
            callback_data=f"pay_debt:{int(debt)}",
        )

    kb.button(text="🏠 В главное меню", callback_data="menu")
    kb.adjust(1)

    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()

waiting_for_amount = set()
waiting_for_balance = {}
waiting_for_new_student = {}
waiting_for_edit_student = {}
waiting_for_broadcast = set()

@dp.callback_query(F.data == "pay_custom")
async def pay_custom(callback: CallbackQuery):
    waiting_for_amount.add(callback.from_user.id)

    await callback.message.edit_text(
        "Введите сумму, на которую хотите пополнить баланс.",
        reply_markup=back_menu(),
    )

    await callback.answer()

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Эта команда доступна только преподавателю.")
        return

    await message.answer(
        "⚙️ Панель преподавателя\n\n"
        "Здесь можно управлять ботом.",
        reply_markup=admin_menu()
    )

@dp.callback_query(F.data == "admin_debts")
async def admin_debts(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    rows = attendance_sheet.get_all_records()

    text = "👥 Список должников\n\n"
    has_debts = False

    for student in rows:
        student_id = student.get("ID ученика")
        name = student.get("Имя ученика", "Без имени")

        if not student_id:
            continue

        lessons, chargeable_total = build_history(student)
        balance = get_student_balance(student_id)
        debt = max(chargeable_total - balance, 0)

        if debt > 0:
            has_debts = True
            text += (
                f"🔸 {name}\n"
                f"ID: {student_id}\n"
                f"Долг: {format_money(debt)}\n\n"
            )

    if not has_debts:
        text += "Сейчас должников нет 🎉"

    await callback.message.edit_text(
        text,
        reply_markup=admin_menu()
    )

    await callback.answer()

@dp.callback_query(F.data == "archive_week")
async def archive_week(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, перенести", callback_data="archive_week_confirm")
    kb.button(text="🏠 В главное меню", callback_data="menu")
    kb.adjust(1)

    await callback.message.edit_text(
        "Вы точно хотите перенести текущую неделю в Архив?\n\n"
        "После этого отметки в листе «Посещаемость» будут очищены.",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(F.data == "archive_week_confirm")
async def archive_week_confirm(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    count = archive_current_week()

    await callback.message.edit_text(
        "📂 Неделя перенесена в Архив.\n\n"
        f"Записей добавлено: {count}\n\n"
        "Лист «Посещаемость» очищен для новой недели.",
        reply_markup=admin_menu()
    )

    await callback.answer()

@dp.callback_query(F.data.startswith("balance_menu:"))
async def balance_menu(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    student_id = callback.data.split(":")[1]

    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Пополнить баланс", callback_data=f"balance_action:{student_id}:plus")
    kb.button(text="➖ Списать с баланса", callback_data=f"balance_action:{student_id}:minus")
    kb.button(text="⬅️ Назад к ученику", callback_data=f"student:{student_id}")
    kb.adjust(1)

    await callback.message.edit_text(
        "Выберите действие с балансом:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("balance_action:"))
async def balance_action(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    _, student_id, action = callback.data.split(":")

    waiting_for_balance[callback.from_user.id] = {
        "student_id": student_id,
        "action": action
    }

    if action == "plus":
        text = "Введите сумму, на которую нужно пополнить баланс."
    else:
        text = "Введите сумму, которую нужно списать с баланса."

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад к ученику", callback_data=f"student:{student_id}")
    kb.adjust(1)

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )

    await callback.answer()

def add_student_to_sheets(data):
    headers = attendance_sheet.row_values(1)
    rows = attendance_sheet.get_all_values()

    memo_row = None

    for index, row in enumerate(rows, start=1):
        row_text = " ".join([str(cell).strip() for cell in row])
        if "Памятка" in row_text:
            memo_row = index
            break

    if memo_row is None:
        memo_row = len(rows) + 1

    target_row = None

    for index in range(2, memo_row):
        row = rows[index - 1] if index - 1 < len(rows) else []
        student_id = row[0] if len(row) > 0 else ""

        if str(student_id).strip() == "":
            target_row = index
            break

    if target_row is None:
        target_row = memo_row

    new_attendance_row = []

    for header in headers:
        header = str(header).strip()

        if header == "ID ученика":
            new_attendance_row.append(data["telegram_id"])
        elif header == "Имя ученика":
            new_attendance_row.append(data["name"])
        elif header == "Группа":
            new_attendance_row.append(data["group"])
        elif header == "Длительность":
            new_attendance_row.append(data["duration"])
        elif header == "Макс. кол-во занятий":
            new_attendance_row.append("")
        else:
            new_attendance_row.append("")

    attendance_sheet.update(
        f"A{target_row}:L{target_row}",
        [new_attendance_row[:12]],
        value_input_option="USER_ENTERED"
    )

    balances_sheet.append_row(
        [data["telegram_id"], data["name"], 0],
        value_input_option="USER_ENTERED"
    )
    
@dp.callback_query(F.data == "add_student")
async def add_student_start(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    waiting_for_new_student[callback.from_user.id] = {"step": "name"}

    await callback.message.edit_text(
        "➕ Добавление ученика\n\n"
        "Шаг 1 из 4.\n"
        "Введите имя ученика:"
    )

    await callback.answer("Начинаем добавление ученика")

def update_student_data(student_id, field, new_value):
    attendance_rows = attendance_sheet.get_all_records()
    balance_rows = balances_sheet.get_all_records()

    attendance_columns = {
        "telegram_id": 1,
        "name": 2,
        "group": 3,
        "duration": 4,
    }

    balance_columns = {
        "telegram_id": 1,
        "name": 2,
    }

    for index, row in enumerate(attendance_rows, start=2):
        if str(row.get("ID ученика", "")).strip() == str(student_id):
            attendance_sheet.update_cell(index, attendance_columns[field], new_value)
            break

    if field in balance_columns:
        for index, row in enumerate(balance_rows, start=2):
            if str(row.get("ID ученика", "")).strip() == str(student_id):
                balances_sheet.update_cell(index, balance_columns[field], new_value)
                break

@dp.callback_query(F.data.startswith("edit_name:"))
async def edit_name(callback: CallbackQuery):
    student_id = callback.data.split(":")[1]
    waiting_for_edit_student[callback.from_user.id] = {
        "student_id": student_id,
        "field": "name"
    }
    await callback.message.edit_text("Введите новое имя ученика:")
    await callback.answer()


@dp.callback_query(F.data.startswith("edit_group:"))
async def edit_group(callback: CallbackQuery):
    student_id = callback.data.split(":")[1]
    waiting_for_edit_student[callback.from_user.id] = {
        "student_id": student_id,
        "field": "group"
    }
    await callback.message.edit_text("Введите новую группу:")
    await callback.answer()


@dp.callback_query(F.data.startswith("edit_duration:"))
async def edit_duration(callback: CallbackQuery):
    student_id = callback.data.split(":")[1]
    waiting_for_edit_student[callback.from_user.id] = {
        "student_id": student_id,
        "field": "duration"
    }
    await callback.message.edit_text("Введите новую длительность: 60 или 90")
    await callback.answer()


@dp.callback_query(F.data.startswith("edit_id:"))
async def edit_id(callback: CallbackQuery):
    student_id = callback.data.split(":")[1]
    waiting_for_edit_student[callback.from_user.id] = {
        "student_id": student_id,
        "field": "telegram_id"
    }
    await callback.message.edit_text("Введите новый Telegram ID ученика:")
    await callback.answer()

@dp.callback_query(F.data == "broadcast_start")
async def broadcast_start(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    waiting_for_broadcast.add(callback.from_user.id)

    await callback.message.edit_text(
        "Введите текст рассылки для всех учеников:"
    )

    await callback.answer()

@dp.message()
async def handle_custom_amount(message: Message):
    text = message.text.strip()

    if message.from_user.id in waiting_for_broadcast:
        rows = attendance_sheet.get_all_records()

        sent = 0
        failed = 0

        for student in rows:
            student_id = student.get("ID ученика")

            if not student_id:
                continue

            try:
                await bot.send_message(
                    int(student_id),
                    f"📢 Сообщение от босса\n\n{text}"
                )
                sent += 1
            except Exception:
                failed += 1

        waiting_for_broadcast.discard(message.from_user.id)

        await message.answer(
            "Рассылка завершена ✅\n\n"
            f"Отправлено: {sent}\n"
            f"Не удалось отправить: {failed}",
            reply_markup=admin_menu()
        )
        return

    if message.from_user.id in waiting_for_edit_student:
        data = waiting_for_edit_student[message.from_user.id]
        student_id = data["student_id"]
        field = data["field"]

        if field in ("telegram_id", "duration") and not text.isdigit():
            await message.answer("Введите число.")
            return

        if field == "duration" and text not in ("60", "90"):
            await message.answer("Длительность должна быть 60 или 90.")
            return

        update_student_data(student_id, field, text)

        waiting_for_edit_student.pop(message.from_user.id, None)

        await message.answer(
            "Данные ученика обновлены ✅",
            reply_markup=admin_menu()
        )
        return

    if message.from_user.id in waiting_for_new_student:
        data = waiting_for_new_student[message.from_user.id]
        step = data.get("step")

        if step == "name":
            data["name"] = text
            data["step"] = "telegram_id"
            await message.answer("Введите Telegram ID ученика:")
            return

        if step == "telegram_id":
            if not text.isdigit():
                await message.answer("ID должен быть числом. Введи Telegram ID ученика:")
                return

            data["telegram_id"] = text
            data["step"] = "group"
            await message.answer("Введите группу ученика: Перс / Пара / A / B / C / D / E / F / G")
            return

        if step == "group":
            data["group"] = text
            data["step"] = "duration"
            await message.answer("Введите длительность занятия: 60 или 90")
            return

        if step == "duration":
            if text not in ("60", "90"):
                await message.answer("Длительность должна быть 60 или 90, мэм. Введи ещё раз:")
                return

            data["duration"] = text

            add_student_to_sheets(data)

            waiting_for_new_student.pop(message.from_user.id, None)

            await message.answer(
                "Ученик успешно добавлен ✅\n\n"
                f"Имя: {data['name']}\n"
                f"ID: {data['telegram_id']}\n"
                f"Группа: {data['group']}\n"
                f"Длительность: {data['duration']}",
                reply_markup=admin_menu()
            )
            return

    text_for_amount = text.replace(" ", "").replace(",", ".")

    if message.from_user.id in waiting_for_balance:
        data = waiting_for_balance[message.from_user.id]

        if not text_for_amount.isdigit():
            await message.answer(
                "Пожалуйста, введи сумму числом. Например: 2400",
                reply_markup=back_menu(),
            )
            return

        amount = int(text_for_amount)

        if data["action"] == "minus":
            amount = -amount

        new_balance = update_student_balance(data["student_id"], amount)

        waiting_for_balance.pop(message.from_user.id, None)

        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Вернуться к ученику", callback_data=f"student:{data['student_id']}")
        kb.button(text="🏠 В админку", callback_data="admin_back")
        kb.adjust(1)

        await message.answer(
            "Баланс изменён ✅\n\n"
            f"Новый баланс: {format_money(new_balance)}",
            reply_markup=kb.as_markup()
        )
        return

    if message.from_user.id not in waiting_for_amount:
        return

    if not text_for_amount.isdigit():
        await message.answer(
            "Пожалуйста, введите сумму числом. Например: 2400",
            reply_markup=back_menu(),
        )
        return

    amount = int(text_for_amount)

    waiting_for_amount.remove(message.from_user.id)

    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оплатить", url=PAYMENT_URL)
    kb.button(text="✅ Миссия выполнена", callback_data=f"paid_request:{amount}")
    kb.button(text="🏠 В главное меню", callback_data="menu")
    kb.adjust(1)

    await message.answer(
        "Спасибо за доверие 💗\n\n"
        "Оплата доступна по кнопке ниже ⬇️\n\n"
        f"Сумма: {format_money(amount)}\n\n"
        "После оплаты нажмите кнопку «Миссия выполнена».",
        reply_markup=kb.as_markup(),
    )

@dp.callback_query(F.data.startswith("pay_debt:"))
async def pay_debt(callback: CallbackQuery):
    amount = callback.data.split(":")[1]

    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оплатить", url=PAYMENT_URL)
    kb.button(text="✅ Миссия выполнена", callback_data=f"paid_request:{amount}")
    kb.button(text="🏠 В главное меню", callback_data="menu")
    kb.adjust(1)

    await callback.message.edit_text(
        "Спасибо за доверие 💗\n\n"
        "Оплата доступна по кнопке ниже ⬇️\n\n"
        f"Сумма: {format_money(amount)}\n\n"
         "После оплаты нажми кнопку «Миссия выполнена».",
        reply_markup=kb.as_markup(),
    )

    await callback.answer()

@dp.callback_query(F.data.startswith("paid_request:"))
async def paid_request(callback: CallbackQuery):
    amount = int(callback.data.split(":")[1])
    student = find_student(callback.from_user.id)

    if not student:
        await callback.answer("Ученик не найден, потерян", show_alert=True)
        return

    student_name = student.get("Имя ученика", "Без имени")

    admin_kb = InlineKeyboardBuilder()
    admin_kb.button(
        text="✅ Подтвердить",
        callback_data=f"approve_payment:{callback.from_user.id}:{amount}",
    )
    admin_kb.button(
        text="❌ Отклонить",
        callback_data=f"reject_payment:{callback.from_user.id}:{amount}",
    )
    admin_kb.adjust(1)

    await bot.send_message(
        ADMIN_ID,
        "💰 Новая заявка на подтверждение оплаты\n\n"
        f"Ученик: {student_name}\n"
        f"ID: {callback.from_user.id}\n"
        f"Сумма: {format_money(amount)}",
        reply_markup=admin_kb.as_markup(),
    )

    await callback.message.edit_text(
        "Спасибо! 💗\n\n"
        "Запрос на подтверждение оплаты отправлен боссу\n\n",
        reply_markup=back_menu(),
    )

    await callback.answer()

def update_student_balance(telegram_id, amount):
    rows = balances_sheet.get_all_records()

    for index, row in enumerate(rows, start=2):
        if str(row.get("ID ученика", "")).strip() == str(telegram_id):
            current_balance = row.get("Баланс", 0)

            if current_balance in ("", None):
                current_balance = 0

            new_balance = float(current_balance) + float(amount)
            balances_sheet.update_cell(index, 3, new_balance)
            return new_balance

    student = find_student(telegram_id)
    student_name = student.get("Имя ученика", "") if student else ""

    balances_sheet.append_row(
        [telegram_id, student_name, float(amount)],
        value_input_option="USER_ENTERED",
    )

    return float(amount)


@dp.callback_query(F.data.startswith("approve_payment:"))
async def approve_payment(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    _, student_id, amount = callback.data.split(":")
    student_id = int(student_id)
    amount = int(amount)

    new_balance = update_student_balance(student_id, amount)

    await bot.send_message(
        student_id,
        "Оплата подтверждена ✅\n\n",
        "Ты вообще молодец",
        reply_markup=back_menu(),
    )

    await callback.message.edit_text(
        "✅ Оплата подтверждена\n\n"
        f"ID ученика: {student_id}\n"
        f"Сумма: {format_money(amount)}\n"
        f"Новый баланс: {format_money(new_balance)}"
    )

    await callback.answer()

@dp.callback_query(F.data.startswith("reject_payment:"))
async def reject_payment(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    _, student_id, amount = callback.data.split(":")
    student_id = int(student_id)
    amount = int(amount)

    await bot.send_message(
        student_id,
        "Платёж пока не подтверждён.\n\n"
        "Если произошла ошибка, свяжитесь с преподавателем.",
        reply_markup=back_menu(),
    )

    await callback.message.edit_text(
        "❌ Оплата отклонена\n\n"
        f"ID ученика: {student_id}\n"
        f"Сумма: {format_money(amount)}"
    )

    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    rows = attendance_sheet.get_all_records()

    total_students = 0
    total_lessons = 0
    total_chargeable = 0
    total_debt = 0

    for student in rows:
        student_id = student.get("ID ученика")

        if not student_id:
            continue

        total_students += 1

        lessons, chargeable_total = build_history(student)
        balance = get_student_balance(student_id)
        debt = max(chargeable_total - balance, 0)

        total_lessons += len(lessons)
        total_chargeable += chargeable_total
        total_debt += debt

    text = (
        "📊 Статистика\n\n"
        f"👥 Учеников: {total_students}\n"
        f"📚 Занятий за текущую неделю: {total_lessons}\n"
        f"💰 Начислено: {format_money(total_chargeable)}\n"
        f"❗ Общий долг: {format_money(total_debt)}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=admin_menu()
    )

    await callback.answer()

@dp.callback_query(F.data == "admin_students")
async def admin_students(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    rows = attendance_sheet.get_all_records()

    kb = InlineKeyboardBuilder()

    for student in rows:
        student_id = student.get("ID ученика")
        name = student.get("Имя ученика", "Без имени")

        if not student_id:
            continue

        kb.button(
            text=f"👤 {name}",
            callback_data=f"student:{student_id}"
        )

    kb.button(text="🏠 В админку", callback_data="admin_back")
    kb.adjust(1)

    await callback.message.edit_text(
        "👥 Выберите ученика:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()

@dp.callback_query(F.data.startswith("student:"))
async def student_card(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    student_id = callback.data.split(":")[1]
    student = find_student(student_id)

    if not student:
        await callback.message.edit_text(
            "Ученик не найден.",
            reply_markup=admin_menu()
        )
        await callback.answer()
        return

    name = student.get("Имя ученика", "Без имени")
    group = student.get("Группа", "")
    duration = student.get("Длительность", "")

    lessons, chargeable_total = build_history(student)
    balance = get_student_balance(student_id)
    debt = max(chargeable_total - balance, 0)

    text = (
        "👤 Карточка ученика\n\n"
        f"Имя: {name}\n"
        f"ID: {student_id}\n"
        f"Группа: {group}\n"
        f"Длительность: {duration} мин.\n\n"
        f"📚 Занятий на этой неделе: {len(lessons)}\n"
        f"💳 Баланс: {format_money(balance)}\n"
        f"❗ Долг: {format_money(debt)}"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Отметить посещение", callback_data=f"mark_attendance:{student_id}")
    kb.button(text="💰 Изменить баланс", callback_data=f"balance_menu:{student_id}")
    kb.button(text="✏️ Редактировать", callback_data=f"edit_student:{student_id}")
    kb.button(text="🗑 Удалить ученика", callback_data=f"delete_student:{student_id}")
    kb.button(text="⬅️ К списку учеников", callback_data="admin_students")
    kb.button(text="🏠 В админку", callback_data="admin_back")
    kb.adjust(1)

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    await callback.message.edit_text(
        "⚙️ Панель преподавателя\n\n"
        "Здесь можно управлять ботом.",
        reply_markup=admin_menu()
    )

    await callback.answer()

@dp.callback_query(F.data.startswith("mark_attendance:"))
async def mark_attendance(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    student_id = callback.data.split(":")[1]

    kb = InlineKeyboardBuilder()

    for day in WEEKDAYS.keys():
        kb.button(
            text=day.capitalize(),
            callback_data=f"mark_day:{student_id}:{day}"
        )

    kb.button(
        text="⬅️ Назад к ученику",
        callback_data=f"student:{student_id}"
    )

    kb.adjust(2, 2, 2, 1)

    await callback.message.edit_text(
        "Выберите день недели:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()

@dp.callback_query(F.data.startswith("mark_day:"))
async def mark_day(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    _, student_id, day = callback.data.split(":")

    kb = InlineKeyboardBuilder()

    kb.button(text="✅ Проведено", callback_data=f"set_mark:{student_id}:{day}:1")
    kb.button(text="❌ Отмена заранее", callback_data=f"set_mark:{student_id}:{day}:0")
    kb.button(text="⏰ Поздняя отмена", callback_data=f"set_mark:{student_id}:{day}:-")
    kb.button(text="➕ Доп. занятие / перенос", callback_data=f"set_mark:{student_id}:{day}:$")
    kb.button(text="🧹 Очистить отметку", callback_data=f"set_mark:{student_id}:{day}:clear")
    kb.button(text="⬅️ Назад", callback_data=f"mark_attendance:{student_id}")

    kb.adjust(1)

    await callback.message.edit_text(
        f"Выберите отметку для дня: {day}",
        reply_markup=kb.as_markup()
    )

    await callback.answer()

@dp.callback_query(F.data.startswith("set_mark:"))
async def set_mark(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    _, student_id, day, mark = callback.data.split(":")

    if mark == "clear":
        mark = ""

    rows = attendance_sheet.get_all_records()
    headers = attendance_sheet.row_values(1)

    row_number = None
    col_number = None

    for index, row in enumerate(rows, start=2):
        if str(row.get("ID ученика", "")).strip() == str(student_id):
            row_number = index
            break

    for index, header in enumerate(headers, start=1):
        if str(header).strip().lower() == day:
            col_number = index
            break

    if row_number is None or col_number is None:
        await callback.message.edit_text(
            "Не могу найти ученика или день недели.",
            reply_markup=admin_menu()
        )
        await callback.answer()
        return

    attendance_sheet.update_cell(row_number, col_number, mark)

    mark_names = {
        "1": "занятие проведено ✅",
        "0": "занятие отменено заранее",
        "-": "поздняя отмена",
        "$": "дополнительное занятие / перенос",
        "": "отметка очищена"
    }

    student = find_student(student_id)
    lessons, chargeable_total = build_history(student)
    balance = get_student_balance(student_id)
    debt = max(chargeable_total - balance, 0)

    if mark != "":
        try:
            await bot.send_message(
                int(student_id),
                f"📌 Апдейт по занятию\n\n"
                f"{day.capitalize()}: {mark_names[mark]}.\n\n"
                f"Текущая задолженность: {format_money(debt)}"
            )
        except Exception:
            pass

    await callback.answer("Отметка сохранена ✅", show_alert=False)

    callback.data = f"student:{student_id}"
    await student_card(callback)
    
@dp.callback_query(F.data.startswith("delete_student:"))
async def delete_student_confirm(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    student_id = callback.data.split(":")[1]
    student = find_student(student_id)

    if not student:
        await callback.message.edit_text(
            "Ученик не найден.",
            reply_markup=admin_menu()
        )
        await callback.answer()
        return

    name = student.get("Имя ученика", "Без имени")

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, удалить", callback_data=f"delete_student_yes:{student_id}")
    kb.button(text="⬅️ Нет, назад", callback_data=f"student:{student_id}")
    kb.adjust(1)

    await callback.message.edit_text(
        f"Удалить ученика?\n\n"
        f"👤 {name}\n"
        f"ID: {student_id}\n\n"
        f"Это удалит строку из «Посещаемость» и «Балансы».",
        reply_markup=kb.as_markup()
    )

    await callback.answer()

@dp.callback_query(F.data.startswith("delete_student_yes:"))
async def delete_student_yes(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    student_id = callback.data.split(":")[1]

    attendance_rows = attendance_sheet.get_all_records()
    balance_rows = balances_sheet.get_all_records()

    deleted_attendance = False
    deleted_balance = False

    for index, row in enumerate(attendance_rows, start=2):
        if str(row.get("ID ученика", "")).strip() == str(student_id):
            attendance_sheet.delete_rows(index)
            deleted_attendance = True
            break

    for index, row in enumerate(balance_rows, start=2):
        if str(row.get("ID ученика", "")).strip() == str(student_id):
            balances_sheet.delete_rows(index)
            deleted_balance = True
            break

    await callback.message.edit_text(
        "Ученик удалён ✅\n\n"
        f"Из посещаемости: {'да' if deleted_attendance else 'не найден'}\n"
        f"Из балансов: {'да' if deleted_balance else 'не найден'}",
        reply_markup=admin_menu()
    )

    await callback.answer()
    
@dp.callback_query(F.data.startswith("edit_student:"))
async def edit_student(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Недоступно.", show_alert=True)
        return

    student_id = callback.data.split(":")[1]
    student = find_student(student_id)

    if not student:
        await callback.answer("Ученик не найден.", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Изменить имя", callback_data=f"edit_name:{student_id}")
    kb.button(text="👥 Изменить группу", callback_data=f"edit_group:{student_id}")
    kb.button(text="⏱ Изменить длительность", callback_data=f"edit_duration:{student_id}")
    kb.button(text="🆔 Изменить Telegram ID", callback_data=f"edit_id:{student_id}")
    kb.button(text="⬅️ Назад", callback_data=f"student:{student_id}")
    kb.adjust(1)

    await callback.message.edit_text(
        "Что хотите изменить?",
        reply_markup=kb.as_markup()
    )

    await callback.answer()

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
