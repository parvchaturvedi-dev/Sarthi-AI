// On-device Google connect — the phone holds the token and calls Gmail /
// Calendar APIs directly, so email/calendar work with NO PC or backend.
import AsyncStorage from "@react-native-async-storage/async-storage";

export const GOOGLE_ANDROID_CLIENT_ID =
  "824668514210-3l6cunkug2m85pugf5qpvisngut7te48.apps.googleusercontent.com";

export const GOOGLE_SCOPES = [
  "openid",
  "email",
  "profile",
  "https://www.googleapis.com/auth/gmail.send",
  "https://www.googleapis.com/auth/calendar",
  "https://www.googleapis.com/auth/drive.readonly",
  "https://www.googleapis.com/auth/contacts.readonly",
];

// ---- session storage ----
export async function saveGoogleSession(accessToken, email) {
  await AsyncStorage.multiSet([
    ["g_token", accessToken || ""],
    ["g_email", email || ""],
  ]);
}
export async function clearGoogleSession() {
  await AsyncStorage.multiRemove(["g_token", "g_email"]);
}
export async function googleEmail() {
  return (await AsyncStorage.getItem("g_email")) || null;
}
export async function googleConnected() {
  return !!(await AsyncStorage.getItem("g_token"));
}
async function token() {
  const t = await AsyncStorage.getItem("g_token");
  if (!t) throw new Error("Google not connected on this phone.");
  return t;
}

export async function fetchGoogleEmail(accessToken) {
  try {
    const r = await fetch("https://www.googleapis.com/oauth2/v2/userinfo", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const d = await r.json();
    return d.email || null;
  } catch {
    return null;
  }
}

// ---- base64url (UTF-8 safe, self-contained) ----
const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
function utf8Bytes(str) {
  const out = [];
  for (let i = 0; i < str.length; i++) {
    let c = str.charCodeAt(i);
    if (c < 0x80) out.push(c);
    else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f));
    else if (c >= 0xd800 && c < 0xdc00) {
      const c2 = str.charCodeAt(++i);
      const cp = 0x10000 + ((c & 0x3ff) << 10) + (c2 & 0x3ff);
      out.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 0x3f), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
    } else out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
  }
  return out;
}
function base64(bytes) {
  let out = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i], b1 = bytes[i + 1], b2 = bytes[i + 2];
    out += B64[b0 >> 2];
    out += B64[((b0 & 3) << 4) | ((b1 || 0) >> 4)];
    out += i + 1 < bytes.length ? B64[((b1 & 15) << 2) | ((b2 || 0) >> 6)] : "=";
    out += i + 2 < bytes.length ? B64[b2 & 63] : "=";
  }
  return out;
}
const b64url = (str) => base64(utf8Bytes(str)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

// ---- actions (called from ApprovalCard on Approve) ----
export async function gmailSend(to, subject, body) {
  const tok = await token();
  const mime = `To: ${to}\r\nSubject: ${subject}\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n${body}`;
  const res = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", {
    method: "POST",
    headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" },
    body: JSON.stringify({ raw: b64url(mime) }),
  });
  if (!res.ok) {
    if (res.status === 401) throw new Error("Google session expired — reconnect in Profile.");
    throw new Error("Gmail: " + (await res.text()).slice(0, 140));
  }
  return true;
}

function toISO(s) {
  const d = new Date(s);
  if (isNaN(d.getTime())) throw new Error(`Couldn't read the time "${s}". Use e.g. 2026-07-05 16:00.`);
  return d.toISOString();
}

export async function calendarAdd(title, start, end) {
  const tok = await token();
  const startISO = toISO(start);
  const endISO = end ? toISO(end) : new Date(new Date(startISO).getTime() + 3600000).toISOString();
  const res = await fetch("https://www.googleapis.com/calendar/v3/calendars/primary/events", {
    method: "POST",
    headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" },
    body: JSON.stringify({ summary: title, start: { dateTime: startISO }, end: { dateTime: endISO } }),
  });
  if (!res.ok) {
    if (res.status === 401) throw new Error("Google session expired — reconnect in Profile.");
    throw new Error("Calendar: " + (await res.text()).slice(0, 140));
  }
  return true;
}
