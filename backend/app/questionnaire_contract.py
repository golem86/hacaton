"""
Контракт анкети між backend і frontend (Digital Questionnaire, №1).

Правила шкали (погоджено №5):
  - межі — безпечні цілі числа (як Number.isSafeInteger у JavaScript), не bool;
  - scale_min <= scale_max;
  - кількість значень (scale_max − scale_min + 1) від 1 до 10 включно;
  - стандартна шкала — [1, 5].

Шкала з одним значенням допустима, але не впливає на бал компонента:
формула (value − min) / (max − min) для неї не визначена (див. routes/results.py).

Ці правила перевіряються в трьох місцях:
  1. модель Question — некоректну шкалу не можна записати в БД (seed, майбутній API);
  2. GET /questionnaires — відповідь перевіряється перед видачею фронтенду;
  3. POST /submissions — некоректна заповнена анкета отримує HTTP 422.
"""
from pydantic import BaseModel, Field, RootModel, StrictInt, StrictStr, model_validator

MIN_SCALE_VALUES = 1
MAX_SCALE_VALUES = 10
DEFAULT_SCALE = (1, 5)
SAFE_INTEGER = 2**53 - 1   # Number.MAX_SAFE_INTEGER у JavaScript


def scale_error(scale_min, scale_max) -> str | None:
    """Повертає пояснення, чому шкала некоректна, або None, якщо все гаразд."""
    for name, bound in (("scale_min", scale_min), ("scale_max", scale_max)):
        if type(bound) is not int:              # bool, float, str, None — не підходять
            return f"{name} має бути цілим числом"
        if abs(bound) > SAFE_INTEGER:
            return f"{name} виходить за межі безпечного цілого числа"
    if scale_min > scale_max:
        return "scale_min не може бути більшим за scale_max"
    count = scale_max - scale_min + 1
    if not MIN_SCALE_VALUES <= count <= MAX_SCALE_VALUES:
        return f"шкала має містити від {MIN_SCALE_VALUES} до {MAX_SCALE_VALUES} значень, а не {count}"
    return None


def validate_scale(scale_min, scale_max) -> None:
    error = scale_error(scale_min, scale_max)
    if error:
        raise ValueError(f"Некоректна шкала [{scale_min}, {scale_max}]: {error}")


SafeId = Field(ge=1, le=SAFE_INTEGER)


class QuestionOut(BaseModel):
    id: StrictInt = SafeId
    text: StrictStr = Field(min_length=1)
    scale: tuple[StrictInt, StrictInt]

    @model_validator(mode="after")
    def check_scale(self):
        validate_scale(*self.scale)
        return self


class ComponentOut(BaseModel):
    code: StrictStr
    name: StrictStr
    weight: float
    questions: list[QuestionOut]


class Questionnaire(RootModel[list[ComponentOut]]):
    """Уся анкета: id питань мають бути унікальними між УСІМА компонентами."""

    @model_validator(mode="after")
    def check_unique_question_ids(self):
        seen: set[int] = set()
        for component in self.root:
            for question in component.questions:
                if question.id in seen:
                    raise ValueError(f"Питання з id {question.id} повторюється в анкеті")
                seen.add(question.id)
        return self
