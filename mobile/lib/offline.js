// On-device brain — runs Qwen2.5-1.5B (GGUF) via llama.rn, fully offline.
// Also holds a zero-model rules planner so "Control Your Device" works offline
// even before the model is downloaded.
//
// Only usable in a custom dev build (llama.rn is native) — NOT Expo Go.
import { initLlama, releaseAllLlama } from "llama.rn";
import * as FS from "expo-file-system/legacy";

export const MODEL = {
  name: "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
  url: "https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
  sizeMB: 940,
};
const PATH = FS.documentDirectory + MODEL.name;

let ctx = null;
let loading = false;

// ---------- model file management ----------
export async function modelInfo() {
  const info = await FS.getInfoAsync(PATH);
  return { exists: !!info.exists, size: info.size || 0, path: PATH, ready: !!ctx };
}

export async function downloadModel(onProgress) {
  const dl = FS.createDownloadResumable(MODEL.url, PATH, {}, (p) => {
    const frac = p.totalBytesExpectedToWrite > 0 ? p.totalBytesWritten / p.totalBytesExpectedToWrite : 0;
    onProgress?.(frac, p.totalBytesWritten, p.totalBytesExpectedToWrite);
  });
  const res = await dl.downloadAsync();
  return res?.uri;
}

export async function deleteModel() {
  await releaseBrain();
  try { await FS.deleteAsync(PATH, { idempotent: true }); } catch {}
}

// ---------- inference ----------
export function isReady() { return !!ctx; }

export async function initBrain() {
  if (ctx) return ctx;
  if (loading) throw new Error("Model is still loading…");
  const info = await FS.getInfoAsync(PATH);
  if (!info.exists) throw new Error("Offline model not downloaded yet (Profile → Offline brain).");
  loading = true;
  try {
    ctx = await initLlama({
      model: PATH.replace("file://", ""),
      n_ctx: 2048,
      n_gpu_layers: 0, // CPU on Android
      n_threads: 4,
    });
    return ctx;
  } finally {
    loading = false;
  }
}

export async function releaseBrain() {
  ctx = null;
  try { await releaseAllLlama(); } catch {}
}

const chatml = (sys, user) =>
  `<|im_start|>system\n${sys}<|im_end|>\n<|im_start|>user\n${user}<|im_end|>\n<|im_start|>assistant\n`;

export async function offlineChat(userText, onToken) {
  const c = await initBrain();
  const sys = "You are Sarthi, a friendly, helpful personal assistant. Answer clearly and concisely.";
  const out = await c.completion(
    { prompt: chatml(sys, userText), n_predict: 256, temperature: 0.6, stop: ["<|im_end|>", "<|endoftext|>"] },
    (d) => { if (d?.token) onToken?.(d.token); }
  );
  return (out?.text || "").trim();
}

// ---------- live web search (works whenever the PHONE has internet, even if
// the PC backend is off) ----------
const LANGSEARCH_KEY = "sk-5656fe8d24b94edb8e3a70b80ab52e85"; // personal key

export function isSearchQuery(t) {
  return /\b(news|khabar|samachar|latest|today|aaj|weather|mausam|score|price|rate|stock|kaun|who won|update|headlines)\b/i.test(t || "");
}

export async function offlineSearch(query) {
  try {
    const res = await fetch("https://api.langsearch.com/v1/web-search", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + LANGSEARCH_KEY },
      body: JSON.stringify({ query, freshness: "oneWeek", summary: true, count: 5 }),
    });
    const d = await res.json();
    const items = d?.data?.webPages?.value || [];
    if (!items.length) return null;
    const top = items.slice(0, 4).map((w, i) => `${i + 1}. ${w.name}\n${(w.summary || w.snippet || "").slice(0, 180)}`).join("\n\n");
    return `Here's the latest I found:\n\n${top}`;
  } catch {
    return null;
  }
}

// ---------- device planning (offline) ----------
const KNOWN_APPS = [
  "whatsapp", "youtube", "instagram", "maps", "chrome", "google", "camera",
  "settings", "phone", "gmail", "spotify", "photos", "files", "playstore",
  "facebook", "telegram", "twitter", "linkedin", "phonepe", "paytm", "gpay",
];

