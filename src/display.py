import re
import io
from telegram.helpers import escape_markdown
from . import database as db
from .config import logger
from .drawing import generate_results_heatmap_image
from typing import Optional, Tuple
from sqlalchemy.orm import Session

def get_progress_bar(progress, total, length=20):
    if total <= 0: return "\\[\\]", 0
    percent = progress / total
    filled_length = int(length * percent)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"\\[{bar}\\]", percent * 100

def generate_poll_content(poll_id: int = None, poll: Optional[db.Poll] = None, session: Optional[Session] = None) -> Tuple[str, Optional[io.BytesIO]]:
    """
    Generates the text caption and heatmap image for a poll.
    Returns a tuple: (text, image_bytes)
    """
    manage_session = session is None
    image_bytes = None

    try:
        if manage_session:
            session = db.SessionLocal()

        if not poll and poll_id is not None:
            # If we have a session, we should use it for the query.
            poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
        elif poll and not manage_session:
            # If the poll object was passed from another session, merge it into ours
            # to avoid the "already attached" error.
            poll = session.merge(poll)
        
        if not poll:
            logger.error(f"generate_poll_content: Poll with ID {poll_id} not found.")
            return "Опрос не найден.", None
        
        # Ensure poll_id is set for other functions that might need it.
        if poll_id is None:
            poll_id = poll.poll_id

        message = poll.message
        responses = db.get_responses(poll_id)
        
        # --- Determine the options to display ---
        # Start with the options defined in the poll.
        display_options = []
        if poll.options and poll.options != 'Web App Poll': # Avoid the old placeholder
             display_options = [opt.strip() for opt in poll.options.split(',')]
        
        # For any poll type, dynamically add options found in responses
        # that aren't already in our list. This makes it robust.
        if responses:
            voted_options = list(dict.fromkeys(r.response.strip() for r in responses))
            for opt in voted_options:
                if opt not in display_options:
                    display_options.append(opt)

        votes_by_option = {opt: [] for opt in display_options}
        # This now stores a list of responses for each user.
        user_votes = {r.user_id: [] for r in responses}

        for r in responses:
            # Normalize the response from DB to match a clean option from the poll
            cleaned_response = r.response.strip()
            if cleaned_response in votes_by_option:
                votes_by_option[cleaned_response].append(r.user_id)
            user_votes[r.user_id].append(cleaned_response)

        counts = {opt: 0 for opt in display_options}
        for resp in responses:
            if resp.response in counts: counts[resp.response] += 1
            
        poll_setting = db.get_poll_setting(poll_id)
        # For webapp polls, we don't have per-option settings from the DB,
        # so we rely only on the poll-wide defaults.
        default_show_names = poll_setting.default_show_names if poll_setting and poll_setting.default_show_names is not None else 1
        default_show_count = poll_setting.default_show_count if poll_setting and poll_setting.default_show_count is not None else 1

        # In multiple choice polls, the number of voters is unique users, not total responses.
        total_voters = len(user_votes)
        text_parts = [escape_markdown(message, version=2), ""]

        # Add a clear 'closed' status if applicable
        if poll.status == 'closed':
            text_parts.insert(0, "*ОПРОС ЗАВЕРШЕН*")
            text_parts.insert(1, "\\-\\-\\-") # Separator

        # For webapp polls, if there are no votes yet, don't show the options list.
        # This avoids a Telegram API conflict on the initial message send.
        if poll.poll_type == 'webapp' and not user_votes:
            # The text will just be the title and the total votes (0).
            pass
        # For webapp polls WITH votes, or for all native polls:
        elif poll.poll_type == 'webapp':
            for option_text in display_options:
                count = counts.get(option_text, 0)
                escaped_option_text = escape_markdown(option_text, version=2)
                line = f"{escaped_option_text}: *{count}*"
                text_parts.append(line)

                if default_show_names and count > 0:
                    user_ids_for_option = votes_by_option.get(option_text, [])
                    user_names = [db.get_user_name(session, uid, markdown_link=True) for uid in user_ids_for_option]
                    names_list = [f"▫️ {name}" for name in user_names]
                    text_parts.append("\n".join(f"    {name}" for name in names_list))
                text_parts.append("")

        else: # Native poll display logic
            options_with_settings = []
            original_options = [opt.strip() for opt in poll.options.split(',')]
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

            total_collected = 0 # Specific to native polls with contributions
            target_sum = poll_setting.target_sum if poll_setting and poll_setting.target_sum is not None else 0

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
                    user_names = [db.get_user_name(session, uid, markdown_link=True) for uid in user_ids_for_option]
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
        
        # Display the number of unique voters.
        text_parts.append(f"\nВсего проголосовало: *{total_voters}*")
        final_text = "\n".join(text_parts)
        
        # --- Image Generation ---
        show_heatmap = poll_setting.show_heatmap if poll_setting is not None else True
        image_bytes = None
        # Generate heatmap only if there are votes and the setting is enabled
        if responses and show_heatmap:
            image_bytes = generate_results_heatmap_image(
                poll_id=poll_id,
                session=session
            )
        
        # We only commit if we created the session inside this function.
        # The calling function is responsible for committing if it passed its own session.
        if manage_session:
            session.commit()
        
        logger.info(f"[DEBUG] Final poll text for poll {poll_id}:\n{final_text}")
        return final_text, image_bytes
    finally:
        # Only close the session if we created it here.
        if manage_session and session:
            session.close()

async def generate_nudge_text(poll_id: int) -> str:
    """Generates the text to nudge non-voters."""
    session = db.SessionLocal()
    try:
        poll = db.get_poll(poll_id)
        if not poll: return "Опрос не найден."
        
        participants = db.get_participants(poll.chat_id, session=session)
        # Исключения на уровне опроса
        poll_excl = db.get_poll_exclusions(poll_id, session=session)

        participant_ids = {p.user_id for p in participants if (not p.excluded) and (p.user_id not in poll_excl)}

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
                user_mention = db.get_user_name(session, user_id, markdown_link=True)
                text_parts.append(f"{neg_emoji} {user_mention}")

        final_text = "\n".join(text_parts)
        session.commit()
        return final_text
    finally:
        session.close() 