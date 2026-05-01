from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def kb_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать диагностику", callback_data="start_diagnostic")]
    ])


def kb_grades() -> InlineKeyboardMarkup:
    grades = ["5", "6", "7", "8", "9", "10", "11"]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=g, callback_data=f"grade_{g}") for g in grades]
    ])


def kb_transfer_to_child() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Передать управление ребёнку", callback_data="transfer_to_child")]
    ])


def kb_start_test() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать тест", callback_data="begin_test")]
    ])


def kb_skip_task() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_task")]
    ])


def kb_waitlist() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Записаться в лист ожидания", callback_data="join_waitlist")],
        [InlineKeyboardButton(text="Пока нет", callback_data="skip_waitlist")],
    ])


def kb_channel(channel_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подписаться на канал", url=channel_url)],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")],
        [InlineKeyboardButton(text="Пропустить", callback_data="skip_channel")],
    ])


def kb_session_menu(channel_url: str, show_waitlist: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔄 Пройти диагностику заново", callback_data="session_restart")],
        [InlineKeyboardButton(text="👤 Диагностику проходит другой ученик", callback_data="session_new_child")],
        [InlineKeyboardButton(text="📊 Получить результаты диагностики", callback_data="session_get_results")],
    ]
    if show_waitlist:
        rows.append([InlineKeyboardButton(text="📋 Записаться в лист ожидания", callback_data="session_join_waitlist")])
    rows.append([InlineKeyboardButton(text="📢 Подписаться на канал", url=channel_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_retry_subscription() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")],
    ])


def kb_children_list(children: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """children: list of (notion_page_id, child_name)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"child_{page_id}")]
        for page_id, name in children
    ])
