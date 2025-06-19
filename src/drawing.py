import io
from PIL import Image, ImageDraw, ImageFont
from typing import Optional
import os

from . import database as db
from .config import logger

from collections import namedtuple

# --- Constants ---
def _load_font(name_candidates, size):
    """Пробует последовательно список имён/путей к TTF-файлам и возвращает первый найденный."""
    for cand in name_candidates:
        try:
            return ImageFont.truetype(cand, size)
        except IOError:
            continue
    return None

# Попытка загрузить шрифт с поддержкой кириллицы.
FONT_REGULAR = _load_font([
    "arial.ttf",  # Windows / пользователь может установить
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "DejaVuSans.ttf",
], 15)

FONT_BOLD = _load_font([
    "arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
], 16)

if FONT_REGULAR is None or FONT_BOLD is None:
    logger.warning("Fallback to default PIL font; Cyrillic glyphs may look poor.")
    FONT_REGULAR = FONT_REGULAR or ImageFont.load_default()
    FONT_BOLD = FONT_BOLD or ImageFont.load_default()

# Colors
COLOR_BG = (255, 255, 255)
# Чуть более выразительный дизайн
COLOR_HEADER_BG = (240, 245, 255)     # мягкий голубой для заголовков
COLOR_ROW_ALT_BG = (250, 250, 250)    # чередующиеся строки
COLOR_GRID = (220, 220, 220)
COLOR_BORDER = (190, 190, 190)
COLOR_TEXT = (20, 20, 20)
COLOR_VOTE_YES = (99, 201, 115)        # более мягкий зелёный
COLOR_VOTE_NO = (245, 245, 245)        # Light Grey
COLOR_EXCLUDED_ROW = (255, 235, 238)   # Light Red for the entire row of an excluded user

# Layout
CELL_HEIGHT = 38
MIN_CELL_WIDTH = 130
NAME_COLUMN_WIDTH = 240
PADDING = 18

def _wrap_text(text, font, max_width):
    """Wraps text to fit into a given width."""
    if font.getlength(text) <= max_width:
        return [text]
    
    lines = []
    words = text.split(' ')
    while words:
        line = ''
        while words and font.getlength(line + words[0]) <= max_width:
            line += words.pop(0) + ' '
        lines.append(line.strip())
    return lines

