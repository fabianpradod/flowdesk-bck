"""Exercise real HTTP + PostgreSQL using the synthetic load fixture on loopback only.

Usage: python scripts/verify_sprint10.py --base-url http://127.0.0.1:18811 \
  --fixture /tmp/fixture.json --dsn <local SQLAlchemy DSN> --out /tmp/verification.json
"""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
from sqlalchemy import create_engine, select, text

LOCAL = {'127.0.0.1', 'localhost', '::1'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--dsn', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if urlsplit(args.base_url).hostname not in LOCAL or urlsplit(args.dsn).hostname not in LOCAL:
        parser.error('Only loopback targets are allowed')
    if not urlsplit(args.dsn).path.lstrip('/').startswith('flowdesk_'):
        parser.error('Use a dedicated flowdesk_ database')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.tenancy.bootstrap import bootstrap_tenant_schema
    from app.tenancy.runtime import get_tenant_tables
    fixture = json.loads(args.fixture.read_text())
    checks = []
    def verify(condition, name):
        checks.append({'check': name, 'passed': bool(condition)})
        if not condition:
            args.out.write_text(json.dumps(checks, indent=2))
            raise AssertionError(name)
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        def login(company, role):
            user = next(user for user in company['users'] if user['role'] == role)
            response = client.post('/api/v1/auth/login', json={'email': user['email'], 'password': fixture['password']})
            response.raise_for_status()
            return {'Authorization': 'Bearer ' + response.json()['access_token']}
        a, b = fixture['companies'][:2]
        admin_a, admin_b = login(a, 'admin'), login(b, 'admin')
        manager_a, employee_a = login(a, 'manager'), login(a, 'employee')
        verify(client.get('/api/v1/audit/events').status_code == 401, 'audit requires authentication')
        verify(client.get('/api/v1/audit/events', headers=employee_a).status_code == 403, 'employee cannot read audit')
        verify(client.get('/api/v1/audit/events', headers=manager_a).status_code == 403, 'manager cannot read audit')
        before_b = client.get('/api/v1/audit/events?limit=100', headers=admin_b).json()
        movement = client.post('/api/v1/inventory/movements', headers=manager_a, json={
            'producto_id': a['product_ids'][0], 'tipo_movimiento': 'entrada_manual',
            'cantidad': 1, 'motivo': 'sprint10 disposable verification',
        })
        verify(movement.status_code in (200, 201), 'movement commits with audit')
        events = client.get('/api/v1/audit/events?action=movement.created&limit=100', headers=admin_a)
        verify(events.status_code == 200 and any(row['entity_id'] == movement.json()['id'] for row in events.json()['items']),
               'admin sees persisted movement event')
        verify(client.get('/api/v1/audit/events?limit=100', headers=admin_b).json() == before_b,
               'other company audit unchanged')
        page = client.get('/api/v1/inventory/movements/page?limit=2', headers=employee_a)
        verify(page.status_code == 200 and len(page.json()['items']) == 2, 'employee can read bounded movement page')
        cursor = page.json()['next_cursor']
        second = client.get('/api/v1/inventory/movements/page', headers=employee_a, params={'limit': 2, 'cursor': cursor})
        verify(second.status_code == 200 and not ({x['id'] for x in page.json()['items']} &
               {x['id'] for x in second.json()['items']}), 'next page has no duplicates')
        verify(client.get('/api/v1/inventory/movements/page', headers=admin_b,
                          params={'limit': 2, 'cursor': cursor}).status_code == 422, 'cross-tenant cursor rejected')
        users = client.get('/api/v1/users', headers=admin_a).json()
        target = next(user for user in users if user['email'] == next(u['email'] for u in a['users'] if u['role'] == 'employee'))
        updated = client.put('/api/v1/users/' + target['id'], headers=admin_a, json={'username': 'verified_' + uuid4().hex[:12]})
        verify(updated.status_code == 200, 'real user update commits')
        events = client.get('/api/v1/audit/events?action=user.updated', headers=admin_a).json()
        verify(any(row['entity_id'] == target['id'] for row in events['items']), 'user update has audit event')
    engine = create_engine(args.dsn)
    with engine.begin() as conn:
        schema = conn.execute(text('SELECT schema_name FROM "global".companies WHERE name=:name'), {'name': a['name']}).scalar_one()
        tables = get_tenant_tables(schema)
        count_before = conn.execute(text(f'SELECT count(*) FROM "{schema}".movimiento_inventario')).scalar_one()
        bootstrap_tenant_schema(conn, schema)
        bootstrap_tenant_schema(conn, schema)
        verify(conn.execute(text(f'SELECT count(*) FROM "{schema}".movimiento_inventario')).scalar_one() == count_before,
               'migration rerun preserves existing movements')
        indexes = conn.execute(text('SELECT indexname FROM pg_indexes WHERE schemaname=:schema'), {'schema': schema}).scalars().all()
        verify({'ix_movimiento_fecha_id', 'ix_movimiento_producto_fecha_id', 'ix_audit_event_occurred_id'} <= set(indexes),
               'migration creates audit and cursor indexes')
        plan = conn.execute(text(f'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT * FROM "{schema}".movimiento_inventario ORDER BY fecha DESC, id DESC LIMIT 101')).scalar_one()
        checks.append({'check': 'movement first-page execution plan', 'plan': plan})
        audit_table = tables['audit_event']
        row = conn.execute(select(audit_table).where(audit_table.c.entity_id == movement.json()['id'])).mappings().one()
        manager_email = next(user['email'] for user in a['users'] if user['role'] == 'manager')
        manager_id = conn.execute(text('SELECT id FROM "global".users WHERE email=:email'),
                                  {'email': manager_email}).scalar_one()
        verify(str(row['actor_id']) == str(manager_id), 'persisted actor matches authenticated manager')
    engine.dispose()
    args.out.write_text(json.dumps(checks, indent=2, default=str))
    print(f'{sum(item.get("passed", False) for item in checks)} checks passed; evidence: {args.out}')


if __name__ == '__main__':
    main()
