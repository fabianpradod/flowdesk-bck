// Load scenario for the endpoints that hit the database.
//
// Each virtual user logs in once (setup) as a manager or admin of one of the seeded
// companies and then calls a weighted mix of endpoints without pauses, so the number
// of virtual users is the number of requests in flight. Requests are tagged with the
// endpoint (name) and the load stage (stage) for tests/load/summarize_k6.py.
//
//   k6 run -e FIXTURE=/abs/path/fixture.json -e BASE_URL=http://127.0.0.1:8800 \
//       --out csv=run.csv tests/load/flowdesk_load.js
import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8800';
const fixture = JSON.parse(open(__ENV.FIXTURE));

// Holds of 30 s at 25, 50 and 100 users, with ramps in between. The same levels as
// the earlier stress_test.js, held longer so each level has stable percentiles.
const STAGES = [
    { duration: '15s', target: 25 },
    { duration: '30s', target: 25 },
    { duration: '15s', target: 50 },
    { duration: '30s', target: 50 },
    { duration: '15s', target: 100 },
    { duration: '30s', target: 100 },
    { duration: '10s', target: 0 },
];

export const options = {
    stages: STAGES,
    discardResponseBodies: true,
    thresholds: {
        http_req_duration: ['p(95)<200'],
        http_req_failed: ['rate<0.01'],
    },
};

const pick = (items) => items[Math.floor(Math.random() * items.length)];

const ENDPOINTS = [
    { name: 'products', weight: 10, path: () => '/api/v1/inventory/products' },
    { name: 'suppliers', weight: 5, path: () => '/api/v1/inventory/suppliers' },
    { name: 'supplier_products', weight: 3, path: (c) => `/api/v1/inventory/supplier-products?product_id=${pick(c.product_ids)}` },
    { name: 'movements_by_product', weight: 8, path: (c) => `/api/v1/inventory/movements?product_id=${pick(c.product_ids)}` },
    { name: 'movements_all', weight: 2, path: () => '/api/v1/inventory/movements' },
    { name: 'alerts', weight: 5, path: () => '/api/v1/inventory/alerts' },
    { name: 'history', weight: 8, path: () => '/api/v1/inventory/history?limit=20' },
    { name: 'inventory_metrics', weight: 6, path: () => '/api/v1/inventory/metrics?period=30d' },
    { name: 'analytics_monthly', weight: 5, path: () => '/api/v1/inventory/analytics/monthly?period=6m' },
    { name: 'analytics_trend', weight: 5, path: () => '/api/v1/inventory/analytics/trend?period=30d&window=day' },
    { name: 'analytics_products', weight: 5, path: () => '/api/v1/inventory/analytics/products?period=30d' },
    { name: 'clients', weight: 7, path: () => '/api/v1/commercial/clients' },
    { name: 'client_purchases', weight: 5, path: (c) => `/api/v1/commercial/clients/${pick(c.client_ids)}/purchases?limit=20` },
    { name: 'sale_detail', weight: 5, path: (c) => `/api/v1/commercial/sales/${pick(c.sale_ids)}` },
    { name: 'sales_metrics', weight: 5, path: () => '/api/v1/analytics/sales/metrics?period=30d' },
    { name: 'sales_trend', weight: 4, path: () => '/api/v1/analytics/sales/trend?period=30d&window=day' },
    { name: 'top_products', weight: 3, path: () => '/api/v1/analytics/sales/top-products?period=30d' },
    { name: 'tasks', weight: 4, path: () => '/api/v1/tasks' },
    { name: 'movement_create', weight: 3, method: 'POST' },
    // Control: no database and no authentication.
    { name: 'health', weight: 2, path: () => '/health' },
];
const TOTAL_WEIGHT = ENDPOINTS.reduce((sum, endpoint) => sum + endpoint.weight, 0);

function chooseEndpoint() {
    let roll = Math.random() * TOTAL_WEIGHT;
    for (const endpoint of ENDPOINTS) {
        roll -= endpoint.weight;
        if (roll < 0) return endpoint;
    }
    return ENDPOINTS[ENDPOINTS.length - 1];
}

// Seconds since the scenario started mapped to the level being held, or "ramp".
function currentStage() {
    let elapsed = (Date.now() - exec.scenario.startTime) / 1000;
    for (let i = 0; i < STAGES.length; i++) {
        const seconds = parseInt(STAGES[i].duration, 10);
        if (elapsed < seconds) {
            const holding = i > 0 && STAGES[i - 1].target === STAGES[i].target;
            return holding ? String(STAGES[i].target) : 'ramp';
        }
        elapsed -= seconds;
    }
    return 'ramp';
}

export function setup() {
    const sessions = [];
    fixture.companies.forEach((company) => {
        company.users
            .filter((user) => user.role === 'manager' || user.role === 'admin')
            .forEach((user) => {
                const res = http.post(
                    `${BASE_URL}/api/v1/auth/login`,
                    JSON.stringify({ email: user.email, password: fixture.password }),
                    { headers: { 'Content-Type': 'application/json' }, responseType: 'text', tags: { name: 'login', stage: 'setup' } },
                );
                if (res.status !== 200) {
                    exec.test.abort(`login failed for ${user.email}: ${res.status}`);
                }
                sessions.push({ token: res.json('access_token'), company });
            });
    });
    return { sessions };
}

export default function (data) {
    const session = data.sessions[exec.vu.idInTest % data.sessions.length];
    const endpoint = chooseEndpoint();
    const params = {
        headers: { Authorization: `Bearer ${session.token}`, 'Content-Type': 'application/json' },
        tags: { name: endpoint.name, stage: currentStage() },
    };

    let res;
    if (endpoint.method === 'POST') {
        const body = JSON.stringify({
            producto_id: pick(session.company.product_ids),
            tipo_movimiento: 'entrada_manual',
            cantidad: 1,
            motivo: 'k6',
        });
        res = http.post(`${BASE_URL}/api/v1/inventory/movements`, body, params);
    } else {
        res = http.get(`${BASE_URL}${endpoint.path(session.company)}`, params);
    }
    check(res, { 'status is 2xx': (r) => r.status >= 200 && r.status < 300 });
}
