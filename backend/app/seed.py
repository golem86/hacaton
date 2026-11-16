"""
Заповнює базу ВИГАДАНИМИ (синтетичними) даними для демонстрації.
Жодних реальних людей чи службової інформації — так вимагає умова хакатону.

Запуск (з папки backend, у пісочниці .venv):
    python -m app.seed            # створює базу, ЛИШЕ якщо вона порожня
    python -m app.seed --reset    # стирає ВСЕ і створює демо-дані заново

Без прапорця --reset скрипт відмовиться чіпати базу, у якій уже є дані.
"""
import argparse
import random
import secrets
import sys
from datetime import date

from sqlalchemy import inspect, select

from .database import Base, SessionLocal, engine
from .models import (AccessToken, Answer, Component, Cycle, ObjectiveIndicator,
                     Question, Recommendation, ResponseSet)

random.seed(2026)  # однакове «випадкове» щоразу, щоб у всієї команди були ті самі дані

# Орієнтовні компоненти. ПОТІМ звірити з додатками Б і В Рекомендацій!
COMPONENTS = [
    ("C1", "Лідерство й тон керівництва", 0.15),
    ("C2", "Антикорупційна політика і процедури", 0.15),
    ("C3", "Управління корупційними ризиками", 0.15),
    ("C4", "Доброчесність освітнього процесу", 0.20),
    ("C5", "Навчання і комунікація", 0.10),
    ("C6", "Повідомлення про порушення", 0.15),
    ("C7", "Моніторинг і контроль", 0.10),
]

# По два демо-питання на компонент (справжні беремо з додатка В)
QUESTIONS = {
    "C1": ["Керівництво власним прикладом демонструє доброчесну поведінку",
           "Керівництво відкрито обговорює питання доброчесності з персоналом"],
    "C2": ["Мені зрозумілі антикорупційні правила закладу",
           "Процедури запобігання конфлікту інтересів застосовуються на практиці"],
    "C3": ["Корупційні ризики в моєму підрозділі визначені та відомі",
           "Заходи щодо зменшення ризиків реально виконуються"],
    "C4": ["Оцінювання знань у закладі є чесним і прозорим",
           "Неможливо отримати кращу оцінку завдяки знайомствам чи подарункам"],
    "C5": ["Я проходив навчання з питань доброчесності за останній рік",
           "Інформація про доброчесність доводиться зрозуміло й регулярно"],
    "C6": ["Я знаю, як повідомити про порушення анонімно",
           "Я впевнений, що повідомлення про порушення не матиме для мене негативних наслідків"],
    "C7": ["Виконання антикорупційних заходів регулярно перевіряється",
           "Результати перевірок доводяться до персоналу"],
}

# Категорії респондентів і скільки анкет кожна заповнює.
# «staff» навмисно 4 — менше за поріг 5, щоб показати приховування малих груп.
CATEGORIES = {"mgmt": 6, "npp": 48, "cadets": 210, "staff": 4}

# «Справжній» середній рівень кожного компонента (0–100) для кожної категорії.
# Керівництво оцінює себе вище — так ми демонструємо розбіжності.
BASE_LEVEL = {  # C1..C7
    "mgmt":   [82, 78, 70, 75, 80, 72, 68],
    "npp":    [64, 70, 52, 58, 72, 45, 60],
    "cadets": [55, 66, 48, 44, 70, 38, 57],
    "staff":  [60, 68, 50, 56, 71, 42, 59],
}
# Об'єктивні показники останнього циклу (0–100) по компонентах C1..C7
OBJECTIVE = [58, 75, 46, 41, 81, 35, 63]
OBJECTIVE_NAMES = [
    "Виконання заходів, закріплених за керівництвом, %",
    "Актуальність антикорупційної програми, %",
    "Ризики з реєстру, щодо яких виконано заходи, %",
    "Скарги на оцінювання, розглянуті вчасно, %",
    "Персонал, що пройшов навчання, %",
    "Повідомлення, на які відреаговано у строк, %",
    "Виконання плану заходів, %",
]
UNITS = ["Факультет 1", "Факультет 2", "Кафедра загальних дисциплін"]

# Три цикли: рівень потроху росте → на дашборді видно позитивну динаміку
CYCLES = [("2025-II", date(2025, 10, 1), -6), ("2026-I", date(2026, 4, 1), -3), ("2026-II", date(2026, 11, 1), 0)]


def level_to_answer(level: float) -> int:
    """Перетворює рівень 0–100 у відповідь за шкалою 1–5 з невеликим випадковим «шумом»."""
    noisy = level + random.gauss(0, 12)
    return max(1, min(5, round(1 + noisy / 25)))


