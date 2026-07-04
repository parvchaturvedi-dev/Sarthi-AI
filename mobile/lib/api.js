// Sarthi mobile <-> FastAPI backend bridge.
// The phone must be on the SAME Wi-Fi as the PC running the backend.
import AsyncStorage from "@react-native-async-storage/async-storage";

// Default = your PC's LAN IP. Editable in Profile > Server.
export const DEFAULT_BASE = "http://192.168.31.228:8760";

let _base = DEFAULT_BASE;
let _token = null;
let _user = null;

export async function loadBase() {
  const b = await AsyncStorage.getItem("sarthi_base");
  if (b) _base = b;
  return _base;
}
export function getBase() {
  return _base;
}
export async function setBase(url) {
  _base = (url || "").trim().replace(/\/+$/, "") || DEFAULT_BASE;
  await AsyncStorage.setItem("sarthi_base", _base);
  return _base;
}

async function req(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && _token) headers.Authorization = `Bearer ${_token}`;
  const res = await fetch(_base + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`);
  return data;
}

async function _saveAuth(d) {
  _token = d.token;
  _user = d.user;
  await AsyncStorage.multiSet([
    ["sarthi_token", _token || ""],
    ["sarthi_user", JSON.stringify(_user || null)],
  ]);
  return _user;
}

// Restore a saved session on app start.
export async function loadAuth() {
  const t = await AsyncStorage.getItem("sarthi_token");
  if (t) _token = t;
  try { _user = JSON.parse((await AsyncStorage.getItem("sarthi_user")) || "null"); } catch {}
  return _token;
}

export async function isLoggedIn() {
  if (!_token) await loadAuth();
  return !!_token;
}

// Silent guest session so the assistant knows a name and approvals can execute.
export async function ensureAuth() {
  if (_token) return _user;
  try {
    await _saveAuth(await req("/api/auth/guest", { method: "POST", auth: false }));
  } catch {
    // ignore — anonymous chat still works
  }
  return _user;
}

export async function login(email, password) {
  return _saveAuth(await req("/api/auth/login", { method: "POST", auth: false, body: { email, password } }));
}
export async function register(name, email, password) {
  return _saveAuth(await req("/api/auth/register", { method: "POST", auth: false, body: { name, email, password } }));
}
// idToken from the Google Sign-In button -> backend verifies it and issues a JWT.
export async function googleAuth(idToken) {
  return _saveAuth(await req("/api/auth/google", { method: "POST", auth: false, body: { credential: idToken } }));
}
export async function guestLogin() {
  return _saveAuth(await req("/api/auth/guest", { method: "POST", auth: false }));
}
export async function logout() {
  _token = null;
  _user = null;
  await AsyncStorage.multiRemove(["sarthi_token", "sarthi_user"]);
}
export function getUser() {
  return _user;
}
export function accountEmail() {
  return _user?.email || null;
}

export async function ping() {
  await req("/api/settings", { auth: false });
  return true;
}

// Fast reachability probe for the online/offline router (short timeout).
export async function isOnline(timeoutMs = 3500) {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    const res = await fetch(_base + "/api/settings", { signal: ctrl.signal });
    clearTimeout(t);
    return res.ok;
  } catch {
    return false;
  }
}

// speak=false keeps the PC silent (mobile plays the audio itself); pass true
// only in "Control your PC" mode so the laptop also speaks.
export async function chat(text, sessionId, speak = false) {
  return req("/api/chat", { method: "POST", body: { text, session_id: sessionId ?? null, speak } });
}

export async function getSessions() {
  return req("/api/sessions", { auth: false });
}

export async function getSession(id) {
  return req(`/api/session/${id}`, { auth: false });
}

// Tell the PC to stop speaking the current response (best-effort).
export async function stopSpeaking() {
  try { await req("/api/stop", { method: "POST", auth: false }); } catch {}
}

export async function executeAction(action) {
  return req("/api/action/execute", { method: "POST", body: action });
}

export async function devicePlan(text) {
  return req("/api/device/plan", { method: "POST", body: { text } });
}

export async function deviceOperate(goal, screen, history) {
  return req("/api/device/operate", { method: "POST", body: { goal, screen, history } });
}

// Upload a recorded audio clip; backend transcribes with whisper. Multipart, so
// we don't go through req() (which forces JSON).
export async function transcribe(uri) {
  const form = new FormData();
  form.append("file", { uri, name: "voice.m4a", type: "audio/m4a" });
  const res = await fetch(_base + "/api/transcribe", { method: "POST", body: form });
  const d = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(d?.error || `HTTP ${res.status}`);
  return d.text || "";
}

export async function getSettings() {
  return req("/api/settings", { auth: false });
}

export async function setMode(mode) {
  return req("/api/settings", { method: "POST", body: { mode } });
}

// --- PC pairing: find your Sarthi PC on the Wi-Fi and connect (no manual IP).
export async function whoami(base, timeoutMs = 800) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(base + "/api/whoami", { signal: ctrl.signal });
    clearTimeout(t);
    if (!r.ok) return null;
    const d = await r.json();
    return d && d.app === "sarthi" ? { base, ...d } : null;
  } catch {
    clearTimeout(t);
    return null;
  }
}

function _subnet(base) {
  const m = (base || "").match(/(\d+\.\d+\.\d+)\.\d+/);
  return m ? m[1] : null;
}

// Scan the LAN (subnet from the current base) for PCs running Sarthi. Returns a
// list of {base, name, owner, mode}. Handles several PCs (multi-device).
export async function discoverPCs(onProgress) {
  const sub = _subnet(_base) || "192.168.1";
  const port = (_base.match(/:(\d+)/) || [])[1] || "8760";
  const hosts = [];
  for (let i = 1; i <= 254; i++) hosts.push(`http://${sub}.${i}:${port}`);
  const found = [];
  const BATCH = 24;
  for (let i = 0; i < hosts.length; i += BATCH) {
    const res = await Promise.all(hosts.slice(i, i + BATCH).map((h) => whoami(h)));
    res.forEach((r) => r && found.push(r));
    if (onProgress) onProgress(Math.min(1, (i + BATCH) / hosts.length), found.slice());
  }
  return found;
}

// Claim a PC for this account (the "Connect" handshake) and switch to it.
export async function pairPC(base, email, deviceName) {
  await setBase(base);
  const r = await fetch(base + "/api/pair", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, device_name: deviceName || null }),
  });
  return r.ok ? r.json() : null;
}

// --- PC brain (AI model) — choose local model or a cloud API key, from the phone.
export async function getBrainModels() {
  return req("/api/brain/models", { auth: false });
}

// body: { mode:'local'|'api', provider, model, api_key }
export async function setBrain(body) {
  return req("/api/brain", { method: "POST", body });
}
