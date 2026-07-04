// Talks to the FastAPI backend (backend/ on port 8760).
export const API = process.env.NEXT_PUBLIC_API || "http://127.0.0.1:8760";
export const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

export function getToken() {
  return typeof window !== "undefined" ? localStorage.getItem("nova_token") : null;
}
export function setSession(token, user) {
  localStorage.setItem("nova_token", token);
  localStorage.setItem("nova_user", JSON.stringify(user || {}));
}
export function getUser() {
  try { return JSON.parse(localStorage.getItem("nova_user") || "null"); } catch { return null; }
}
export function logout() {
  localStorage.removeItem("nova_token");
  localStorage.removeItem("nova_user");
}

export async function api(path, opts = {}) {
  const t = getToken();
  const res = await fetch(API + path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(t ? { Authorization: "Bearer " + t } : {}),
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}
