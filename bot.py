import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

logging.basicConfig(level=logging.INFO)

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()


@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("Бот работает в облаке ✅")


@dp.message()
async def echo(message: Message):
    await message.answer(message.text)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
