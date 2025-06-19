# coding: utf-8
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, TypeHandler
from telegram import Update

from src.config import BOT_TOKEN, logger
from src.handlers import base, text, misc  # гарантируем доступ к используемым модулям

# Сначала создаём объект Application, затем регистрируем все обработчики
application = Application.builder().token(BOT_TOKEN).build()

# Text and wizard handlers
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text.text_handler))
application.add_handler(CommandHandler("done", text.done_command))

# Forwarded message handler
application.add_handler(MessageHandler(filters.FORWARDED, misc.forwarded_message_handler))

# Web App data handler
application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, misc.web_app_data_handler))

# Catch-all for other button presses not caught by specific handlers
application.add_handler(CallbackQueryHandler(base.unrecognized_button))

# Error handler (не показан здесь)

# --- Register Handlers ---

# 1. Сначала — трекинг чатов, чтобы бот знал все чаты, где он находится
application.add_handler(TypeHandler(Update, base.track_chats), group=-1)

# 2. Регистрация любых сообщений в группах для учёта участников
#    Игнорируем команды, чтобы не дублировать обработку /start и т.-д.
application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, base.register_user_activity), group=-1)

# Command Handlers
application.add_handler(CommandHandler("start", base.start))
application.add_handler(CommandHandler("help", base.help_command)) 