def database_has_data() -> bool:
    """Чи є хоч один рядок у БУДЬ-ЯКІЙ таблиці бази (не лише в анкетах)."""
    existing = set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name in existing and conn.execute(select(table).limit(1)).first() is not None:
                return True
    return False


def run(reset: bool = False) -> bool:
    """
    Заповнює базу демо-даними. Повертає True, якщо дані створено.
    Без reset=True НЕ чіпає базу, у якій уже є дані — захист від випадкового стирання.
    """
    random.seed(2026)  # щоразу однакові дані

    if database_has_data() and not reset:
        print("У базі вже є дані — нічого не змінюю.\n"
              "Щоб стерти все і створити демо-дані заново: python -m app.seed --reset")
        return False

    # 1. Стираємо таблиці ЛИШЕ за явного --reset; інакше база гарантовано порожня
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    db = SessionLocal()

    # 2. Компоненти і питання
    components = {}
    for code, name, weight in COMPONENTS:
        comp = Component(code=code, name=name, weight=weight)
        db.add(comp)
        components[code] = comp
        for text in QUESTIONS[code]:
            db.add(Question(component=comp, text=text))
    db.flush()  # flush = «відправ у базу зараз», щоб отримати id нових рядків

    questions = db.query(Question).all()

    # 3. Цикли, анкети, токени, факти
    for cycle_name, start, shift in CYCLES:
        cycle = Cycle(name=cycle_name, start_date=start,
                      status="open" if shift == 0 else "closed")
        db.add(cycle)
        db.flush()

        for category, count in CATEGORIES.items():
            for _ in range(count):
                rs = ResponseSet(cycle_id=cycle.id, respondent_category=category,
                                 unit=random.choice(UNITS))
                db.add(rs)
                for q in questions:
                    comp_index = int(q.component.code[1:]) - 1
                    level = BASE_LEVEL[category][comp_index] + shift
                    rs.answers.append(Answer(question_id=q.id, value=level_to_answer(level)))
                # токен лише позначаємо «використаним» — без зв'язку з анкетою
                db.add(AccessToken(cycle_id=cycle.id, token=secrets.token_hex(16), used=True))

        # кілька невикористаних токенів = людей, які ще не пройшли опитування
        for _ in range(20):
            db.add(AccessToken(cycle_id=cycle.id, token=secrets.token_hex(16), used=False))

        for i, (code, comp) in enumerate(components.items()):
            db.add(ObjectiveIndicator(
                cycle_id=cycle.id, component_id=comp.id, name=OBJECTIVE_NAMES[i],
                value=OBJECTIVE[i] + shift, entered_by_role="Відповідальний за дані",
                confirmed_by_role="Уповноважений з антикорупції", confirmed=True))

    # 4. Рекомендації попереднього циклу (для демонстрації трекера)
    prev = db.query(Cycle).filter_by(name="2026-I").one()
    demo_recs = [
        ("C6", "Запровадити анонімний канал повідомлень про порушення", "done", "Уповноважений з антикорупції", date(2026, 5, 30)),
        ("C5", "Провести навчання з доброчесності для курсантів 1 курсу", "done", "Навчальний відділ", date(2026, 6, 15)),
        ("C3", "Оновити реєстр корупційних ризиків", "done", "Робоча група", date(2026, 7, 1)),
        ("C4", "Запровадити прозорі критерії оцінювання знань", "overdue", "Заступник з навчальної роботи", date(2026, 9, 1)),
        ("C7", "Щоквартально публікувати результати моніторингу", "in_progress", "Уповноважений з антикорупції", date(2026, 12, 20)),
    ]
    for code, text, status, owner, due in demo_recs:
        db.add(Recommendation(cycle_id=prev.id, component_id=components[code].id, text=text,
                              basis="Бал компонента нижче порогу в циклі 2026-I",
                              status=status, owner_role=owner, due_date=due))

    db.commit()  # commit = «зберегти все остаточно»
    print("Готово! Анкет:", db.query(ResponseSet).count(),
          "| відповідей:", db.query(Answer).count(),
          "| циклів:", db.query(Cycle).count())
    db.close()
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Заповнити базу синтетичними демо-даними")
    parser.add_argument("--reset", action="store_true",
                        help="стерти ВСІ наявні дані і створити демо-дані заново")
    args = parser.parse_args()
    sys.exit(0 if run(reset=args.reset) or not args.reset else 1)
