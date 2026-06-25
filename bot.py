import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

logging.basicConfig(level=logging.INFO)

print("BOT_TOKEN =", os.getenv("BOT_TOKEN"))
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()


from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

@dp.message(Command("start"))
async def start(message: Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💳 Оплатить занятие")]
        ],
        resize_keyboard=True
    )

    await message.answer(
        "Здравствуйте! Выберите действие:",
        reply_markup=keyboard
    )


@dp.message()
async def echo(message: Message):
    await message.answer(message.text)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
