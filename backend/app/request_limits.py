"""
Обмеження вхідних даних API (docs/V2_HARDENING_CONTRACT.md, розділ 3 «Поведінка даних»).

1. Цілі id у шляху й запиті — лише 1..2^63-1 (BoundedId, IdQuery, OptionalIdQuery).
   Більші числа SQLite не вміщує: без обмеження запит падав з 500 (OverflowError),
   тепер це звичайна 422. Використання:
       def read(assessment_id: BoundedId, ...)                 # параметр шляху
       def compare(assessment_id: IdQuery, other: OptionalIdQuery = None, ...)

2. Ліміт тіла запиту (BodySizeLimitMiddleware) — V2_MAX_BODY_BYTES, за замовчуванням 64 KiB:
   - Content-Length більший за ліміт → 413 одразу, тіло не читається взагалі;
   - тіло без Content-Length (chunked) читається частинами з лічильником; щойно сума
     перевищила ліміт → 413, решта не читається. У пам'яті — не більше ліміту;
   - перевірка працює ДО маршрутизації й автентифікації, для всіх адрес.

3. Відповідь 422 (validation_error_handler) містить лише loc/msg/type кожної помилки:
   без `input` і `ctx`, тож сервер не повертає назад надіслані дані (раніше 30 МБ тіла
   поверталися у відповіді 422 цілком).
"""
import os
from typing import Annotated

from fastapi import Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

MAX_ID = 2**63 - 1            # найбільше ціле SQLite (INTEGER, 8 байтів зі знаком)
BoundedId = Annotated[int, Path(ge=1, le=MAX_ID)]
IdQuery = Annotated[int, Query(ge=1, le=MAX_ID)]
OptionalIdQuery = Annotated[int | None, Query(ge=1, le=MAX_ID)]

DEFAULT_MAX_BODY_BYTES = 64 * 1024
_LOC_TEXT_LIMIT = 64          # ключі з тіла запиту в loc обрізаються, щоб не віддзеркалювати довгий ввід


def max_body_bytes() -> int:
    """Ліміт тіла з V2_MAX_BODY_BYTES (додатне ціле число байтів)."""
    raw = os.environ.get("V2_MAX_BODY_BYTES", "").strip()
    if not raw:
        return DEFAULT_MAX_BODY_BYTES
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise RuntimeError("V2_MAX_BODY_BYTES має бути додатним цілим числом байтів")
    return value


async def _send_json(send, status: int, detail: str) -> None:
    body = ('{"detail":"' + detail + '"}').encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode("ascii")),
                            (b"connection", b"close")]})
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    """Чистий ASGI-middleware: 413 для тіла понад ліміт без читання (і зберігання) решти тіла."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = max_body_bytes()
        declared = Headers(scope=scope).get("content-length")
        if declared is not None:
            if not declared.strip().isdigit():
                await _send_json(send, 400, "Invalid Content-Length")
                return
            if int(declared) > limit:
                await _send_json(send, 413, "Request body too large")
                return

        # Тіло читається з лічильником (і для Content-Length — на випадок сервера без перевірки рамок)
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return                                   # клієнт пішов: застосунок не викликаємо
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > limit:
                await _send_json(send, 413, "Request body too large")
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()                        # далі — події з'єднання (http.disconnect)

        await self.app(scope, replay, send)


def _safe_loc(loc) -> list:
    return [part if isinstance(part, int) else str(part)[:_LOC_TEXT_LIMIT] for part in loc or ()]


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 без `input` і `ctx`: лише де (loc), що (msg) і код помилки (type)."""
    errors = [{"loc": _safe_loc(error.get("loc")), "msg": str(error.get("msg", "")),
               "type": str(error.get("type", ""))} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})
