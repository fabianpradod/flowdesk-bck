"""Persistence, rollback, authorization and stable tenant-bound keyset pages."""
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Column, DateTime, MetaData, String, Table, Uuid, create_engine, insert, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.tenant.audit import AuditEvent
from app.services import audit, inventory
from app.utils.exceptions import AppError
from tests.security_helpers import client_for, make_company, make_user


@pytest.fixture
def store(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    metadata = MetaData()
    tables = {}
    with engine.begin() as conn:
        for schema in ('tenant_a', 'tenant_b'):
            conn.exec_driver_sql(f'ATTACH DATABASE ":memory:" AS {schema}')
    for schema in ('tenant_a', 'tenant_b'):
        tables[schema] = {
            'audit_event': AuditEvent.__table__.to_metadata(metadata, schema=schema),
            'movimiento_inventario': Table('movimiento_inventario', metadata,
                Column('id', Uuid, primary_key=True), Column('fecha', DateTime, nullable=False),
                Column('producto_id', Uuid, nullable=False), schema=schema),
            'critical_record': Table('critical_record', metadata,
                Column('id', Uuid, primary_key=True), Column('value', String), schema=schema),
        }
    metadata.create_all(engine)
    monkeypatch.setattr(audit, 'get_tenant_tables', lambda schema: tables[schema])
    monkeypatch.setattr(inventory, '_get_tenant_tables_for_user', lambda user: tables[user.company.schema_name])
    actors = {schema: SimpleNamespace(id=uuid4(), company_id=uuid4(),
              company=SimpleNamespace(is_active=True, schema_name=schema)) for schema in tables}
    yield engine, tables, actors
    engine.dispose()


def test_audit_and_change_commit_together_and_are_visible_after_reconnect(store):
    engine, tables, actors = store
    record_id = uuid4()
    with Session(engine) as db:
        db.execute(insert(tables['tenant_a']['critical_record']).values(id=record_id, value='changed'))
        audit.record_event(db, actors['tenant_a'], 'product.status_changed', 'product', record_id)
        db.commit()
    with Session(engine) as recovered:
        assert recovered.execute(select(tables['tenant_a']['critical_record'])).one().value == 'changed'
        page = audit.list_events(actors['tenant_a'], recovered)
        assert len(page['items']) == 1
        assert page['items'][0]['actor_id'] == actors['tenant_a'].id
        assert page['items'][0]['entity_id'] == record_id
        assert set(page['items'][0]) == {'id', 'occurred_at', 'actor_id', 'action', 'entity_type', 'entity_id'}
        assert audit.list_events(actors['tenant_b'], recovered)['items'] == []


def test_rollback_removes_both_mutation_and_audit(store):
    engine, tables, actors = store
    with Session(engine) as db:
        db.execute(insert(tables['tenant_a']['critical_record']).values(id=uuid4(), value='not committed'))
        audit.record_event(db, actors['tenant_a'], 'sale.created', 'sale', uuid4())
        db.rollback()
    with Session(engine) as recovered:
        assert recovered.execute(select(tables['tenant_a']['critical_record'])).all() == []
        assert audit.list_events(actors['tenant_a'], recovered)['items'] == []


def test_failure_to_write_audit_cannot_commit_business_change(store):
    engine, tables, actors = store
    from sqlalchemy import event
    def reject_audit(_conn, _cursor, statement, _parameters, _context, _many):
        if 'INSERT INTO tenant_a.audit_event' in statement:
            raise RuntimeError('audit storage unavailable')
    event.listen(engine, 'before_cursor_execute', reject_audit)
    with pytest.raises(RuntimeError), Session(engine) as db:
        db.execute(insert(tables['tenant_a']['critical_record']).values(id=uuid4(), value='must rollback'))
        audit.record_event(db, actors['tenant_a'], 'sale.created', 'sale', uuid4())
        db.commit()
    event.remove(engine, 'before_cursor_execute', reject_audit)
    with Session(engine) as recovered:
        assert recovered.execute(select(tables['tenant_a']['critical_record'])).all() == []


def test_audit_keyset_filters_and_cursor_are_tenant_bound(store):
    engine, tables, actors = store
    with Session(engine) as db:
        for n in range(5):
            db.execute(insert(tables['tenant_a']['audit_event']).values(
                id=UUID(int=n + 1), occurred_at=datetime(2026, 10, 20),
                actor_id=actors['tenant_a'].id, action='sale.created', entity_type='sale', entity_id=uuid4()))
        db.commit()
        page = audit.list_events(actors['tenant_a'], db, limit=2, action='sale.created')
        assert [row['id'].int for row in page['items']] == [5, 4]
        following = audit.list_events(actors['tenant_a'], db, limit=2, cursor=page['next_cursor'], action='sale.created')
        assert [row['id'].int for row in following['items']] == [3, 2]
        with pytest.raises(AppError, match='Invalid pagination cursor'):
            audit.list_events(actors['tenant_b'], db, cursor=page['next_cursor'], action='sale.created')
        with pytest.raises(AppError):
            audit.list_events(actors['tenant_a'], db, cursor=page['next_cursor'], action='user.updated')
        assert audit.list_events(actors['tenant_a'], db, actor_id=uuid4())['items'] == []


def test_movements_keyset_handles_equal_dates_and_new_insertions(store):
    engine, tables, actors = store
    product = uuid4()
    with Session(engine) as db:
        db.execute(insert(tables['tenant_a']['movimiento_inventario']), [
            {'id': UUID(int=n), 'fecha': datetime(2026, 10, 20), 'producto_id': product} for n in range(1, 6)])
        db.commit()
        page = inventory.list_inventory_movements_page(actors['tenant_a'], db, limit=2, product_id=product)
        assert [row['id'].int for row in page['items']] == [5, 4]
        db.execute(insert(tables['tenant_a']['movimiento_inventario']).values(
            id=UUID(int=6), fecha=datetime(2026, 10, 21), producto_id=product))
        db.commit()
        following = inventory.list_inventory_movements_page(actors['tenant_a'], db, limit=2,
                    product_id=product, cursor=page['next_cursor'])
        assert [row['id'].int for row in following['items']] == [3, 2]
        last = inventory.list_inventory_movements_page(actors['tenant_a'], db, limit=2,
                    product_id=product, cursor=following['next_cursor'])
        assert [row['id'].int for row in last['items']] == [1]
        assert last['next_cursor'] is None
        for actor, filter_product in [(actors['tenant_b'], product), (actors['tenant_a'], uuid4())]:
            with pytest.raises(AppError):
                inventory.list_inventory_movements_page(actor, db, limit=2, product_id=filter_product,
                                                        cursor=page['next_cursor'])


@pytest.mark.parametrize('cursor', ['not-base64', 'W10=', 'e30=', '////'])
def test_invalid_cursors_are_clean_422(store, cursor):
    engine, _, actors = store
    with Session(engine) as db, pytest.raises(AppError) as error:
        audit.list_events(actors['tenant_a'], db, cursor=cursor)
    assert error.value.status_code == 422


@pytest.mark.parametrize('role,status', [('employee', 403), ('manager', 403), ('admin', 200)])
def test_audit_endpoint_is_admin_only(role, status):
    session = client_for(make_user(role, make_company()))
    assert session.get('/api/v1/audit/events').status_code == status


@pytest.mark.parametrize('path', ['/api/v1/audit/events', '/api/v1/inventory/movements/page'])
@pytest.mark.parametrize('limit', [0, -1, 501])
def test_page_limits_are_bounded(path, limit):
    session = client_for(make_user('admin', make_company()))
    assert session.get(path, params={'limit': limit}).status_code == 422


@pytest.mark.parametrize('timestamp,event_id', [
    ('2026-10-20T00:00:00', 123), (123, '00000000-0000-0000-0000-000000000001'),
    ('2026-10-20T00:00:00+00:00', '00000000-0000-0000-0000-000000000001'),
])
def test_well_formed_base64_with_invalid_scalar_types_is_422(store, timestamp, event_id):
    import base64
    import json
    engine, _, actors = store
    context = ['audit', str(actors['tenant_a'].company_id), None, None]
    cursor = base64.urlsafe_b64encode(json.dumps([context, timestamp, event_id]).encode()).decode()
    with Session(engine) as db, pytest.raises(AppError) as error:
        audit.list_events(actors['tenant_a'], db, cursor=cursor)
    assert error.value.status_code == 422
