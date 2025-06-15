import re
from telegram.helpers import escape_markdown
from . import database as db
from .config import logger

def get_progress_bar(progress, total, length=20):
    if total <= 0: return "\\[\\]", 0
    percent = progress / total
    filled_length = int(length * percent)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"\\[{bar}\\]", percent * 100

def generate_poll_text(poll_id: int) -> str:
    """Generates the text to display for a poll, including results."""
    poll = db.get_poll(poll_id)
    if not poll: return "Опрос не найден."
    
    message, options_str = poll.message, poll.options
    original_options = [opt.strip() for opt in options_str.split(',')]
    
    responses = db.get_responses(poll_id)
    
    # --- DEBUG LOGGING ---
    raw_responses_log = [f"(User: {r.user_id}, Vote: '{r.response}')" for r in responses]
    logger.info(f"[DEBUG_DISPLAY] Generating text for poll {poll_id}. Raw responses from DB: {raw_responses_log}")
    # --- END DEBUG LOGGING ---

    votes_by_option = {opt.strip(): [] for opt in original_options}
    user_votes = {} # To track which option a user voted for

    for r in responses:
        # Normalize the response from DB to match a clean option from the poll
        cleaned_response = r.response.strip()
        if cleaned_response in votes_by_option:
            votes_by_option[cleaned_response].append(r.user_id)
        user_votes[r.user_id] = cleaned_response

    counts = {opt: 0 for opt in original_options}
    for resp in responses:
        if resp.response in counts: counts[resp.response] += 1
        
    poll_setting = db.get_poll_setting(poll_id)
    default_show_names = poll_setting.default_show_names if poll_setting else 1
    target_sum = poll_setting.target_sum if poll_setting else 0
    default_show_count = poll_setting.default_show_count if poll_setting else 1
    
    total_votes = len(responses)
    total_collected = 0
    text_parts = [escape_markdown(message, version=2), ""]

    options_with_settings = []
    for i, option_text in enumerate(original_options):
        opt_setting = db.get_poll_option_setting(poll_id, i)
        options_with_settings.append({
            'text': option_text,
            'show_names': opt_setting.show_names if opt_setting and opt_setting.show_names is not None else default_show_names,
            'names_style': opt_setting.names_style if opt_setting and opt_setting.names_style else 'list',
            'is_priority': opt_setting.is_priority if opt_setting else 0,
            'contribution_amount': opt_setting.contribution_amount if opt_setting else 0,
            'emoji': (opt_setting.emoji + ' ') if opt_setting and opt_setting.emoji else "",
            'show_count': opt_setting.show_count if opt_setting and opt_setting.show_count is not None else default_show_count,
            'show_contribution': opt_setting.show_contribution if opt_setting and opt_setting.show_contribution is not None else 1,
        })

    options_with_settings.sort(key=lambda x: x['is_priority'], reverse=True)

    for option_data in options_with_settings:
        option_text = option_data['text']
        count = counts.get(option_text, 0)
        contribution = option_data['contribution_amount']
        if contribution > 0: total_collected += count * contribution
            
        marker = "⭐ " if option_data['is_priority'] else ""
        escaped_option_text = escape_markdown(option_text, version=2)
        formatted_text = f"*{escaped_option_text}*" if option_data['is_priority'] else escaped_option_text
        line = f"{marker}{formatted_text}"
        if contribution > 0 and option_data['show_contribution']:
            line += f" \\(по {int(contribution)}\\)"
        if option_data['show_count']:
            line += f": *{count}*"
        text_parts.append(line)

        if option_data['show_names'] and count > 0:
            user_ids_for_option = votes_by_option.get(option_text, [])
            user_names = [db.get_user_name(uid, markdown_link=True) for uid in user_ids_for_option]
            logger.info(f"[DEBUG] User names for option '{option_text}' in poll {poll_id}: {user_names}")
            names_list = [f"{option_data['emoji']}{name}" for name in user_names]
            indent = "    "
            if option_data['names_style'] == 'list': text_parts.append("\n".join(f"{indent}{name}" for name in names_list))
            elif option_data['names_style'] == 'inline': text_parts.append(f'{indent}{", ".join(names_list)}')
            elif option_data['names_style'] == 'numbered': text_parts.append("\n".join(f"{indent}{i}\\. {name}" for i, name in enumerate(names_list, 1)))
        text_parts.append("")

    if target_sum > 0:
        bar, percent = get_progress_bar(total_collected, target_sum)
        formatted_percent = f"{percent:.1f}".replace('.', '\\.')
        text_parts.append(f"💰 Собрано: *{int(total_collected)} из {int(target_sum)}* \\({formatted_percent}%\\)\n{bar}")
    elif total_collected > 0:
        text_parts.append(f"💰 Собрано: *{int(total_collected)}*")
    
    while text_parts and text_parts[-1] == "": text_parts.pop()
    text_parts.append(f"\nВсего проголосовало: *{total_votes}*")
    final_text = "\n".join(text_parts)
    logger.info(f"[DEBUG] Final poll text for poll {poll_id}:\n{final_text}")
    return final_text

async def generate_nudge_text(poll_id: int) -> str:
    """Generates the text to nudge non-voters."""
    poll = db.get_poll(poll_id)
    if not poll: return "Опрос не найден."
    
    participants = db.get_participants(poll.chat_id)
    participant_ids = {p.user_id for p in participants if not p.excluded}

    respondents = db.get_responses(poll_id)
    respondent_ids = {r.user_id for r in respondents}
    
    non_voters = participant_ids - respondent_ids

    poll_setting = db.get_poll_setting(poll_id)
    neg_emoji = poll_setting.nudge_negative_emoji if poll_setting and poll_setting.nudge_negative_emoji else '❌'

    text_parts = ["📢 *Ждем вашего голоса:*"]
    
    if not non_voters:
        text_parts.append("\n_Все участники проголосовали!_ 🎉")
    else:
        text_parts.append("")
        # Sorting by name requires fetching all names, which can be slow.
        # For simplicity, we sort by user_id. For real applications, consider sorting after fetching names.
        sorted_non_voters = sorted(list(non_voters))
        for user_id in sorted_non_voters:
            user_mention = db.get_user_name(user_id, markdown_link=True)
            text_parts.append(f"{neg_emoji} {user_mention}")

    return "\n".join(text_parts) 