const DEVICE_SYS =
  "You convert a phone command into ONE action as strict JSON: " +
  '{"reply":"<one short sentence>","action":<obj or null>}. Kinds: ' +
  '{"kind":"open_app","app":"' + KNOWN_APPS.join("|") + '"} | ' +
  '{"kind":"call","number":"<digits>"} | {"kind":"sms","number":"","body":""} | ' +
  '{"kind":"whatsapp","number":"","message":""} | {"kind":"maps","query":""} | ' +
  '{"kind":"web","query":""} | {"kind":"youtube","query":""} | ' +
  '{"kind":"email","to":"","subject":"","body":""}. ' +
  "If a needed detail is missing, set action null and ask for it. Never invent numbers/emails. JSON only.";

// Instant, no-model regex planner (mirrors backend nova/core/device.py _rules).
export function rulesPlan(text) {
  const t = (text || "").toLowerCase().trim();
  if (!t) return { reply: "What should I do on your phone?", action: null };

  let m = t.match(/\b(?:open|launch|khol|start)\s+([a-z ]+)/);
  if (m) {
    let name = m[1].trim().split(/\s+/)[0];
    name = { insta: "instagram", wa: "whatsapp", yt: "youtube", map: "maps", browser: "chrome" }[name] || name;
    if (KNOWN_APPS.includes(name)) return { reply: `Opening ${name}.`, action: { kind: "open_app", app: name } };
  }
  m = t.match(/\b(?:navigate to|directions to|maps? (?:to|for)|take me to)\s+(.+)/);
  if (m) return { reply: `Opening maps for ${m[1].trim()}.`, action: { kind: "maps", query: m[1].trim() } };

  m = t.match(/\b(?:play|youtube|watch)\s+(.+)/);
  if (m) return { reply: `Searching YouTube for ${m[1].trim()}.`, action: { kind: "youtube", query: m[1].trim() } };

  m = t.match(/\bcall\s+(.+)/);
  if (m) {
    const num = m[1].replace(/[^\d+]/g, "");
    if (num.length >= 7) return { reply: `Calling ${num}.`, action: { kind: "call", number: num } };
    return { reply: `What's ${m[1].trim()}'s number? I don't have it saved.`, action: null };
  }
  if (/\bwhatsapp\b/.test(t)) return { reply: "Who should I message on WhatsApp, and what should it say?", action: null };

  m = t.match(/\b(?:search|google|find|look up)\s+(?:for\s+)?(.+)/);
  if (m) return { reply: `Searching the web for ${m[1].trim()}.`, action: { kind: "web", query: m[1].trim() } };

  return { reply: "I can open apps, call, WhatsApp, navigate, or search — try 'open YouTube' or 'navigate to the airport'.", action: null };
}

const _OP_SYS =
  'You operate an Android app step by step. Given GOAL and on-screen elements, return the next action as JSON: ' +
  '{"say":"<short status>","action":"tap|type|scroll|back|done|ask|confirm","text":"<tap label or text to type>","label":"<for confirm/ask>"}. ' +
  "When only an irreversible SEND/PAY/CONFIRM tap remains, use action \"confirm\" (text=the button label). JSON only.";

export async function offlineOperateStep(goal, screen, history) {
  if (!ctx) return { action: "ask", say: "Offline model not loaded.", label: "" };
  const elems = (screen || []).slice(0, 40)
    .map((e, i) => `[${i}] "${e.text}"${e.editable ? " (input)" : ""}${e.clickable ? " (button)" : ""}`).join("\n");
  const hist = (history || []).slice(-6).map((h) => `- ${h}`).join("\n") || "(none)";
  const user = `GOAL: ${goal}\n\nDONE:\n${hist}\n\nSCREEN:\n${elems || "(empty)"}\n\nNext action JSON:`;
  try {
    const out = await ctx.completion({
      prompt: chatml(_OP_SYS, user), n_predict: 160, temperature: 0.2,
      stop: ["<|im_end|>", "<|endoftext|>"],
    });
    const j = JSON.parse((out?.text || "").trim());
    if (j && j.action) return j;
  } catch {}
  return { action: "ask", say: "I'm stuck.", label: "" };
}

export async function offlinePlanDevice(text) {
  // Rules first (instant, no model). If they yield a concrete action, use it.
  const r = rulesPlan(text);
  if (r.action) return r;
  // Otherwise, if the model is loaded, let it try for the trickier phrasing.
  if (ctx) {
    try {
      const out = await ctx.completion({
        prompt: chatml(DEVICE_SYS, text), n_predict: 200, temperature: 0.2,
        stop: ["<|im_end|>", "<|endoftext|>"],
      });
      const j = JSON.parse((out?.text || "").trim());
      if (j && typeof j === "object") return { reply: j.reply || r.reply, action: j.action || null };
    } catch {}
  }
  return r;
}
