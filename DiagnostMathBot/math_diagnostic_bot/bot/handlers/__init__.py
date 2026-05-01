from aiogram import Dispatcher

from bot.handlers import start, session, questionnaire, test, report, cta, admin


def register_all_handlers(dp: Dispatcher) -> None:
    start.register(dp)
    session.register(dp)
    questionnaire.register(dp)
    test.register(dp)
    report.register(dp)
    cta.register(dp)
    admin.register(dp)
