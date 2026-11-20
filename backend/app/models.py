"""
Таблиці бази даних.

Кожен клас нижче = одна таблиця (як аркуш в Excel).
Кожне поле `Mapped[...] = mapped_column(...)` = одна колонка.

ГОЛОВНЕ ПРАВИЛО АНОНІМНОСТІ:
у таблицях з відповідями НЕМАЄ жодного поля, яке вказує на людину
(ні імені, ні ID користувача, ні точного часу відправки).
Токени доступу лежать в окремій таблиці і НЕ пов'язані з відповідями.
"""
import hashlib
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, event)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


# ---------------------------------------------------------------------------
# 1. МЕТОДИКА: що саме ми оцінюємо
# ---------------------------------------------------------------------------

class Component(Base):
    """Компонент системи доброчесності, напр. «Повідомлення про порушення»."""
    __tablename__ = "components"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)   # коротке позначення: C1, C2...
    name: Mapped[str] = mapped_column(String(200))
    weight: Mapped[float] = mapped_column(Float)                  # вага в Integrity Index (0.15 = 15%)

    # «зв'язок»: дозволяє писати component.questions і отримати всі питання компонента
    questions: Mapped[list["Question"]] = relationship(back_populates="component")


class Question(Base):
    """Питання анкети (з додатка В) або пункт чек-листа (з додатка Б)."""
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"))  # до якого компонента належить
    text: Mapped[str] = mapped_column(Text)
    scale_min: Mapped[int] = mapped_column(Integer, default=1)   # шкала відповіді, напр. від 1...
    scale_max: Mapped[int] = mapped_column(Integer, default=5)   # ...до 5
    # для кого питання: "survey" — анкета персоналу, "expert" — експертне оцінювання
    kind: Mapped[str] = mapped_column(String(20), default="survey")

    component: Mapped[Component] = relationship(back_populates="questions")


@event.listens_for(Question, "before_insert")
@event.listens_for(Question, "before_update")
def _check_question_scale(_mapper, _connection, question: Question) -> None:
    """Некоректну шкалу (див. questionnaire_contract.py) не можна записати в БД."""
    from .questionnaire_contract import DEFAULT_SCALE, validate_scale
    scale_min = DEFAULT_SCALE[0] if question.scale_min is None else question.scale_min
    scale_max = DEFAULT_SCALE[1] if question.scale_max is None else question.scale_max
    validate_scale(scale_min, scale_max)


# ---------------------------------------------------------------------------
# 2. ЦИКЛИ ОЦІНЮВАННЯ: коли оцінювали (потрібно для динаміки)
# ---------------------------------------------------------------------------

class Cycle(Base):
    """Один раунд оцінювання, напр. «2026-II». Порівнюючи цикли, бачимо динаміку."""
    __tablename__ = "cycles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    start_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="open")   # open / closed
    # мінімальний розмір групи: групи з меншою кількістю відповідей НЕ показуються
    min_group_size: Mapped[int] = mapped_column(Integer, default=5)


class CycleConfig(Base):
    """Додаткові параметри нових циклів; старі seed-цикли зберігають свій контракт."""
    __tablename__ = "cycle_configs"

    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[str] = mapped_column(String(200), default="")
    categories_json: Mapped[str] = mapped_column(Text)
    questionnaire_version: Mapped[str] = mapped_column(String(50), default="demo-v1")
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)


# ---------------------------------------------------------------------------
# 3. ВІДПОВІДІ: анонімно!
# ---------------------------------------------------------------------------

class Unit(Base):
    """
    Довідник підрозділів. Анкета може посилатися ЛИШЕ на підрозділ з цього списку —
    так у базу не потрапить довільний текст (напр. прізвище чи номер кімнати).
    """
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class ResponseSet(Base):
    """
    Одна заповнена анкета. Зберігаємо ЛИШЕ категорію і підрозділ —
    цього досить для аналітики й недостатньо, щоб упізнати людину.
    """
    __tablename__ = "response_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"))
    respondent_category: Mapped[str] = mapped_column(String(30))  # mgmt / npp / cadets / staff / expert
    # підрозділ — лише назва з довідника units (база сама відхилить інший текст)
    unit: Mapped[str] = mapped_column(ForeignKey("units.name"))
    # Навмисно НЕМАЄ: user_id, імені, email, точного часу відправки.

    answers: Mapped[list["Answer"]] = relationship(back_populates="response_set")


