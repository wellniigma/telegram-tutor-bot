import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

TOKEN = "8306133509:AAEzhYbPa4PQO8biS_9zr8cREn_dQxs_ERw"
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("Бот работает ✅")


@dp.message()
async def echo(message: Message):
    await message.answer(f"Я получил: {message.text}")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())