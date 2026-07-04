// Nova web UI (light dashboard) — talks to the FastAPI backend.
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
let state = { sessionId: null, sending: false, mode: "pc_control" };

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// ---------- views ----------
function setView(v) {
  $("#home-view").classList.toggle("hidden", v !== "home");
  $("#thread").classList.toggle("hidden", v !== "chat");
  $("#settings-view").classList.toggle("hidden", v !== "settings");
  $("#composer").classList.toggle("hidden", v === "settings");
  $("#nav-home").classList.toggle("on", v === "home");
  $("#nav-settings").classList.toggle("on", v === "settings");
  if (v === "settings") renderSettings();
  if (v !== "settings") setTimeout(() => $("#input").focus(), 40);
}

// ---------- rendering ----------
function esc(s){ return s.replace(/[&<>]/g, c=>({ "&":"&amp;","<":"&lt;",">":"&gt;" }[c])); }
function fmt(text){
  let h = esc(text).replace(/```(\w+)?\n([\s\S]*?)```/g, (_,l,c)=>`<pre>${c.replace(/\n$/,"")}</pre>`);
  return h.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\n/g, "<br>");
}
function addMsg(role, text) {
  const who = role === "user" ? "user" : "nova";
  const el = document.createElement("div");
  el.className = "msg " + who;
  el.innerHTML = `<div class="av"></div><div class="bubble">${fmt(text)}</div>`;
  $("#thread").appendChild(el);
  $("#scroll").scrollTop = $("#scroll").scrollHeight;
  return el;
}
function clearThread(){ $("#thread").innerHTML = ""; }

// ---------- sessions ----------
async function loadSessions() {
  const data = await api("/api/sessions");
  const box = $("#chats"); box.innerHTML = "";
  const recent = $("#recent-chats"); recent.innerHTML = "";
  data.sessions.forEach((s, i) => {
    const d = document.createElement("div");
    d.className = "item" + (s.id === state.sessionId ? " on" : "");
    d.textContent = s.title || "New chat";
    d.onclick = () => openSession(s.id, s.title);
    box.appendChild(d);
    if (i < 3) {
      const r = document.createElement("div");
      r.className = "row";
      r.innerHTML = `<span class="fico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg></span><span class="rt">${esc(s.title || "New chat")}</span>`;
      r.onclick = () => openSession(s.id, s.title);
      recent.appendChild(r);
    }
  });
  if (!data.sessions.length) recent.innerHTML = `<div style="color:#a3a9b6;font-size:13.5px">No chats yet</div>`;
}
async function openSession(id, title) {
  const data = await api("/api/session/" + id);
  state.sessionId = id;
  clearThread();
  data.turns.forEach(t => addMsg(t.role, t.content));
  setView(data.turns.length ? "chat" : "home");
  loadSessions();
}
async function newChat() {
  const data = await api("/api/session/new", { method: "POST" });
  state.sessionId = data.id;
  clearThread(); setView("home"); loadSessions();
}

// ---------- chat ----------
async function send(text) {
  text = (text || $("#input").value).trim();
  if (!text || state.sending) return;
  state.sending = true; $("#send").disabled = true;
  $("#input").value = "";
  setView("chat");
  addMsg("user", text);
  const thinking = addMsg("nova", "…"); thinking.querySelector(".bubble").classList.add("think");
  try {
    const data = await api("/api/chat", { method: "POST", body: JSON.stringify({ text, session_id: state.sessionId }) });
    state.sessionId = data.session_id;
    thinking.remove();
    (data.replies && data.replies.length ? data.replies : ["(no response)"]).forEach(r => addMsg("nova", r));
    loadSessions();
  } catch (e) {
    thinking.querySelector(".bubble").classList.remove("think");
    thinking.querySelector(".bubble").textContent = "⚠️ " + e.message;
  } finally { state.sending = false; $("#send").disabled = false; $("#input").focus(); }
}

