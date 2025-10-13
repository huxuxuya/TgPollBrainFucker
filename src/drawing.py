import io
from PIL import Image, ImageDraw, ImageFont
from typing import Optional
import os
import math

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
    "/System/Library/Fonts/Supplemental/Arial.ttf",  # macOS
    "arial.ttf",  # Windows / пользователь может установить
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "DejaVuSans.ttf",
], 15)

FONT_BOLD = _load_font([
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",  # macOS (если есть)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "arialbd.ttf",
], 16)

if FONT_REGULAR is None or FONT_BOLD is None:
    logger.warning("Fallback to default PIL font; Cyrillic glyphs may look poor.")
    FONT_REGULAR = FONT_REGULAR or ImageFont.load_default()
    FONT_BOLD = FONT_BOLD or ImageFont.load_default()

def get_system_font(size=20):
    """
    Возвращает объект ImageFont с поддержкой кириллицы для Mac, Windows и Linux.
    Если подходящий ttf-шрифт не найден — возвращает стандартный PIL-шрифт.
    """
    possible_paths = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",  # macOS
        # Windows
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/ARIAL.TTF",
        # Linux (часто ставят DejaVuSans)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    print("WARNING: Не найден подходящий ttf-шрифт, используем стандартный PIL-шрифт (кириллица будет отображаться некорректно)")
    return ImageFont.load_default()

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
COLOR_VOTE_EXCLUDED = (255, 183, 74)   # Orange highlight for votes cast by excluded users

# Layout
CELL_HEIGHT = 38
MIN_CELL_WIDTH = 130
NAME_COLUMN_WIDTH = 240
NUMBER_COL_WIDTH = 32  # width reserved for row numbers
PADDING = 18

def _wrap_text(text, font, max_width):
    """Wraps text to fit into a given width."""
    if font.getlength(text) <= max_width:
        return [text]
    
    lines = []
    words = text.split(' ')
    while words:
        line = ''
        while words:
            word = words[0]
            # Проверяем, помещается ли слово в текущую строку
            test_line = line + word + ' ' if line else word + ' '
            if font.getlength(test_line) <= max_width:
                line += words.pop(0) + ' '
            else:
                # Если строка пустая и слово не помещается, принудительно обрезаем слово
                if not line:
                    # Находим максимальную длину символов, которая помещается в max_width
                    word_chars = list(word)
                    truncated_word = ''
                    for char in word_chars:
                        test_char = truncated_word + char
                        if font.getlength(test_char) <= max_width:
                            truncated_word += char
                        else:
                            break
                    
                    if truncated_word:
                        lines.append(truncated_word)
                        # Обновляем слово, убирая уже добавленную часть
                        remaining_word = word[len(truncated_word):]
                        if remaining_word:
                            words[0] = remaining_word
                        else:
                            words.pop(0)
                    else:
                        # Если даже один символ не помещается, добавляем пустую строку и пропускаем символ
                        lines.append('')
                        words.pop(0)
                else:
                    # Строка не пустая, завершаем её
                    break
        
        if line:
            lines.append(line.strip())
    
    return lines

