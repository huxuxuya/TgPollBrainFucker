import logging
from telegram.ext import CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from telegram import Update, InlineKeyboardButton
from src.modules.carpool.models import Car
from src.database import SessionLocal

# Состояния диалога
ASK_SEATS, ASK_TIME, ASK_AREA, CONFIRM = range(4)

async def carpool_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.warning("carpool_start вызван")
    if update.message:
        await update.message.reply_text(
            "Вы хотите создать машину для рассадки по машинам.\nСколько мест (включая водителя) в вашей машине?")
        return ASK_SEATS
    else:
        logging.warning("update.message is None")
        return ConversationHandler.END

async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seats = update.message.text.strip()
    if not seats.isdigit() or int(seats) < 1:
        await update.message.reply_text("Пожалуйста, введите корректное число мест (целое число > 0)")
        return ASK_SEATS
    context.user_data['seats'] = int(seats)
    await update.message.reply_text("Во сколько планируете выезд? (например, 18:30)")
    return ASK_TIME

async def ask_area(update: Update, context: ContextTypes.DEFAULT_TYPE):
    depart_time = update.message.text.strip()
    context.user_data['depart_time'] = depart_time
    await update.message.reply_text("Из какого района/места будет выезд?")
    return ASK_AREA

async def confirm_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    depart_area = update.message.text.strip()
    context.user_data['depart_area'] = depart_area
    seats = context.user_data['seats']
    depart_time = context.user_data['depart_time']
    area = depart_area
    await update.message.reply_text(
        f"Проверьте данные:\nМест: {seats}\nВремя: {depart_time}\nРайон: {area}\n\nВсе верно? (да/нет)")
    return CONFIRM

async def save_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.message.text.strip().lower()
    if answer not in ("да", "yes", "+"):
        await update.message.reply_text("Отмена создания машины.")
        return ConversationHandler.END
    user = update.effective_user
    seats = context.user_data['seats']
    depart_time = context.user_data['depart_time']
    depart_area = context.user_data['depart_area']
    # Сохраняем машину в БД
    session = SessionLocal()
    try:
        car = Car(driver_id=user.id, seats=seats, depart_time=depart_time, depart_area=depart_area)
        session.add(car)
        session.commit()
        await update.message.reply_text("Машина успешно создана! Спасибо, вы добавлены как водитель.")
    except Exception as e:
        session.rollback()
        await update.message.reply_text(f"Ошибка при сохранении: {e}")
    finally:
        session.close()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Диалог отменён.")
    return ConversationHandler.END

def get_driver_button(poll_id, bot_username):
    url = f"https://t.me/{bot_username}?start=carpool_{poll_id}"
    return InlineKeyboardButton("Я водитель (личка)", url=url)

# Deep-link обработчик для /start carpool_<poll_id>
async def handle_deeplink_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args and args[0].startswith('carpool_'):
        poll_id = args[0].split('_', 1)[1]
        await update.message.reply_text(f"Вы приглашены стать водителем для опроса {poll_id}!\nСейчас начнём регистрацию вашей машины.")
        # Можно сразу запустить сценарий создания машины (carpool_start)
        await carpool_start(update, context)
        return True
    return False

def register_carpool_handlers(application):
    print("register_carpool_handlers вызван")
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("carpool", carpool_start)],
        states={
            ASK_SEATS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_time)],
            ASK_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_area)],
            ASK_AREA: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_car)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_car)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler) 