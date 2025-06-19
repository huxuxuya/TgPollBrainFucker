import io
from PIL import Image, ImageDraw, ImageFont
from typing import Optional

from . import database as db
from .config import logger

from collections import namedtuple

# --- Constants ---
try:
    # Using a common font, assuming it exists. A bundled font would be more robust.
    FONT_REGULAR = ImageFont.truetype("arial.ttf", 15)
    FONT_BOLD = ImageFont.truetype("arialbd.ttf", 16)
except IOError:
    logger.warning("Arial font not found. Using default PIL font. Text rendering might be poor.")
    FONT_REGULAR = ImageFont.load_default()
    FONT_BOLD = ImageFont.load_default()

# Colors
COLOR_BG = (255, 255, 255)
COLOR_GRID = (220, 220, 220)
COLOR_TEXT = (0, 0, 0)
COLOR_VOTE_YES = (76, 175, 80) # Material Design Green
COLOR_VOTE_NO = (245, 245, 245) # Light Grey
COLOR_EXCLUDED_ROW = (255, 235, 238) # Light Red for the entire row of an excluded user

# Layout
CELL_HEIGHT = 35
MIN_CELL_WIDTH = 120
NAME_COLUMN_WIDTH = 220
PADDING = 15

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
        # Draw Option Headers
        for i, option_text_lines in enumerate(wrapped_options):
            x = PADDING + NAME_COLUMN_WIDTH + (i * MIN_CELL_WIDTH)
            line_y = PADDING + 5
            for line in option_text_lines:
                draw.text((x + 5, line_y), line, font=FONT_REGULAR, fill=COLOR_TEXT)
                line_y += 18 # Line height

        # Draw Participant Rows
        for p_idx, participant in enumerate(participants):
            y = PADDING + header_height + (p_idx * CELL_HEIGHT)
            
            # Highlight excluded users by coloring their row
            if participant.excluded:
                draw.rectangle([(PADDING, y), (image_width - PADDING, y + CELL_HEIGHT)], fill=COLOR_EXCLUDED_ROW)

            # Draw name (and truncate if necessary)
            user_name = db.get_user_name(session, participant.user_id)
            if FONT_REGULAR.getlength(user_name) > NAME_COLUMN_WIDTH - 10:
                user_name = user_name[:30] + '…'
            draw.text((PADDING + 5, y + (CELL_HEIGHT // 2) - 8), user_name, font=FONT_REGULAR, fill=COLOR_TEXT)
            
            # Draw vote cells
            for o_idx, option_text in enumerate(options):
                x = PADDING + NAME_COLUMN_WIDTH + (o_idx * MIN_CELL_WIDTH)
                cell_color = COLOR_VOTE_NO
                if (participant.user_id, option_text) in votes:
                    cell_color = COLOR_VOTE_YES
                draw.rectangle([(x, y), (x + MIN_CELL_WIDTH, y + CELL_HEIGHT)], fill=cell_color)

        # --- Draw Gridlines ---
        # Vertical
        for i in range(len(options) + 2):
            x_pos = PADDING + NAME_COLUMN_WIDTH + (i * MIN_CELL_WIDTH) if i > 0 else PADDING
            draw.line([(x_pos, PADDING), (x_pos, image_height - PADDING)], fill=COLOR_GRID)
        # Horizontal
        for i in range(len(participants) + 1):
            y_pos = PADDING + header_height + (i * CELL_HEIGHT)
            draw.line([(PADDING, y_pos), (image_width - PADDING, y_pos)], fill=COLOR_GRID)
        
        # Bolder separator for names
        draw.line([(PADDING + NAME_COLUMN_WIDTH, PADDING), (PADDING + NAME_COLUMN_WIDTH, image_height - PADDING)], fill=(180, 180, 180), width=2)
        
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