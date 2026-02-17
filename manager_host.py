#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import psutil
import asyncio
import logging
import gc  # Сборщик мусора
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Настройки - УМЕНЬШАЕМ ПОТРЕБЛЕНИЕ ПАМЯТИ
BOT_TOKEN = "8328009081:AAFybCojde0Nj2eeBTJOEHJn4td4WLkYMxo"  # Замените на ваш токен
ADMIN_IDS = [5684330880, 5000479220]  # ID администраторов
ALLOWED_EXTENSIONS = {'.py', '.sh'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # Уменьшили до 10 MB

# Папки
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Настройка логирования (меньше логов - меньше памяти)
logging.basicConfig(
    level=logging.WARNING,  # Только важные сообщения
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

class ProcessManager:
    """Класс для управления процессами с оптимизацией памяти"""
    
    @staticmethod
    def get_all_processes():
        """Получает список процессов (оптимизировано)"""
        processes = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info']):
                try:
                    if 'python' in proc.info['name'].lower():
                        cmdline = proc.info['cmdline']
                        if cmdline and len(cmdline) > 1:
                            script_path = cmdline[-1]
                            if script_path.startswith(BASE_DIR) and script_path != __file__:
                                # Минимум информации для экономии памяти
                                processes.append({
                                    'pid': proc.info['pid'],
                                    'script': os.path.basename(script_path),
                                    'memory': proc.info['memory_info'].rss / 1024 / 1024 if proc.info['memory_info'] else 0
                                })
                except:
                    continue
        except:
            pass
        return processes
    
    @staticmethod
    def start_script(script_path):
        """Запускает скрипт с ограничением памяти"""
        try:
            # Проверяем свободную память перед запуском
            memory = psutil.virtual_memory()
            if memory.available < 200 * 1024 * 1024:  # Меньше 200 MB свободно
                return False, "Недостаточно памяти для запуска"
            
            # Делаем файл исполняемым
            os.chmod(script_path, 0o755)
            
            # Запускаем с низким приоритетом
            if sys.platform == "win32":
                process = subprocess.Popen(
                    [sys.executable, script_path],
                    stdout=subprocess.DEVNULL,  # Не сохраняем вывод
                    stderr=subprocess.DEVNULL,
                    cwd=os.path.dirname(script_path)
                )
            else:
                # Для Linux - nice и ionice для уменьшения нагрузки
                process = subprocess.Popen(
                    ['nice', '-n', '19', sys.executable, script_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=os.path.dirname(script_path),
                    start_new_session=True
                )
            
            return True, process.pid
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def stop_process(pid):
        """Останавливает процесс"""
        try:
            process = psutil.Process(pid)
            process.terminate()
            gone, alive = psutil.wait_procs([process], timeout=3)
            if alive:
                process.kill()
            return True, "Остановлен"
        except:
            return False, "Ошибка"
    
    @staticmethod
    def get_server_status():
        """Базовый статус сервера (минимум информации)"""
        try:
            memory = psutil.virtual_memory()
            return {
                'memory_available': memory.available / 1024 / 1024,
                'memory_percent': memory.percent,
                'cpu_percent': psutil.cpu_percent(interval=0.5)
            }
        except:
            return None

# Проверка администратора
def is_admin(user_id):
    return user_id in ADMIN_IDS

@dp.message(Command('start'))
async def cmd_start(message: Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Нет доступа")
        return
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📁 Загрузить", callback_data="upload")
    builder.button(text="📋 Файлы", callback_data="list_files")
    builder.button(text="🔄 Процессы", callback_data="processes")
    builder.button(text="📊 Статус", callback_data="status")
    builder.button(text="❌ Остановить", callback_data="stop_process")
    builder.adjust(2)
    
    await message.reply(
        "🤖 *Управление хостингом*\n"
        "⚠️ *Ограничение памяти!* Запускайте только 1 бота за раз",
        reply_markup=builder.as_markup()
    )

@dp.callback_query()
async def process_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    
    action = callback.data
    
    if action == "upload":
        await callback.message.answer(
            "📤 Отправьте файл (.py или .sh)\n"
            f"Макс. размер: {MAX_FILE_SIZE/1024/1026} MB"
        )
    
    elif action == "list_files":
        files = [f for f in os.listdir(BASE_DIR) 
                if f.endswith(('.py', '.sh')) and f != os.path.basename(__file__)]
        
        if not files:
            await callback.message.answer("📁 Нет файлов")
        else:
            builder = InlineKeyboardBuilder()
            for file in files[:5]:  # Показываем только 5 файлов
                builder.button(text=f"▶️ {file}", callback_data=f"run_{file}")
            builder.adjust(1)
            await callback.message.answer("Выберите файл:", reply_markup=builder.as_markup())
    
    elif action == "processes":
        processes = ProcessManager.get_all_processes()
        if not processes:
            await callback.message.answer("🔄 Нет процессов")
        else:
            text = "🔄 *Процессы:*\n"
            for p in processes:
                text += f"• {p['script']} (PID: {p['pid']}) - {p['memory']:.0f} MB\n"
            await callback.message.answer(text[:1000])  # Ограничиваем длину
    
    elif action == "status":
        status = ProcessManager.get_server_status()
        if status:
            text = (
                f"📊 *Статус*\n"
                f"RAM: {status['memory_percent']}%\n"
                f"Доступно: {status['memory_available']:.0f} MB\n"
                f"CPU: {status['cpu_percent']}%"
            )
            await callback.message.answer(text)
        else:
            await callback.message.answer("❌ Ошибка")
    
    elif action.startswith("run_"):
        filename = action[4:]
        file_path = os.path.join(BASE_DIR, filename)
        
        if os.path.exists(file_path):
            # Проверяем, нет ли уже запущенных процессов
            processes = ProcessManager.get_all_processes()
            if len(processes) >= 10:  # Максимум 1 процесс
                await callback.message.answer("⚠️ Уже запущен 1 процесс. Остановите его сначала.")
                await callback.answer()
                return
            
            success, result = ProcessManager.start_script(file_path)
            if success:
                await callback.message.answer(f"✅ Запущен {filename}\nPID: {result}")
                # Принудительный сбор мусора
                gc.collect()
            else:
                await callback.message.answer(f"❌ Ошибка: {result}")
        else:
            await callback.message.answer(f"❌ Файл не найден")
    
    elif action.startswith("kill_"):
        pid = int(action[5:])
        success, msg = ProcessManager.stop_process(pid)
        await callback.message.answer(f"✅ Процесс {pid} остановлен" if success else f"❌ Ошибка")
        gc.collect()  # Сбор мусора
    
    await callback.answer()

# Обработка файлов
@dp.message(F.document)
async def handle_document(message: Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Нет доступа")
        return
    
    document = message.document
    file_ext = os.path.splitext(document.file_name)[1].lower()
    
    if file_ext not in {'.py', '.sh'}:
        await message.reply("❌ Только .py и .sh файлы")
        return
    
    if document.file_size > MAX_FILE_SIZE:
        await message.reply(f"❌ Файл > {MAX_FILE_SIZE/1024/1026} MB")
        return
    
    # Скачиваем
    file_path = os.path.join(BASE_DIR, document.file_name)
    try:
        file = await bot.get_file(document.file_id)
        await bot.download_file(file.file_path, file_path)
        os.chmod(file_path, 0o755)
        await message.reply(f"✅ {document.file_name} загружен")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")

@dp.message(Command('status'))
async def cmd_status(message: Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Нет доступа")
        return
    status = ProcessManager.get_server_status()
    await message.reply(f"RAM: {status['memory_percent']}%" if status else "❌ Ошибка")

@dp.message(Command('stop'))
async def cmd_stop(message: Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Нет доступа")
        return
    args = message.text.split()
    if len(args) > 1:
        try:
            pid = int(args[1])
            ProcessManager.stop_process(pid)
            await message.reply(f"✅ Процесс {pid} остановлен")
            gc.collect()
        except:
            await message.reply("❌ Ошибка")
    else:
        await message.reply("❌ Укажите PID: /stop 12345")

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    logger.warning("Бот запущен в экономичном режиме")
    asyncio.run(main())