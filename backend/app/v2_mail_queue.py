"""
Фонова черга листів Dashboard V2 (скидання пароля).

Маршрут запиту коду скидання лише ставить завдання в чергу і відповідає одразу, тож час відповіді
не залежить від існування акаунта й швидкості SMTP. Один фоновий потік-воркер виконує завдання по черзі.
Черга обмежена: при переповненні завдання відкидається (відповідь клієнту та сама), подія лише логується.
Помилки завдань логуються лише назвою класу винятку — без email, кодів, адрес SMTP і traceback.
"""
import logging
import queue
import threading
import time
from typing import Callable

log = logging.getLogger("app.v2_mail")

QUEUE_MAXSIZE = 100


class MailQueue:
    def __init__(self, maxsize: int = QUEUE_MAXSIZE):
        self._queue: queue.Queue[Callable[[], object]] = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def submit(self, job: Callable[[], object]) -> bool:
        """Ставить завдання в чергу без очікування. False — черга переповнена, завдання відкинуто."""
        self._ensure_worker()
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            log.warning("Черга листів переповнена: завдання відкинуто")
            return False
        return True

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Чекає, доки всі поставлені завдання виконано (для тестів і зупинки). False — вийшов час."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._queue.all_tasks_done.wait(remaining)
        return True

    def _ensure_worker(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="v2-mail-worker", daemon=True)
                self._thread.start()

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                job()
            except Exception as error:   # noqa: BLE001 — воркер не має падати; деталі можуть містити email
                log.error("Фонове надсилання листа не вдалося: %s", type(error).__name__)
            finally:
                self._queue.task_done()


mail_queue = MailQueue()
