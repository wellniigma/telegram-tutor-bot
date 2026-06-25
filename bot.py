import asyncio
import logging
import os
import json

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
    amount = float(amount)
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " руб."


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
                    "date": column,
                    "title": "Проведено",
                    "price": lesson_price,
                    "need_pay": True,
                }
            )
            chargeable_total += lesson_price

        elif value == "$":
            lessons.append(
                {
                    "date": column,
                    "title": "Дополнительное занятие / перенос",
                    "price": lesson_price,
                    "need_pay": True,
                }
            )
            chargeable_total += lesson_price

        elif value == "-":
            lessons.append(
                {
                    "date": column,
                    "title": "Поздняя отмена",
                    "price": lesson_price,
                    "need_pay": True,
                }
            )
            chargeable_total += lesson_price

        elif value == "0":
            lessons.append(
                {
                    "date": column,
                    "title": "Отмена заранее",
                    "price": 0,
                    "need_pay": False,
                }
            )

    return lessons, chargeable_total


def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Прошедшие занятия", callback_data="history")
    kb.button(text="💳 Оплатить занятия", callback_data="payment")
    kb.adjust(1)
    return kb.as_markup()


def back_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 В главное меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def get_main_text():
    return (
        "Здравствуйте! Я очень полезный бот, который поможет:\n\n"
        "📝 Узнать количество посещённых занятий -- Чтобы понять какой большой путь мы прошли!\n\n"
        "💳 Оплатить занятия: Быстро и удобно, с помощью СБП!\n\n"
        "📌 Быть в курсе всех новостей и изменений!\n\n"
        "📨 А также: я буду присылать уведомления, если вдруг нужно будет что-то напомнить"
    )


@dp.message(Command("start"))
async def start(message: Message):
    student = find_student(message.from_user.id)

    if not student:
        await message.answer(
            "Ваш Telegram ID не найден в таблице.\n\n"
            f"Ваш ID: {message.from_user.id}\n\n"
            "Свяжитесь с преподавателем."
        )
        return

    await message.answer(get_main_text(), reply_markup=main_menu())


@dp.callback_query(F.data == "menu")
async def menu(callback: CallbackQuery):
    await callback.message.edit_text(get_main_text(), reply_markup=main_menu())
    await callback.answer()


@dp.callback_query(F.data == "history")
async def history(callback: CallbackQuery):
    student = find_student(callback.from_user.id)

    if not student:
        await callback.message.edit_text(
            "Ваш Telegram ID не найден в таблице.",
            reply_markup=back_menu(),
        )
        await callback.answer()
        return

    lessons, chargeable_total = build_history(student)
    balance = get_student_balance(callback.from_user.id)
    debt = max(chargeable_total - balance, 0)

    if not lessons:
        await callback.message.edit_text(
            "История занятий пока отсутствует.",
            reply_markup=back_menu(),
        )
        await callback.answer()
        return

    remaining_balance = balance
    text = "📚 История занятий\n\n"

    for item in lessons:
        if item["need_pay"]:
            if remaining_balance >= item["price"]:
                payment_status = "✅ Оплачено"
                remaining_balance -= item["price"]
            else:
                payment_status = "🟡 Ожидает оплаты"
        else:
            payment_status = "🔴 Не оплачивается"

        text += (
            f"{payment_status}\n"
            f"Предмет: Обществознание\n"
            f"Тип: {item['title']}\n"
            f"Дата: {item['date']}\n"
            f"Стоимость: {format_money(item['price'])}\n\n"
        )

    text += "──────────────\n"
    text += f"Ваш баланс: {format_money(balance)}\n"
    text += f"Общая задолженность: {format_money(debt)}"

    await callback.message.edit_text(text, reply_markup=back_menu())
    await callback.answer()


@dp.callback_query(F.data == "payment")
async def payment(callback: CallbackQuery):
    student = find_student(callback.from_user.id)

    if not student:
        await callback.message.edit_text(
            "Ваш Telegram ID не найден в таблице.",
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
            "Сейчас задолженности нет.\n\n"
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
                f"{number}. {item['date']} | "
                f"{item['title']} | "
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


@dp.callback_query(F.data == "pay_custom")
async def pay_custom(callback: CallbackQuery):
    await callback.message.edit_text(
        "Введите сумму, на которую хотите пополнить баланс.\n\n"
        "Пока ввод суммы подключим следующим шагом.",
        reply_markup=back_menu(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("pay_debt:"))
async def pay_debt(callback: CallbackQuery):
    amount = callback.data.split(":")[1]

    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оплатить", url="https://example.com")
    kb.button(text="🏠 В главное меню", callback_data="menu")
    kb.adjust(1)

    await callback.message.edit_text(
        "Спасибо, что остаётесь со мной 💗\n\n"
        "Оплата доступна по кнопке ниже ⬇️\n\n"
        f"Сумма: {format_money(amount)}",
        reply_markup=kb.as_markup(),
    )

    await callback.answer()


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
