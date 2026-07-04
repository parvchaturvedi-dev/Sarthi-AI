"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api, getToken, getUser, logout } from "@/lib/api";
import PendingCard from "./components/PendingCard";
import "./dashboard.css";

const fav = (d) => `https://www.google.com/s2/favicons?domain=${d}&sz=64`;
const SOON = ["whatsapp.com", "linkedin.com", "telegram.org", "slack.com", "discord.com", "outlook.com", "github.com", "notion.so"];
const GAPPS = [["Gmail", "mail.google.com"], ["Google Calendar", "calendar.google.com"], ["Google Drive", "drive.google.com"], ["Contacts", "contacts.google.com"]];

function esc(s){ return s.replace(/[&<>]/g, c=>({ "&":"&amp;","<":"&lt;",">":"&gt;" }[c])); }
function fmt(t){ let h=esc(t).replace(/```(\w+)?\n([\s\S]*?)```/g,(_,l,c)=>`<pre>${c.replace(/\n$/,"")}</pre>`); return h.replace(/`([^`]+)`/g,"<code>$1</code>").replace(/\n/g,"<br>"); }

export default function Dashboard() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [view, setView] = useState("home");
  const [sessions, setSessions] = useState([]);
  const [sid, setSid] = useState(null);
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [settings, setSettings] = useState(null);
  const scroll = useRef(null);

  useEffect(() => {
    if (!getToken()) { router.replace("/login"); return; }
    (async () => {
      try {
        const cur = await api("/api/session/current");
        setSid(cur.id); setMsgs(cur.turns); setView(cur.turns.length ? "chat" : "home");
        loadSessions();
      } catch { logout(); router.replace("/login"); return; }
      // if we just got back from Google OAuth, jump straight into Settings so
      // the user sees the freshly-connected state.
      if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("connected") === "google") {
        try { setSettings(await api("/api/settings")); setView("settings"); } catch {}
        window.history.replaceState({}, "", "/");
      }
      setReady(true);
    })();
  }, [router]);
  useEffect(() => { if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight; }, [msgs, view]);

  async function loadSessions(){ try { setSessions((await api("/api/sessions")).sessions); } catch {} }
  async function newChat(){ const d = await api("/api/session/new",{method:"POST"}); setSid(d.id); setMsgs([]); setView("home"); loadSessions(); }
  async function openSession(id){ const d = await api("/api/session/"+id); setSid(id); setMsgs(d.turns); setView("chat"); loadSessions(); }
  async function send(text){
    text=(text ?? input).trim(); if(!text || sending) return;
    setInput(""); setSending(true); setView("chat");
    setMsgs(m=>[...m,{role:"user",content:text},{role:"assistant",content:"…",think:true}]);
    try{
      const d=await api("/api/chat",{method:"POST",body:JSON.stringify({text,session_id:sid})});
      setSid(d.session_id);
      setMsgs(m=>{
        const base=m.filter(x=>!x.think);
        const r=d.replies?.length?d.replies:["(no response)"];
        const out=[...base,...r.map(x=>({role:"assistant",content:x}))];
        if (d.pending) out.push({role:"pending", action:d.pending});
        return out;
      });
      loadSessions();
    }catch(e){ setMsgs(m=>m.map(x=>x.think?{role:"assistant",content:"⚠️ "+e.message}:x)); }
    finally{ setSending(false); }
  }
  const openSettings = useCallback(async()=>{ setView("settings"); try{ setSettings(await api("/api/settings")); }catch{} },[]);
  async function setMode(mode){ setSettings(s=>({...s,mode})); await api("/api/settings",{method:"POST",body:JSON.stringify({mode})}); }
  async function connectGoogle(){
    try{
      const r = await api("/api/connectors/google/connect", { method: "POST" });
      if (r.error === "setup_needed") {
        alert("Google Web OAuth not configured on the cloud backend yet. Ask the admin to set GOOGLE_WEB_CLIENT_ID / GOOGLE_WEB_CLIENT_SECRET in Render.");
        return;
      }
      if (r.auth_url) { window.location.href = r.auth_url; return; }
      setSettings(await api("/api/settings"));
    } catch(e) { alert(e.message); }
  }

  if (!ready) return <div style={{minHeight:"100vh",display:"grid",placeItems:"center",color:"#8b91a1"}}>Loading…</div>;
  const user = getUser() || {};
  const gc = settings?.connectors?.google;
  const recent = sessions.slice(0, 3);

  return (
    <div className={"app-shell" + (collapsed ? " collapsed" : "")}>
      {/* SIDEBAR */}
      <aside className="side">
        <div className="brandrow">
          <img className="logo" src="/logo.png" alt="Sarthi" />
          <span className="name lbl">Sarthi</span>
          <button className="collapsebtn" title="Collapse" onClick={() => setCollapsed(c => !c)}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="11 7 6 12 11 17"/><polyline points="18 7 13 12 18 17"/></svg>
          </button>
        </div>

        <nav>
          <a className={"navitem" + (view === "home" ? " on" : "")} onClick={() => setView(msgs.length ? "chat" : "home")}>
            <span className="ic"><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg></span>
            <span className="lbl">Home</span>
          </a>
          <a className="navitem" onClick={newChat}>
            <span className="ic"><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8z"/><line x1="12" y1="9" x2="12" y2="14"/><line x1="9.5" y1="11.5" x2="14.5" y2="11.5"/></svg></span>
            <span className="lbl">New Chat</span>
          </a>
        </nav>

        <div className="hist">
          <div className="lbl">CHATS</div>
          <div>
            {sessions.map(s => (
              <div key={s.id} className={"item" + (s.id === sid ? " on" : "")} onClick={() => openSession(s.id)}>{s.title || "New chat"}</div>
            ))}
          </div>
        </div>

        <div className="upgrade">
          <div className="t">Sarthi Automation</div>
          <div className="d">Connect Gmail to let Sarthi work in the background</div>
          <button onClick={openSettings}>Set up</button>
        </div>

        <a className={"navitem settingsrow" + (view === "settings" ? " on" : "")} onClick={openSettings}>
          <span className="ic"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg></span>
          <span className="lbl">Settings</span>
        </a>
        <div className="userrow">
          <span className="uav" />
          <div style={{minWidth:0,flex:1}} className="lbl">
            <div className="un">{user.name || user.email}</div>
            <div className="out" onClick={() => { logout(); router.replace("/login"); }}>Sign out</div>
          </div>
        </div>
      </aside>

      {/* MAIN */}
      <main className="main">
        <div className="scroll" ref={scroll}>
          {/* HOME */}
          <div className={"wrap" + (view === "home" ? "" : " hidden")}>
            <div className="hero">
              <div className="hi"><mark>Welcome{user.name ? ", " + user.name.split(" ")[0] : ""}</mark></div>
              <div className="q">How can I help you today?</div>
            </div>
            <div className="grid2">
              <div className="card">
                <div className="ch">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M8 3v4M16 3v4M3 10h18M5 6h14a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z"/></svg>
                  Recent chats
                </div>
                <div>
                  {recent.length ? recent.map(s => (
                    <div key={s.id} className="row" onClick={() => openSession(s.id)}>
                      <span className="fico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></span>
                      <span className="rt">{s.title || "New chat"}</span>
                    </div>
                  )) : <div style={{color:"#a3a9b6",fontSize:"13.5px"}}>No chats yet</div>}
                </div>
              </div>
              <div className="card">
                <div className="ch">
                  <svg className="spark" width="16" height="16" viewBox="0 0 24 24" fill="#2f7ff0" stroke="none"><path d="M12 2c.5 3.8 2.2 5.5 6 6-3.8.5-5.5 2.2-6 6-.5-3.8-2.2-5.5-6-6 3.8-.5 5.5-2.2 6-6z"/></svg>
                  What Sarthi can do
                </div>
                <div className="caps">
                  <div className="cap"><span className="capic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg></span> Control your PC — open apps, type, search, screenshot</div>
                  <div className="cap"><span className="capic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/></svg></span> Send email directly via Gmail (Automation)</div>
                  <div className="cap"><span className="capic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18z"/></svg></span> Search the web and answer</div>
                  <div className="cap"><span className="capic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></span> Chat with memory of past conversations</div>
                </div>
              </div>
            </div>
            <div className="grid2">
              {[["Write a professional email for me","Write an email"],["Open notepad and write a to-do list","Make a to-do list"]].map(([p,label]) => (
                <div key={label} className="suggest" onClick={() => send(p)}>
                  <div className="ch"><svg className="spark" viewBox="0 0 24 24" fill="#2f7ff0" stroke="none"><path d="M12 2c.5 3.8 2.2 5.5 6 6-3.8.5-5.5 2.2-6 6-.5-3.8-2.2-5.5-6-6 3.8-.5 5.5-2.2 6-6z"/></svg>Suggested</div>
                  <div className="st">{label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* CHAT */}
          <div className={"thread" + (view === "chat" ? "" : " hidden")}>
            {msgs.map((m, i) => (
              <div key={i} className={"msg " + (m.role === "user" ? "user" : "nova")}>
                <span className="av" />
                {m.role === "pending"
                  ? <PendingCard action={m.action} />
                  : <div className={"bubble" + (m.think ? " think" : "")} dangerouslySetInnerHTML={{ __html: fmt(m.content) }} />}
              </div>
            ))}
          </div>

          {/* SETTINGS */}
          <div className={"settings" + (view === "settings" ? "" : " hidden")}>
            <h1>Settings</h1>
            <div className="sub">Control how Sarthi works.</div>
            <div className="sec">
              <h2>Mode</h2>
              <p>PC Controlling = Sarthi sees the screen and operates apps itself. Automation = where a connector is set up (like Gmail), it acts directly in the background — without showing anything.</p>
              <div className="modes">
                <div className={"mode" + (settings?.mode === "pc_control" ? " on" : "")} onClick={() => setMode("pc_control")}>
                  <div className="t"><span className="mdot" /> PC Controlling</div>
                  <div className="d">Sees the screen, searches and acts — on any app.</div>
                </div>
                <div className={"mode" + (settings?.mode === "automation" ? " on" : "")} onClick={() => setMode("automation")}>
                  <div className="t"><span className="mdot" /> Automation</div>
                  <div className="d">Works directly via API in connected apps (Gmail) — silently. PC control elsewhere.</div>
                </div>
              </div>
            </div>
            <div className="sec">
              <h2>Connections</h2>
              <p>Connect once, then Sarthi handles it in the background. One Google login connects Gmail, Calendar, Drive &amp; Contacts.</p>
              {GAPPS.map(([name, d]) => (
                <div key={name} className={"conn" + (gc?.connected ? " done" : "")}>
                  <div className="cic"><img src={fav(d)} onError={(e) => (e.currentTarget.style.display = "none")} alt="" /></div>
                  <div><div className="cname">{name}</div><div className="cstat">{gc?.connected ? "Connected · " + gc.email : settings?.google_ready ? "Not connected" : "Setup needed"}</div></div>
                  <button className="cbtn" onClick={connectGoogle}>{gc?.connected ? "Reconnect" : "Add connection"}</button>
                </div>
              ))}
              {SOON.map(d => (
                <div key={d} className="conn">
                  <div className="cic"><img src={fav(d)} onError={(e) => (e.currentTarget.style.display = "none")} alt="" /></div>
                  <div><div className="cname" style={{textTransform:"capitalize"}}>{d.split(".")[0]}</div><div className="cstat">Coming soon</div></div>
                  <span className="soon">Soon</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* COMPOSER */}
        <div className={"composer" + (view === "settings" ? " hidden" : "")}>
          <div className="inner">
            <form className="bar" onSubmit={(e) => { e.preventDefault(); send(); }}>
              <span className="plus" title="Attach">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><line x1="12" y1="6" x2="12" y2="18"/><line x1="6" y1="12" x2="18" y2="12"/></svg>
              </span>
              <input value={input} onChange={(e) => setInput(e.target.value)} autoComplete="off" placeholder="Ask Sarthi anything, or tell it a task…" />
              <button type="button" className="iconbtn ghost" title="Voice">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/></svg>
              </button>
              <button type="submit" className="iconbtn send" title="Send" disabled={sending}>
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
              </button>
            </form>
          </div>
        </div>
      </main>
    </div>
  );
}
