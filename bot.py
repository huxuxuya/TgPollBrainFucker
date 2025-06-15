from telegram.ext import Application, CommandHandler, MessageHandler, filters, TypeHandler, CallbackQueryHandler
from telegram.request import HTTPXRequest

from src.config import BOT_TOKEN, logger
from src import database as db
from src.handlers import admin, base, dashboard, voting, settings, text, results, misc

def main() -> None:
    """Start the bot."""
    # Initialize the database
    db.init_database()

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # --- Register Handlers ---
    
    # Base handlers
    application.add_handler(CommandHandler("start", base.start))
    application.add_handler(CommandHandler("help", base.help_command))
    application.add_handler(CommandHandler("debug", base.toggle_debug))
    application.add_handler(TypeHandler(object, base.track_chats), group=-2) # Track all chats
    application.add_handler(TypeHandler(object, base.log_all_updates), group=-1) # Log all updates
    
    # Admin commands
    application.add_handler(CommandHandler("backup", admin.backup))
    application.add_handler(CommandHandler("restore", admin.restore))

    # Dashboard handler
    application.add_handler(CallbackQueryHandler(dashboard.dashboard_callback_handler, pattern="^dash:"))

    # Voting handler
    application.add_handler(CallbackQueryHandler(voting.vote_callback_handler, pattern="^vote:"))

    # Settings handler
    application.add_handler(CallbackQueryHandler(settings.settings_callback_handler, pattern="^settings:"))

    # Results handler
    application.add_handler(CallbackQueryHandler(results.results_callback_handler, pattern="^results:"))

    # Legacy vote handler for old format (e.g., "poll_22_1")
    application.add_handler(CallbackQueryHandler(voting.legacy_vote_handler, pattern=r"^poll_\d+_\d+$"))

    # Text and wizard handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text.text_handler))
    application.add_handler(CommandHandler("done", text.done_command))

    # Forwarded message handler
    application.add_handler(MessageHandler(filters.FORWARDED, misc.forwarded_message_handler))

    # Catch-all for other button presses not caught by specific handlers
    application.add_handler(CallbackQueryHandler(base.unrecognized_button))

    # Error handler
    application.add_error_handler(base.error_handler)

    # TODO: Register handlers for polls, dashboard, callbacks, etc.

    # Run the bot until the user presses Ctrl-C
    logger.info("Starting bot...")
    application.run_polling()

if __name__ == "__main__":
    main() 