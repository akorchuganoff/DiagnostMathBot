import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger(__name__)

_TICK = 10  # seconds between countdown edits

_timers: dict[int, asyncio.Task] = {}


def format_remaining(seconds: int) -> str:
    display = (seconds // 10) * 10  # floor to nearest 10 so seconds always divisible by 10
    m, s = divmod(display, 60)
    if m > 0:
        return f"⏱ Осталось {m} мин {s} сек"
    return f"⏱ Осталось {s} сек"


def start_timer(
    user_id: int,
    delay_sec: int,
    on_timeout: Callable[[], Coroutine[Any, Any, None]],
    *,
    bot: "Bot | None" = None,
    chat_id: int | None = None,
    timer_msg_id: int | None = None,
) -> None:
    cancel_timer(user_id)

    async def _run() -> None:
        from bot.messages import TIMER_EXPIRED

        try:
            remaining = delay_sec
            while remaining > 0:
                tick = min(_TICK, remaining)
                await asyncio.sleep(tick)
                remaining -= tick
                if bot and chat_id and timer_msg_id:
                    text = TIMER_EXPIRED if remaining <= 0 else format_remaining(remaining)
                    try:
                        await bot.edit_message_text(text, chat_id=chat_id, message_id=timer_msg_id)
                    except Exception:
                        pass
            await on_timeout()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Timer on_timeout error for user_id=%d", user_id)
        finally:
            _timers.pop(user_id, None)

    _timers[user_id] = asyncio.create_task(_run())


def cancel_timer(user_id: int) -> None:
    task = _timers.pop(user_id, None)
    if task and not task.done():
        task.cancel()
