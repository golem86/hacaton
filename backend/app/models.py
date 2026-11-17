"""
Таблиці бази даних.

Кожен клас нижче = одна таблиця (як аркуш в Excel).
Кожне поле `Mapped[...] = mapped_column(...)` = одна колонка.

ГОЛОВНЕ ПРАВИЛО АНОНІМНОСТІ:
у таблицях з відповідями НЕМАЄ жодного поля, яке вказує на людину
(ні імені, ні ID користувача, ні точного часу відправки).
Токени доступу лежать в окремій таблиці і НЕ пов'язані з відповідями.
"""
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
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


class AccessToken(Base):
    """
    Одноразовий код для проходження анкети.
    Знаємо лише, ЧИ використано код, але НЕ знаємо, яка анкета ним заповнена:
    тут немає посилання на ResponseSet.
    """
    __tablename__ = "access_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"))
    token: Mapped[str] = mapped_column(String(64), unique=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


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