// ---------- settings ----------
async function renderSettings() {
  const s = await api("/api/settings");
  applyMode(s.mode);
  renderBrain(s.brain);
  const g = (s.connectors && s.connectors.google) || {};
  const conns = $$(".google-conn"), stats = $$(".gstat"), btns = $$(".gbtn");
  if (g.connected) {
    stats.forEach(x => x.textContent = "Connected · " + g.email);
    conns.forEach(x => x.classList.add("done"));
    btns.forEach(x => x.textContent = "Reconnect");
    $("#google-setup").classList.remove("open");
  } else {
    stats.forEach(x => x.textContent = s.google_ready ? "Not connected" : "Setup needed");
    conns.forEach(x => x.classList.remove("done"));
    btns.forEach(x => x.textContent = "Add connection");
    if (!s.google_ready) $("#google-setup").classList.add("open");
  }
}
function applyMode(mode) {
  state.mode = mode;
  $("#mode-pc").classList.toggle("on", mode === "pc_control");
  $("#mode-auto").classList.toggle("on", mode === "automation");
}
async function setMode(mode) {
  applyMode(mode);
  await api("/api/settings", { method: "POST", body: JSON.stringify({ mode }) });
}
// ---------- brain (AI model) ----------
async function renderBrain(brain) {
  brain = brain || {};
  try {
    const m = await api("/api/brain/models");
    const sel = $("#brain-model-local");
    sel.innerHTML = "";
    (m.local_models || []).forEach(name => {
      const o = document.createElement("option"); o.value = name; o.textContent = name; sel.appendChild(o);
    });
    if (!(m.local_models || []).length) {
      const o = document.createElement("option");
      o.value = ""; o.textContent = "(no local models — run: ollama pull qwen2.5:7b)"; sel.appendChild(o);
    }
  } catch (e) {}
  applyBrainMode(brain.mode || "local");
  if (brain.mode === "local" && brain.model) $("#brain-model-local").value = brain.model;
  if (brain.mode === "api") {
    if (brain.provider) $("#brain-provider").value = brain.provider;
    if (brain.model) $("#brain-model-api").value = brain.model;
  }
  $("#brain-status").textContent = brain.api_key_set ? "Key saved" : "";
}
function applyBrainMode(m) {
  $("#brain-local").classList.toggle("on", m === "local");
  $("#brain-api").classList.toggle("on", m === "api");
  $("#brain-local-form").classList.toggle("hidden", m !== "local");
  $("#brain-api-form").classList.toggle("hidden", m !== "api");
}
async function saveBrain() {
  const isApi = $("#brain-api").classList.contains("on");
  const body = isApi
    ? { mode: "api", provider: $("#brain-provider").value, model: $("#brain-model-api").value.trim(), api_key: $("#brain-key").value.trim() }
    : { mode: "local", provider: "ollama", model: $("#brain-model-local").value };
  $("#brain-status").textContent = "Saving…";
  try {
    const r = await api("/api/brain", { method: "POST", body: JSON.stringify(body) });
    if (r.working) { $("#brain-status").textContent = "✓ Connected — " + (r.brain.model || body.model || "local"); $("#brain-key").value = ""; }
    else { $("#brain-status").textContent = "⚠ " + (r.error || "not working"); }
  } catch (e) { $("#brain-status").textContent = "Error: " + e.message; }
}

async function connectGoogle() {
  $$(".gstat").forEach(x => x.textContent = "Opening Google login… (sign in on the new tab)");
  try {
    const r = await api("/api/connectors/google/connect", { method: "POST" });
    if (r.error === "setup_needed") { $("#google-setup").classList.add("open"); $$(".gstat").forEach(x => x.textContent = "Complete the setup below first"); return; }
    if (r.ok) renderSettings(); else $$(".gstat").forEach(x => x.textContent = "Error: " + (r.error || "fail"));
  } catch (e) { $$(".gstat").forEach(x => x.textContent = "Error: " + e.message); }
}

// ---------- wiring ----------
$("#collapse").onclick = () => document.body.classList.toggle("collapsed");
$("#nav-home").onclick = () => setView("home");
$("#nav-new").onclick = newChat;
$("#nav-settings").onclick = () => setView("settings");
$("#send").onclick = () => send();
$("#up-btn").onclick = () => setView("settings");
$("#input").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); send(); } });
$$(".suggest").forEach(c => c.onclick = () => send(c.dataset.prompt));
$$(".mode[data-mode]").forEach(m => m.onclick = () => setMode(m.dataset.mode));
$$(".mode[data-bmode]").forEach(m => m.onclick = () => applyBrainMode(m.dataset.bmode));
$("#brain-save").onclick = saveBrain;
$$(".gbtn").forEach(b => b.onclick = connectGoogle);

(async function init(){
  try {
    const cur = await api("/api/session/current");
    state.sessionId = cur.id;
    cur.turns.forEach(t => addMsg(t.role, t.content));
    setView(cur.turns.length ? "chat" : "home");
    await loadSessions();
    const s = await api("/api/settings"); applyMode(s.mode);
  } catch(e){ console.error(e); }
})();