def _draw_rounded_rectangle(draw, xy, radius, fill=None, outline=None, width=1, shadow=False):
    # xy = (x1, y1, x2, y2)
    x1, y1, x2, y2 = xy
    if shadow:
        # Draw shadow as a blurred rectangle (имитация)
        shadow_color = (200, 200, 200, 80)
        for offset in range(6, 0, -2):
            draw.rounded_rectangle([x1+offset, y1+offset, x2+offset, y2+offset], radius=radius+offset, fill=shadow_color)
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

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

        # votes dict already built above based on visible participants
        
        # Проставляем флаги excluded для poll-specific исключений
        poll_excl_ids = db.get_poll_exclusions(poll_id, session=session)
        for idx, p in enumerate(participants):
            if p.user_id in poll_excl_ids:
                # namedtuple – неизменяем, поэтому создаём новый DummyParticipant либо дополняем
                try:
                    participants[idx] = p._replace(excluded=1)
                except AttributeError:
                    # ORM-объект Participant – у него атрибут изменяемый
                    setattr(p, 'excluded', 1)

        # --- Build final participant list ---
        # 1. Добавляем все не-исключённые.
        # 2. Добавляем исключённых только если они голосовали.
        respondent_ids = {r.user_id for r in responses}
        participants = [
            p for p in participants
            if (not getattr(p, 'excluded', False)) or (p.user_id in respondent_ids)
        ]
        visible_user_ids = {p.user_id for p in participants}

        # Re-build the votes map so that only rows present on the heatmap are considered
        votes = {(r.user_id, r.response.strip()): True for r in responses if r.user_id in visible_user_ids}

        # --- Calculate Dimensions & Prepare Canvas ---
        # --- Prepare question text (poll title) ---
        question_text = (poll.message or "").strip()
        title_lines = _wrap_text(question_text, FONT_BOLD, NAME_COLUMN_WIDTH + len(options)*MIN_CELL_WIDTH)
        # Calculate exact line height of the bold font to avoid overlaps
        line_height = FONT_BOLD.getbbox("Ag")[3] - FONT_BOLD.getbbox("Ag")[1]
        TITLE_MARGIN = 18  # extra spacing below title to separate from option headers
        title_height = (len(title_lines) * (line_height + 2)) if title_lines and question_text else 0
        title_block_height = title_height + (TITLE_MARGIN if question_text else 0)

        wrapped_options = [_wrap_text(opt, FONT_REGULAR, MIN_CELL_WIDTH - 10) for opt in options]
        max_option_lines = max(len(w) for w in wrapped_options) if wrapped_options else 1
        header_height = title_block_height + (max_option_lines * 18) + 14

        image_width = NAME_COLUMN_WIDTH + (len(options) * MIN_CELL_WIDTH) + 2 * PADDING
        image_height = header_height + (len(participants) * CELL_HEIGHT) + 2 * PADDING
        
        # --- Glassmorphism: полупрозрачный белый фон ---
        image = Image.new('RGBA', (image_width, image_height), (255,255,255,0))
        draw = ImageDraw.Draw(image, 'RGBA')
        # Тень под таблицей
        _draw_rounded_rectangle(draw, (8, 8, image_width-8, image_height-8), radius=24, fill=(200,200,220,60), shadow=True)
        # Основная карточка
        _draw_rounded_rectangle(draw, (0, 0, image_width, image_height), radius=24, fill=(255,255,255,220), outline=(220,220,240,255), width=3)

        # --- Header ---
        header_rect_top = PADDING
        header_rect_bottom = PADDING + header_height
        _draw_rounded_rectangle(draw, (PADDING, header_rect_top, image_width - PADDING, header_rect_bottom), radius=16, fill=(240,245,255,220))

        # --- Draw poll question text ---
        if question_text:
            cur_y = PADDING + 6
            for line in title_lines:
                text_width = FONT_BOLD.getlength(line)
                x_pos = PADDING + (image_width - 2*PADDING - text_width)/2  # center align
                draw.text((x_pos, cur_y), line, font=FONT_BOLD, fill=COLOR_TEXT)
                cur_y += line_height + 2

        # --- Определяем лидирующий вариант ---
        # Пересчитываем количество голосов по оставшимся (неисключённым) участникам
        option_counts = {opt: 0 for opt in options}
        for r in responses:
            if r.user_id not in visible_user_ids:
                continue
            resp = r.response.strip()
            if resp in option_counts:
                option_counts[resp] += 1
        max_votes = max(option_counts.values()) if option_counts else 0
        leaders = [opt for opt, cnt in option_counts.items() if cnt == max_votes and max_votes > 0]

        # --- Draw Option Headers ---
        for i, option_text_lines in enumerate(wrapped_options):
            x = PADDING + NAME_COLUMN_WIDTH + (i * MIN_CELL_WIDTH)
            line_y = PADDING + 6 + title_block_height
            # Если есть эмодзи для варианта — показываем крупно
            emoji = None
            if hasattr(poll, 'option_settings'):
                try:
                    emoji = poll.option_settings[i].emoji
                except Exception:
                    emoji = None
            if emoji:
                draw.text((x + 40, line_y), emoji, font=get_system_font(28), fill=(0,0,0,255))
                line_y += 32
            for line in option_text_lines:
                draw.text((x + 8, line_y), line, font=FONT_BOLD, fill=COLOR_TEXT)
                line_y += 18
            # Лидирующий вариант — можно выделить другим способом (например, жирным текстом).
            # Убираем обводку, чтобы шапки колонок были без рамок.
            # if options[i] in leaders:
            #     draw.rounded_rectangle([(x+2, header_rect_top+2), (x+MIN_CELL_WIDTH-4, header_rect_bottom-2)], radius=12, outline=(99,201,115,255), width=4)

        # --- Draw Participant Rows ---
        for p_idx, participant in enumerate(participants):
            y = PADDING + header_height + (p_idx * CELL_HEIGHT)
            # Цвет строки
            if participant.excluded:
                row_bg = (255, 235, 238, 220)
            elif p_idx % 2 == 1:
                row_bg = (250, 250, 250, 180)
            else:
                row_bg = (255,255,255,0)
            # Скругление только у первой и последней строки
            radius = 14 if p_idx in (0, len(participants)-1) else 0
            _draw_rounded_rectangle(draw, (PADDING, y, image_width - PADDING, y + CELL_HEIGHT), radius=radius, fill=row_bg)
            # Имя
            # Draw row number
            row_number_text = str(p_idx + 1)
            draw.text((PADDING + 5, y + (CELL_HEIGHT // 2) - 8), row_number_text, font=FONT_REGULAR, fill=COLOR_TEXT)

            # Prepare and draw user name shifted right to leave space for number
            user_name = db.get_user_name(session, participant.user_id)
            if participant.username and f"@{participant.username}" not in user_name:
                user_name = f"{user_name} (@{participant.username})"
            max_name_width = NAME_COLUMN_WIDTH - NUMBER_COL_WIDTH - 10
            if FONT_REGULAR.getlength(user_name) > max_name_width:
                while FONT_REGULAR.getlength(user_name + '…') > max_name_width and len(user_name) > 1:
                    user_name = user_name[:-1]
                user_name += '…'
            draw.text((PADDING + 5 + NUMBER_COL_WIDTH, y + (CELL_HEIGHT // 2) - 8), user_name, font=FONT_REGULAR, fill=COLOR_TEXT)
            # Ячейки голосов
            for o_idx, option_text in enumerate(options):
                x = PADDING + NAME_COLUMN_WIDTH + (o_idx * MIN_CELL_WIDTH)
                voted = (participant.user_id, option_text) in votes
                # Градиент по количеству голосов за вариант
                votes_for_option = option_counts[option_text]
                if max_votes > 0:
                    norm = votes_for_option / max_votes
                    intensity = int(40 + 215 * (norm ** 1.7))  # Квадратичная шкала для контраста
                else:
                    intensity = 40
                if voted:
                    if participant.excluded:
                        # Постоянный оранжевый цвет для голосов исключённых участников
                        cell_color = (*COLOR_VOTE_EXCLUDED, 220)
                    else:
                        cell_color = (99, 201, 115, intensity)  # Вернул прежний зелёный цвет
                else:
                    cell_color = (245, 245, 245, 180)
                # Скругление только у первой/последней строки и первой/последней колонки
                cell_radius = 10 if (p_idx in (0, len(participants)-1) or o_idx in (0, len(options)-1)) else 0
                _draw_rounded_rectangle(draw, (x+4, y+4, x + MIN_CELL_WIDTH-6, y + CELL_HEIGHT-6), radius=cell_radius, fill=cell_color)
                # Акцент для лидирующего варианта
                if option_text in leaders and voted:
                    draw.rounded_rectangle([(x+8, y+8), (x+MIN_CELL_WIDTH-10, y+CELL_HEIGHT-10)], radius=cell_radius, outline=(99,201,115,255), width=3)
            # Иконка исключённого
            if participant.excluded:
                draw.text((PADDING + 5, y + (CELL_HEIGHT // 2) - 8), "🚫", font=FONT_BOLD, fill=(220,0,0,255))
        # --- Gridlines (мягкие) ---
        for i in range(len(options) + 2):
            x_pos = PADDING + NAME_COLUMN_WIDTH + (i * MIN_CELL_WIDTH) if i > 0 else PADDING
            draw.line([(x_pos, PADDING), (x_pos, image_height - PADDING)], fill=(220,220,220,120))
        for i in range(len(participants) + 1):
            y_pos = PADDING + header_height + (i * CELL_HEIGHT)
            draw.line([(PADDING, y_pos), (image_width - PADDING, y_pos)], fill=(220,220,220,120))
        # Bolder separator for names
        # Vertical separator after number+name column
        draw.line([(PADDING + NAME_COLUMN_WIDTH, PADDING), (PADDING + NAME_COLUMN_WIDTH, image_height - PADDING)], fill=(190,190,190,180), width=2)
        # Optional thinner separator between number and name
        draw.line([(PADDING + NUMBER_COL_WIDTH, PADDING + header_height), (PADDING + NUMBER_COL_WIDTH, image_height - PADDING)], fill=(220,220,220,120))
        # Outer border
        _draw_rounded_rectangle(draw, (PADDING, PADDING, image_width - PADDING, image_height - PADDING), radius=18, outline=(190,190,190,200), width=3)
        # --- Finalize ---
        out = Image.new('RGB', (image_width, image_height), (255,255,255))
        out.paste(image, (0,0), image)
        image_buffer = io.BytesIO()
        out.save(image_buffer, format='PNG')
        image_buffer.seek(0)
        
        return image_buffer

    except Exception as e:
        logger.error(f"Failed to generate heatmap for poll {poll_id}: {e}", exc_info=True)
        return None
    finally:
        if manage_session:
            session.close() 