class Answer(Base):
    """Відповідь на одне питання в межах однієї анкети."""
    __tablename__ = "answers"
    # на одне питання в одній анкеті — лише одна відповідь (перевіряє сама база)
    __table_args__ = (UniqueConstraint("response_set_id", "question_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    response_set_id: Mapped[int] = mapped_column(ForeignKey("response_sets.id"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    value: Mapped[int] = mapped_column(Integer)   # напр. 4 за шкалою 1–5

    response_set: Mapped[ResponseSet] = relationship(back_populates="answers")


def hash_access_code(code: str) -> str:
    """SHA-256 (hex) одноразового коду. У БД зберігається лише він (schema 5), не сам код."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class AccessToken(Base):
    """
    Одноразовий код для проходження анкети.
    Знаємо лише, ЧИ використано код, але НЕ знаємо, яка анкета ним заповнена:
    тут немає посилання на ResponseSet.

    Schema 5: зберігається лише token_hash = SHA-256 коду. Відкритий код повертається
    один раз у відповіді POST /tokens (лише роль data_officer) і в БД не потрапляє.
    Коди — 128 випадкових біт, тож перебір хешу непрактичний, а «сіль» не потрібна.

    Залишковий ризик (I3): анкети й коди лежать у різних таблицях без посилань, але
    порядок рядків (id) у БД зберігається. Той, хто має два знімки БД (до і після
    подання), бачить, який рядок access_tokens став used=1 і яка анкета з'явилась.
    Після D1 (admin не отримує кодів, їх видає лише data_officer) і D5 (у БД лише хеші)
    зіставити рядок коду з людиною можна лише маючи і копії БД, і журнал роздачі кодів
    поза системою. Захист — доступ до файлів БД і резервних копій лише для служби й
    адміністраторів сервера (див. також anonymity.py).
    """
    __tablename__ = "access_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)   # SHA-256 hex, не сам код
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class AccessTokenPolicy(Base):
    """Категорія та строк коду, без посилання на анкету чи особу."""
    __tablename__ = "access_token_policies"

    token_id: Mapped[int] = mapped_column(ForeignKey("access_tokens.id"), primary_key=True)
    category: Mapped[str] = mapped_column(String(30))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


# ---------------------------------------------------------------------------
# 4. ОБ'ЄКТИВНІ ПОКАЗНИКИ: факти, з якими порівнюємо самооцінку
# ---------------------------------------------------------------------------

class ObjectiveIndicator(Base):
    """Факт, напр. «% персоналу, що пройшов навчання» = 81. Вносить один, підтверджує інший."""
    __tablename__ = "objective_indicators"

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"))
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"))
    name: Mapped[str] = mapped_column(String(200))
    value: Mapped[float] = mapped_column(Float)                    # вже переведене в 0–100
    entered_by_role: Mapped[str] = mapped_column(String(50))       # роль, не ім'я
    confirmed_by_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------------------
# 5. РЕКОМЕНДАЦІЇ І ЇХ ВИКОНАННЯ
# ---------------------------------------------------------------------------

class Recommendation(Base):
    """Рекомендація: система пропонує, посадова особа приймає, далі контроль виконання."""
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"))
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"))
    text: Mapped[str] = mapped_column(Text)                        # що зробити
    basis: Mapped[str] = mapped_column(Text)                       # «на підставі чого» — пояснення
    # proposed (запропоновано) / accepted / rejected / in_progress / done / overdue
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    owner_role: Mapped[str | None] = mapped_column(String(100), nullable=True)  # відповідальний (роль)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)          # строк


class RecommendationAction(Base):
    """
    Recommendations Tracker: рішення посадової особи щодо пропозиції і контроль виконання.

    Пропозиції генеруються детерміновано й не зберігаються; тут — лише ухвалене людиною
    рішення (прийнято / відхилено) зі знімком тексту, взятим із серверної пропозиції.
    Одне рішення на пропозицію в циклі (унікальність перевіряє сама база).

    Персональних даних немає: відповідальний — посада чи підрозділ (не ПІБ),
    в історії — роль того, хто змінив статус, а не ім'я.
    """
    __tablename__ = "recommendation_actions"
    __table_args__ = (UniqueConstraint("assessment_id", "recommendation_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"))
    recommendation_id: Mapped[str] = mapped_column(String(64))       # відбиток пропозиції (fingerprint)
    rule_id: Mapped[str] = mapped_column(String(50))
    component_code: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)                          # знімок тексту пропозиції
    methodology_version: Mapped[str] = mapped_column(String(50))
    # accepted / rejected / in_progress / completed / verified (автомат у services/tracker.py)
    status: Mapped[str] = mapped_column(String(20))
    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)   # посада/підрозділ, не ПІБ
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    decision_reason: Mapped[str] = mapped_column(Text)
    evidence_refs_json: Mapped[str] = mapped_column(Text, default="[]")     # JSON-список посилань на докази
    # пізніше закрите оцінювання, яке перевірило результат (для статусу verified)
    verified_in_assessment_id: Mapped[int | None] = mapped_column(ForeignKey("cycles.id"), nullable=True)
    history_json: Mapped[str] = mapped_column(Text, default="[]")           # JSON: from/to/reason/at/роль
    created_at: Mapped[datetime] = mapped_column(DateTime)                  # час сервера (UTC)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


# ---------------------------------------------------------------------------
# 6. ЖУРНАЛ ДІЙ (Audit Trail)
# ---------------------------------------------------------------------------

class AuditEvent(Base):
    """
    Запис про адміністративну дію: хто (роль), що, коли, над яким циклом.

    НІКОЛИ не зберігаємо: коди доступу, відповіді анкет, категорію чи підрозділ
    респондента. Подання анкет не журналюється взагалі — інакше час подання
    разом із розкладом людей міг би розкрити автора анкети.
    """
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)        # час сервера (UTC)
    actor_role: Mapped[str] = mapped_column(String(50))           # роль, не ім'я
    action: Mapped[str] = mapped_column(String(50))               # напр. "tokens.issue"
    assessment_id: Mapped[int | None] = mapped_column(ForeignKey("cycles.id"), nullable=True)
    details: Mapped[str] = mapped_column(Text, default="{}")      # JSON без чутливих даних
    # Schema 5: id користувача V2_AUTH_DB (без email та імені); NULL — CLI або демо-заголовок X-Role
    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# 7. МЕТАДАНІ ЕКЗЕМПЛЯРА
# ---------------------------------------------------------------------------

class InstanceMeta(Base):
    """
    Службові позначки екземпляра БД (schema 5), напр. ('dataset', 'synthetic') від seed.
    Аналітика демо в release працює лише на БД з цією позначкою (routes/analytics.py).
    """
    __tablename__ = "instance_meta"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text)


# ---------------------------------------------------------------------------
# 8. ЗРІЛІСТЬ ЗА ДОДАТКОМ В (schema 6)
# ---------------------------------------------------------------------------

class AnnexVResponse(Base):
    """
    Одна анонімна анкета Додатка В. Як і ResponseSet: лише категорія, форма і версія шаблону.
    Навмисно НЕМАЄ: user_id, коду доступу, підрозділу, часу подання (навіть дати).
    """
    __tablename__ = "annex_v_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"))
    respondent_category: Mapped[str] = mapped_column(String(30))     # mgmt / npp / cadets / staff
    form: Mapped[int] = mapped_column(Integer)                        # 1 або 2
    version: Mapped[str] = mapped_column(String(20))                  # версія шаблону, "2.0.0"

    answers: Mapped[list["AnnexVAnswer"]] = relationship(back_populates="response")


class AnnexVAnswer(Base):
    """Обраний варіант (id з каталогу annex_v.py) на одне питання анкети Додатка В."""
    __tablename__ = "annex_v_answers"
    __table_args__ = (UniqueConstraint("response_id", "question_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("annex_v_responses.id"))
    question_id: Mapped[str] = mapped_column(String(40))
    option_id: Mapped[str] = mapped_column(String(40))

    response: Mapped[AnnexVResponse] = relationship(back_populates="answers")


class AnnexVExpertAssessment(Base):
    """Експертна оцінка за формою 1. Експерт — посада/роль (expert_label), не ПІБ; вносить admin."""
    __tablename__ = "annex_v_expert_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"))
    expert_label: Mapped[str] = mapped_column(String(120))
    form: Mapped[int] = mapped_column(Integer)
    version: Mapped[str] = mapped_column(String(20))
    answers_json: Mapped[str] = mapped_column(Text)                   # {id питання: id варіанта}
    entered_role: Mapped[str] = mapped_column(String(50))
    entered_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)            # час сервера (UTC)


class ChecklistEntry(Base):
    """
    Стан пункту чек-листа (Додаток Б, адаптовано) у циклі. Вносить data_officer (або admin),
    підтверджує admin — інший користувач. У API — лише ролі; id користувача V2 (без email та імені)
    зберігається тільки для правила «не можна підтвердити власний запис».
    """
    __tablename__ = "checklist_entries"
    __table_args__ = (UniqueConstraint("cycle_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"))
    code: Mapped[str] = mapped_column(String(10))                     # B-01 … з каталогу annex_v.py
    status: Mapped[str] = mapped_column(String(10))                   # yes / partial / no
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    entered_role: Mapped[str] = mapped_column(String(50))
    entered_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entered_at: Mapped[datetime] = mapped_column(DateTime)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MaturityIndicator(Base):
    """
    Об'єктивний показник критерію Додатка В (%, значення і цільове значення за період).
    Окремо від старої таблиці objective_indicators (Integrity Index), яку не змінюємо.
    """
    __tablename__ = "maturity_indicators"

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"))
    criterion: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    value: Mapped[float] = mapped_column(Float)                       # 0–100, %
    target: Mapped[float] = mapped_column(Float)                      # 0–100, %
    period: Mapped[str] = mapped_column(String(50))
    entered_role: Mapped[str] = mapped_column(String(50))
    entered_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entered_at: Mapped[datetime] = mapped_column(DateTime)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
