from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, TypeHandler
from telegram import Update

from src.config import BOT_TOKEN, logger

# Text and wizard handlers
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text.text_handler))
application.add_handler(CommandHandler("done", text.done_command))

# Forwarded message handler
application.add_handler(MessageHandler(filters.FORWARDED, misc.forwarded_message_handler))

# Web App data handler
application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, misc.web_app_data_handler))

# Catch-all for other button presses not caught by specific handlers
application.add_handler(CallbackQueryHandler(base.unrecognized_button))

# Error handler 

# Create the Application and pass it your bot's token.
application = Application.builder().token(BOT_TOKEN).build()

# --- Register Handlers ---

# This handler runs first to ensure the bot knows about every chat it's in.
application.add_handler(TypeHandler(Update, base.track_chats), group=-1)

# Command Handlers
application.add_handler(CommandHandler("start", base.start))
application.add_handler(CommandHandler("help", base.help_command)) 