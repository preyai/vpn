from aiogram.fsm.state import State, StatesGroup


class WGCreate(StatesGroup):
    name = State()


class XrayCreate(StatesGroup):
    name = State()
