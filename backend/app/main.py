from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Component, Cycle, ResponseSet

# Створює таблиці, якщо їх ще немає (дані при цьому не стираються)
Base.metadata.create_all(engine)

app = FastAPI(title="Integrity Dashboard API")


@app.get("/")
def hello():
    return {"message": "Integrity Dashboard працює"}


@app.get("/cycles")
def list_cycles(db: Session = Depends(get_db)):
    """Усі цикли оцінювання (для вибору циклу і графіка динаміки)."""
    cycles = db.query(Cycle).order_by(Cycle.start_date).all()
    return [{"id": c.id, "name": c.name, "start_date": c.start_date,
             "status": c.status, "min_group_size": c.min_group_size} for c in cycles]


@app.get("/components")
def list_components(db: Session = Depends(get_db)):
    """Компоненти з вагами і питаннями — щоб методика була прозорою."""
    return [{"code": c.code, "name": c.name, "weight": c.weight,
             "questions": [{"id": q.id, "text": q.text, "scale": [q.scale_min, q.scale_max]}
                           for q in c.questions]}
            for c in db.query(Component).order_by(Component.code).all()]


@app.get("/cycles/{cycle_id}/participation")
def participation(cycle_id: int, db: Session = Depends(get_db)):
    """
    Скільки анкет заповнила кожна категорія.
    Групи, менші за min_group_size, приховуємо — це захист анонімності.
    """
    cycle = db.get(Cycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="Цикл не знайдено")

    rows = (db.query(ResponseSet.respondent_category, func.count(ResponseSet.id))
            .filter(ResponseSet.cycle_id == cycle_id)
            .group_by(ResponseSet.respondent_category).all())

    return [{"category": category,
             "responses": count if count >= cycle.min_group_size else None,
             "hidden": count < cycle.min_group_size}
            for category, count in rows]