def generate_results_heatmap_image(poll_id: int, session: Optional[db.Session] = None) -> io.BytesIO:
    """
    Generates a heatmap-style image for poll results.
    Returns an in-memory image file (BytesIO) or None on failure.
    """
    manage_session = not session
    if manage_session:
        session = db.SessionLocal()

    try:
        poll = db.get_poll(poll_id)
        if not poll:
            raise ValueError("Poll not found")

        participants = db.get_participants(poll.chat_id, session=session)
        responses = db.get_responses(poll_id)
        
        # --- Ensure we have participant rows ---------------------------------
        # В случае, если в таблице participants нет записей (или нет тех, кто
        # уже проголосовал), добавим «виртуальных» участников только для
        # отрисовки карты.

        if not participants:
            logger.info(f"No participants stored for chat {poll.chat_id}; building list from responders for heatmap")

        participant_ids_present = {p.user_id for p in participants}
        dummy_needed_ids = [r.user_id for r in responses if r.user_id not in participant_ids_present]

        if dummy_needed_ids:
            DummyParticipant = namedtuple('Participant', ['user_id', 'chat_id', 'username', 'first_name', 'last_name', 'excluded'])
            for uid in dummy_needed_ids:
                user = session.query(db.User).filter_by(user_id=uid).first()
                participants.append(
                    DummyParticipant(
                        user_id=uid,
                        chat_id=poll.chat_id,
                        username=getattr(user, 'username', None) if user else None,
                        first_name=getattr(user, 'first_name', None) if user else None,
                        last_name=getattr(user, 'last_name', None) if user else None,
                        excluded=0,
                    )
                )

        # Determine poll options, dynamically for web apps.
        if poll.poll_type == 'native' and poll.options:
            options = [opt.strip() for opt in poll.options.split(',')]
        else:
            options = sorted(list(set(r.response.strip() for r in responses)))

        if not participants or not options:
            logger.warning(f"Not enough data for heatmap poll {poll_id}")
            return None

        votes = {(r.user_id, r.response.strip()): True for r in responses}
        
        # Проставляем флаги excluded для poll-specific исключений
        poll_excl_ids = db.get_poll_exclusions(poll_id, session=session)
        for idx, p in enumerate(participants):
            if p.user_id in poll_excl_ids:
                # namedtuple – неизменяем, поэтому создаём новый DummyParticipant либо дополняем
                try:
                    participants[idx] = p._replace(excluded=1)
                except AttributeError:
                    # p может быть ORM-объектом Participant – у него атрибут изменяемый
                    setattr(p, 'excluded', 1)

        # --- Calculate Dimensions & Prepare Canvas ---
        wrapped_options = [_wrap_text(opt, FONT_REGULAR, MIN_CELL_WIDTH - 10) for opt in options]
        max_option_lines = max(len(w) for w in wrapped_options) if wrapped_options else 1
        header_height = (max_option_lines * 18) + 10

        image_width = NAME_COLUMN_WIDTH + (len(options) * MIN_CELL_WIDTH) + 2 * PADDING
        image_height = header_height + (len(participants) * CELL_HEIGHT) + 2 * PADDING
        
        image = Image.new('RGB', (image_width, image_height), COLOR_BG)
        draw = ImageDraw.Draw(image)

        # --- Draw Content ---
        # Header background
        header_rect_top = PADDING
        header_rect_bottom = PADDING + header_height
        draw.rectangle([(PADDING, header_rect_top), (image_width - PADDING, header_rect_bottom)], fill=COLOR_HEADER_BG)

        # Draw Option Headers
        for i, option_text_lines in enumerate(wrapped_options):
            x = PADDING + NAME_COLUMN_WIDTH + (i * MIN_CELL_WIDTH)
            line_y = PADDING + 5
            for line in option_text_lines:
                draw.text((x + 8, line_y), line, font=FONT_BOLD, fill=COLOR_TEXT)
                line_y += 18 # Line height

        # Draw Participant Rows
        for p_idx, participant in enumerate(participants):
            y = PADDING + header_height + (p_idx * CELL_HEIGHT)
            
            # Determine row background: excluded > alternating stripe > default
            if participant.excluded:
                row_bg = COLOR_EXCLUDED_ROW
            elif p_idx % 2 == 1:
                row_bg = COLOR_ROW_ALT_BG
            else:
                row_bg = None

            if row_bg:
                draw.rectangle([(PADDING, y), (image_width - PADDING, y + CELL_HEIGHT)], fill=row_bg)

            # Draw name with optional @username
            user_name = db.get_user_name(session, participant.user_id)
            if participant.username:
                # Добавляем юзернейм, если его ещё нет в строке
                if f"@{participant.username}" not in user_name:
                    user_name = f"{user_name} (@{participant.username})"

            # Обрезаем, если не влезает
            if FONT_REGULAR.getlength(user_name) > NAME_COLUMN_WIDTH - 10:
                # Грубая обрезка по символам – достаточно для UI
                while FONT_REGULAR.getlength(user_name + '…') > NAME_COLUMN_WIDTH - 10 and len(user_name) > 1:
                    user_name = user_name[:-1]
                user_name += '…'

            draw.text((PADDING + 5, y + (CELL_HEIGHT // 2) - 8), user_name, font=FONT_REGULAR, fill=COLOR_TEXT)
            
            # Draw vote cells
            for o_idx, option_text in enumerate(options):
                x = PADDING + NAME_COLUMN_WIDTH + (o_idx * MIN_CELL_WIDTH)
                cell_color = COLOR_VOTE_NO
                if (participant.user_id, option_text) in votes:
                    cell_color = COLOR_VOTE_YES
                draw.rectangle([(x, y), (x + MIN_CELL_WIDTH, y + CELL_HEIGHT)], fill=cell_color)

        # --- Draw Gridlines ---
        # Vertical gridlines
        for i in range(len(options) + 2):
            x_pos = PADDING + NAME_COLUMN_WIDTH + (i * MIN_CELL_WIDTH) if i > 0 else PADDING
            draw.line([(x_pos, PADDING), (x_pos, image_height - PADDING)], fill=COLOR_GRID)
        # Horizontal gridlines
        for i in range(len(participants) + 1):
            y_pos = PADDING + header_height + (i * CELL_HEIGHT)
            draw.line([(PADDING, y_pos), (image_width - PADDING, y_pos)], fill=COLOR_GRID)
        
        # Bolder separator for names
        draw.line([(PADDING + NAME_COLUMN_WIDTH, PADDING), (PADDING + NAME_COLUMN_WIDTH, image_height - PADDING)], fill=COLOR_BORDER, width=2)
        
        # Outer border
        draw.rectangle([(PADDING, PADDING), (image_width - PADDING, image_height - PADDING)], outline=COLOR_BORDER, width=2)
        
        # --- Finalize ---
        image_buffer = io.BytesIO()
        image.save(image_buffer, format='PNG')
        image_buffer.seek(0)
        
        return image_buffer

    except Exception as e:
        logger.error(f"Failed to generate heatmap for poll {poll_id}: {e}", exc_info=True)
        return None
    finally:
        if manage_session:
            session.close() 