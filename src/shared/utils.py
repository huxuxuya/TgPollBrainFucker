# Общие утилиты для всех модулей (генерация таблиц, диалоги, валидация)

def generate_table(data, headers=None, fmt="text"):
    """
    Универсальная генерация таблицы (text или html).
    data: список списков (строки таблицы)
    headers: список заголовков
    fmt: "text" или "html"
    """
    if fmt == "html":
        html = "<table>"
        if headers:
            html += "<tr>" + ''.join(f"<th>{h}</th>" for h in headers) + "</tr>"
        for row in data:
            html += "<tr>" + ''.join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        html += "</table>"
        return html
    else:
        lines = []
        if headers:
            lines.append(" | ".join(headers))
            lines.append("-|-" * len(headers))
        for row in data:
            lines.append(" | ".join(str(cell) for cell in row))
        return "\n".join(lines)

def ask_user_input(prompt):
    # Заглушка для универсального диалога запроса ввода
    return f"[Диалог] {prompt}"

def confirm_action(prompt):
    # Заглушка для универсального диалога подтверждения
    return f"[Подтвердите] {prompt}"

def validate_user_data(data, schema=None):
    # Простейшая валидация (можно расширить под pydantic/schemas)
    if not data:
        return False, "Пустые данные"
    return True, "" 