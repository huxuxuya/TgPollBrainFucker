import sys
from src import database as db

if __name__ == '__main__':
    try:
        chat_id = int(input('Введите chat_id чата: '))
    except ValueError:
        print('Некорректный chat_id!')
        sys.exit(1)
    participants = db.get_participants(chat_id)
    if not participants:
        print('Нет участников для этого чата.')
    else:
        print(f'Участники чата {chat_id}:')
        for p in participants:
            print(f"user_id={p.user_id} | username={p.username} | first_name={p.first_name} | last_name={p.last_name} | excluded={p.excluded}") 