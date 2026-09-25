const API = "";
export function setSession(session) { localStorage.setItem("session", session); }
export function getSession() { return localStorage.getItem("session"); }
export function clearSession() { localStorage.removeItem("session"); }

async function req(path, { method = "GET", body, headers = {} } = {}) {
  const session = getSession();
  const res = await fetch(API + path, {
    method,
    headers: { "Content-Type": "application/json", ...(session ? {"X-Session":session} : {}), ...headers },
    body: body ? JSON.stringify(body) : undefined
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(typeof data.detail === "string" ? data.detail : "Request failed");
    error.status = res.status;
    throw error;
  }
  return data;
}

async function transfer(to_username, amount) {
  const body = {to_username, amount:Number(amount)};
  const fingerprint = JSON.stringify([sessionStorage.getItem("banking-user") || getSession(),body]);
  const saved = JSON.parse(sessionStorage.getItem("pending-transfer") || "null");
  if (saved && saved.fingerprint !== fingerprint) {
    throw new Error("A previous transfer has an unknown outcome. Retry its original recipient and amount before making another transfer.");
  }
  const pending = saved || {fingerprint,key:crypto.randomUUID()};
  sessionStorage.setItem("pending-transfer",JSON.stringify(pending));
  try {
    const result = await req("/api/transfer/transfer",{method:"POST",body,headers:{"Idempotency-Key":pending.key}});
    sessionStorage.removeItem("pending-transfer");
    return result;
  } catch (error) {
    if (error.status >= 400 && error.status < 500) sessionStorage.removeItem("pending-transfer");
    throw error;
  }
}

export const api = {
  register:(username,password)=>req("/api/auth/register",{method:"POST",body:{username,password}}),
  login:async (username,password)=>{
    const result=await req("/api/auth/login",{method:"POST",body:{username,password}});
    sessionStorage.setItem("banking-user",result.username);
    return result;
  },
  logout:()=>req("/api/auth/logout",{method:"POST"}),
  me:()=>req("/api/account/me"),
  transfer,
  notifications:()=>req("/api/notifications/notifications")
};
