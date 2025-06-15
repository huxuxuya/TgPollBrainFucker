from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram import Update

from src.config import BOT_TOKEN, logger
from src.database import init_database
from src.handlers import admin, dashboard, voting, text, results, misc, base, settings


def main() -> None:
    """Start the bot."""
    # Initialize the database
    init_database()

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # --- Register Handlers ---
    
    # Command Handlers
    application.add_handler(CommandHandler("start", base.start))
    application.add_handler(CommandHandler("help", base.help_command))
    application.add_handler(CommandHandler("dashboard", dashboard.private_chat_entry_point))
    application.add_handler(CommandHandler("done", text.done_command))
    application.add_handler(CommandHandler("backup", admin.backup))
    application.add_handler(CommandHandler("restore", admin.restore))

    # Callback Query Handlers
    application.add_handler(CallbackQueryHandler(dashboard.dashboard_callback_handler, pattern="^dash:"))
    application.add_handler(CallbackQueryHandler(voting.vote_callback_handler, pattern="^vote:"))
    application.add_handler(CallbackQueryHandler(results.results_callback_handler, pattern="^res:"))
    application.add_handler(CallbackQueryHandler(settings.settings_callback_handler, pattern="^settings:"))

    
    # Message Handlers
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text.text_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, misc.web_app_data_handler))
    application.add_handler(MessageHandler(filters.FORWARDED, misc.forwarded_message_handler))

    # Error handler
    application.add_error_handler(base.error_handler) 

    # Run the bot until the user presses Ctrl-C
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main() 