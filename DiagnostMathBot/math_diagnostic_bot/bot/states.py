from aiogram.fsm.state import State, StatesGroup


class Questionnaire(StatesGroup):
    waiting_parent_name = State()
    waiting_parent_phone = State()
    waiting_child_name = State()
    waiting_child_grade = State()


class Test(StatesGroup):
    instructions = State()
    waiting_answer = State()


class Report(StatesGroup):
    generating = State()


class CTA(StatesGroup):
    waitlist = State()
    channel = State()


class Session(StatesGroup):
    menu = State()
    selecting_child = State()
