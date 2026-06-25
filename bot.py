import asyncio
import logging
import os
import json
from io import StringIO

import gspread
from google.oauth2.service_account import Credentials

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ------------------------
# Google Sheets
# ------------------------

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

google_credentials = json.loads(
    os.getenv("GOOGLE_CREDENTIALS")
)

creds = Credentials.from_service_account_info(
    google_credentials,
    scopes=SCOPES
)

gc = gspread.authorize(creds)

spreadsheet = gc.open_by_key(SPREADSHEET_ID)

attendance_sheet = spreadsheet.worksheet("Посещаемость")
balances_sheet = spreadsheet.worksheet("Балансы")
settings_sheet = spreadsheet.worksheet("Настройки")

# ------------------------
# Helpers
# ------------------------

def find_student(telegram_id: int):
    rows = attendance_sheet.get_all_records()

    for row in rows:
        if str(row["ID ученика"]) == str(telegram_id):
            return row

    return None

def get_lesson_price(group_name, duration):

    rows = settings_sheet.get_all_records()

    for row in rows:

        if str(row["Формат"]).strip() == str(group_name).strip():

            value = row.get(str(duration))

            if value not in ("", None):
                return int(value)

    return 0

def get_student_balance(telegram_id):

    rows = balances_sheet.get_all_records()

    for row in rows:

        if str(row["ID ученика"]) == str(telegram_id):

            return float(row["Баланс"])

    return 0


def get_lesson_price(group_name, duration):

    rows = settings_sheet.get_all_records()

    for row in rows:

        if str(row["Формат"]).strip() == str(group_name).strip():

            duration = str(duration)

            value = row.get(duration)

            if value:
                return int(value)

    return 0

def build_history(student):

    result = []

    group_name = student["Группа"]
    duration = student["Длительность"]

    lesson_price = get_lesson_price(
        group_name,
        duration
    )

    debt = 0

    for column, value in student.items():

        if "." not in str(column):
            continue

        value = str(value).strip()

        if value == "":
            continue

        if value == "1":

            debt += lesson_price

            result.append({
                "date": column,
                "status": "Проведено",
                "price": lesson_price,
                "need_pay": True
            })

        elif value == "$":

            debt += lesson_price

            result.append({
                "date": column,
                "status": "Дополнительное занятие",
                "price": lesson_price,
                "need_pay": True
            })

        elif value == "-":

            debt += lesson_price

            result.append({
                "date": column,
                "status": "Поздняя отмена",
                "price": lesson_price,
                "need_pay": True
            })

        elif value == "0":

            result.append({
                "date": column,
                "status": "Отмена заранее",
                "price": 0,
                "need_pay": False
            })

    return result, debt

# ------------------------
# Main menu
# ------------------------

def main_menu():
    kb = InlineKeyboardBuilder()

    kb.button(
        text="📝 Прошедшие занятия",
        callback_data="history"
    )

    kb.button(
        text="💳 Оплатить занятия",
        callback_data="payment"
    )

    kb.adjust(1)

    return kb.as_markup()

# ------------------------
# Start
# ------------------------

@dp.message(Command("start"))
async def start(message: Message):

    student = find_student(message.from_user.id)

    if not student:
        await message.answer(
            "Ваш Telegram ID не найден в таблице.\n\nСвяжитесь с преподавателем."
        )
        return

    text = (
        "Здравствуйте! Я очень полезный бот, который поможет:\n\n"
        "📝 Узнать количество посещённых занятий\n\n"
        "💳 Оплатить занятия\n\n"
        "📌 Быть в курсе новостей\n\n"
        "📨 Получать уведомления"
    )

    await message.answer(
        text,
        reply_markup=main_menu()
    )

# ------------------------
# History
# ------------------------

@dp.callback_query(F.data == "history")
async def history(callback: CallbackQuery):

    student = find_student(
        callback.from_user.id
    )

    history_data, debt = build_history(student)

    if not history_data:

        await callback.message.edit_text(
            "История занятий пока отсутствует.",
            reply_markup=main_menu()
        )

        await callback.answer()
        return

    text = ""

    for item in history_data:

        text += (
            f"{item['status']}\n"
            f"Обществознание\n"
            f"{item['date']}\n"
            f"{item['price']} руб.\n\n"
        )

    text += f"\nОбщая задолженность: {debt} руб."

    kb = InlineKeyboardBuilder()

    kb.button(
        text="🏠 В главное меню",
        callback_data="menu"
    )

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )

    await callback.answer()
# ------------------------
# Main menu button
# ------------------------

@dp.callback_query(F.data == "menu")
async def menu(callback: CallbackQuery):

    text = (
        "Здравствуйте! Я очень полезный бот, который поможет:\n\n"
        "📝 Узнать количество посещённых занятий\n\n"
        "💳 Оплатить занятия\n\n"
        "📌 Быть в курсе новостей\n\n"
        "📨 Получать уведомления"
    )

    await callback.message.edit_text(
        text,
        reply_markup=main_menu()
    )

    await callback.answer()
    
# ------------------------
# Payment
# ------------------------

@dp.callback_query(F.data == "payment")
async def payment(callback: CallbackQuery):

    await callback.message.edit_text(
        "💳 Раздел оплаты появится на следующем этапе.",
        reply_markup=main_menu()
    )

    await callback.answer()

# ------------------------
# Run
# ------------------------

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
