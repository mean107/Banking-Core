import http from 'k6/http';
import { check, sleep } from 'k6';
const base = __ENV.BASE_URL || 'http://localhost:8000';
export const options = {
  stages: [{duration:'1m',target:10},{duration:'3m',target:50},{duration:'1m',target:0}],
  thresholds: {http_req_failed:['rate<0.01'],http_req_duration:['p(95)<3000']},
};
export function setup() {
  const username = `load_${Date.now()}`;
  const params = {headers:{'Content-Type':'application/json'}};
  const body = JSON.stringify({username,password:'LoadPass123!'});
  const registered = http.post(`${base}/api/auth/register`,body,params);
  if (registered.status !== 200) throw new Error(`Registration failed: ${registered.status}`);
  const login = http.post(`${base}/api/auth/login`,body,params);
  if (login.status !== 200) throw new Error(`Login failed: ${login.status}`);
  return {session:login.json('session')};
}
export default function(data) {
  const r=http.get(`${base}/api/account/me`,{headers:{'X-Session':data.session}});
  check(r,{'account returned':r=>r.status===200});
  sleep(0.1);
}
