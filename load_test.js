import http from 'k6/http';
import { check } from 'k6';

export let options = {
    vus: 10,
    duration: '30s',
};

export default function () {
    // We use the docker network name of the API since k6 will run in the same docker-compose network
    let res = http.get('http://api:8000/health');
    check(res, {
        'status is 200': (r) => r.status === 200,
    });
}
