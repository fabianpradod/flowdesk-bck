import http from 'k6/http';
import { check } from 'k6';

export let options = {
    stages: [
        { duration: '10s', target: 25 }, // Ramp-up to 25 VUs
        { duration: '10s', target: 25 }, // Hold at 25 VUs
        { duration: '10s', target: 50 }, // Ramp-up to 50 VUs
        { duration: '10s', target: 50 }, // Hold at 50 VUs
        { duration: '10s', target: 100 }, // Ramp-up to 100 VUs
        { duration: '10s', target: 100 }, // Hold at 100 VUs
        { duration: '10s', target: 0 },   // Ramp-down to 0 VUs
    ],
};

export default function () {
    let res = http.get('http://api:8000/health');
    check(res, {
        'status is 200': (r) => r.status === 200,
    });
}
