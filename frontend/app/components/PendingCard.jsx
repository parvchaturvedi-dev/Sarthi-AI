"use client";
import { useState } from "react";
import { api } from "@/lib/api";

const S = {
  card: { border: "1px solid #d8e6fb", background: "#f7faff", borderRadius: 16, padding: 16, maxWidth: "82%", boxShadow: "0 1px 2px rgba(16,24,40,.04)" },
  head: { fontSize: 13, fontWeight: 700, color: "#2a5fb8", marginBottom: 12, display: "flex", alignItems: "center", gap: 7 },
  label: { fontSize: 11, fontWeight: 700, color: "#8b91a1", letterSpacing: ".03em", marginBottom: 3, textTransform: "uppercase" },
  val: { fontSize: 14, color: "#1b2230", lineHeight: 1.55, whiteSpace: "pre-wrap", marginBottom: 12 },
  input: { width: "100%", border: "1px solid #cfd9ea", borderRadius: 9, padding: "9px 11px", fontSize: 14, color: "#1b2230", outline: "none", marginBottom: 12, fontFamily: "inherit", background: "#fff" },
  btns: { display: "flex", gap: 8, marginTop: 4 },
  approve: { padding: "9px 18px", borderRadius: 10, border: "none", cursor: "pointer", fontWeight: 700, fontSize: 13, color: "#fff", background: "linear-gradient(135deg,#12a18c,#0d8f7c)", boxShadow: "0 4px 12px rgba(18,161,140,.3)" },
  edit: { padding: "9px 16px", borderRadius: 10, border: "1px solid #d8dbe4", cursor: "pointer", fontWeight: 700, fontSize: 13, color: "#4b5262", background: "#fff" },
  reject: { padding: "9px 16px", borderRadius: 10, border: "1px solid #f3d0d0", cursor: "pointer", fontWeight: 700, fontSize: 13, color: "#e5484d", background: "#fff" },
  done: { background: "#e1f5ef", color: "#0d8f7c", border: "1px solid #b9e6da", borderRadius: 14, padding: "12px 16px", fontSize: 14, fontWeight: 600, maxWidth: "82%" },
  cancel: { background: "#f6f7fa", color: "#8b91a1", border: "1px solid #edeff3", borderRadius: 14, padding: "12px 16px", fontSize: 14, maxWidth: "82%" },
  err: { color: "#e5484d", fontSize: 13, marginBottom: 8 },
};

function Field({ label, value, editing, onChange, textarea }) {
  return (
    <div>
      <div style={S.label}>{label}</div>
      {editing ? (
        textarea
          ? <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={7} style={{ ...S.input, resize: "vertical" }} />
          : <input value={value} onChange={(e) => onChange(e.target.value)} style={S.input} />
      ) : <div style={S.val}>{value || <span style={{ color: "#a3a9b6" }}>(empty)</span>}</div>}
    </div>
  );
}

export default function PendingCard({ action }) {
  const [f, setF] = useState({ ...action });
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState("");   // "" | sending | done | rejected
  const [msg, setMsg] = useState("");
  const isEmail = action.kind === "email";

  async function approve() {
    setStatus("sending"); setMsg("");
    try {
      const r = await api("/api/action/execute", { method: "POST", body: JSON.stringify(f) });
      if (r.ok) { setStatus("done"); setMsg(r.message); }
      else { setStatus(""); setMsg("⚠️ " + r.message); }
    } catch (e) { setStatus(""); setMsg("⚠️ " + e.message); }
  }

  if (status === "done") return <div style={S.done}>✓ {msg}</div>;
  if (status === "rejected") return <div style={S.cancel}>Cancelled — nothing was sent.</div>;

  return (
    <div style={S.card}>
      <div style={S.head}>{isEmail ? "Draft email — review before sending" : "New calendar event — review before adding"}</div>
      {isEmail ? (
        <>
          <Field label="To" value={f.to} editing={editing} onChange={(v) => setF({ ...f, to: v })} />
          <Field label="Subject" value={f.subject} editing={editing} onChange={(v) => setF({ ...f, subject: v })} />
          <Field label="Body" value={f.body} editing={editing} textarea onChange={(v) => setF({ ...f, body: v })} />
        </>
      ) : (
        <>
          <Field label="Title" value={f.title} editing={editing} onChange={(v) => setF({ ...f, title: v })} />
          <Field label="When (start)" value={f.start} editing={editing} onChange={(v) => setF({ ...f, start: v })} />
          <Field label="End (optional)" value={f.end || ""} editing={editing} onChange={(v) => setF({ ...f, end: v })} />
        </>
      )}
      {msg && <div style={S.err}>{msg}</div>}
      <div style={S.btns}>
        <button onClick={approve} disabled={status === "sending"} style={S.approve}>{status === "sending" ? "Sending…" : "Approve"}</button>
        <button onClick={() => setEditing((e) => !e)} style={S.edit}>{editing ? "Done editing" : "Edit"}</button>
        <button onClick={() => setStatus("rejected")} style={S.reject}>Reject</button>
      </div>
    </div>
  );
}
