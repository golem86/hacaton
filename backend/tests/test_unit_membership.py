"""Належність користувача до підрозділу (app/unit_membership.py): зберігання в instance_meta, перевірки."""
import pytest

from app import unit_membership
from app.database import SessionLocal
from app.models import InstanceMeta, Unit


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _unit_id(db) -> int:
    unit = db.query(Unit).order_by(Unit.id).first()
    assert unit is not None, "seed має створити хоча б один підрозділ"
    return unit.id


def test_set_get_and_clear_membership(db):
    unit_id = _unit_id(db)
    assert unit_membership.get_user_unit_id(db, 987001) is None
    unit_membership.set_user_unit_id(db, 987001, unit_id)
    db.flush()
    assert unit_membership.get_user_unit_id(db, 987001) == unit_id
    assert db.get(InstanceMeta, "unit_member:987001").value == str(unit_id)
    unit_membership.set_user_unit_id(db, 987001, None)
    db.flush()
    assert unit_membership.get_user_unit_id(db, 987001) is None
    assert db.get(InstanceMeta, "unit_member:987001") is None


def test_unknown_unit_and_bad_ids_are_rejected(db):
    with pytest.raises(ValueError):
        unit_membership.set_user_unit_id(db, 987002, 99999999)
    for bad in (0, -1, True, "5"):
        with pytest.raises(ValueError):
            unit_membership.membership_key(bad)


def test_corrupt_or_dangling_value_reads_as_no_unit(db):
    db.add(InstanceMeta(key="unit_member:987003", value="not-a-number"))
    db.add(InstanceMeta(key="unit_member:987004", value="99999999"))
    db.flush()
    assert unit_membership.get_user_unit_id(db, 987003) is None
    assert unit_membership.get_user_unit_id(db, 987004) is None
