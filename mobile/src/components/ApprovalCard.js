// In-chat approval card: Sarthi drafts an email/calendar action; user reviews,
// edits inline, then Approve (executes) / Reject (discards). Nothing is sent
// until Approve — mirrors the desktop web flow.
import React, { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import { C, R, shadow } from "../../lib/theme";
import { executeAction } from "../../lib/api";
import { googleConnected, gmailSend, calendarAdd } from "../../lib/google";

function Field({ label, value, editing, onChange, multiline }) {
  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={s.label}>{label}</Text>
      {editing ? (
        <TextInput
          value={value}
          onChangeText={onChange}
          multiline={multiline}
          style={[s.input, multiline && { minHeight: 96, textAlignVertical: "top" }]}
          placeholderTextColor={C.muted}
        />
      ) : (
        <Text style={s.val}>{value || "—"}</Text>
      )}
    </View>
  );
}

export default function ApprovalCard({ action }) {
  const [f, setF] = useState({ ...action });
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState(""); // "", sending, done, rejected
  const [msg, setMsg] = useState("");
  const isEmail = action.kind === "email";

  async function approve() {
    setStatus("sending");
    setMsg("");
    try {
      // Prefer on-device Google (no PC needed); fall back to the backend.
      if (await googleConnected()) {
        if (f.kind === "email") {
          await gmailSend(f.to, f.subject || "", f.body || "");
          setStatus("done"); setMsg(`Email sent to ${f.to}.`); return;
        }
        if (f.kind === "calendar") {
          await calendarAdd(f.title, f.start, f.end);
          setStatus("done"); setMsg(`Added '${f.title}' to your calendar.`); return;
        }
      }
      const r = await executeAction(f);
      if (r.ok) { setStatus("done"); setMsg(r.message); }
      else { setStatus(""); setMsg("⚠ " + r.message); }
    } catch (e) {
      setStatus("");
      setMsg("⚠ " + e.message);
    }
  }

  if (status === "done")
    return (
      <View style={[s.result, { backgroundColor: C.okBg }]}>
        <Ionicons name="checkmark-circle" size={18} color={C.ok} />
        <Text style={[s.resultTxt, { color: C.ok }]}>{msg}</Text>
      </View>
    );
  if (status === "rejected")
    return (
      <View style={[s.result, { backgroundColor: "#F5F7FA" }]}>
        <Ionicons name="close-circle" size={18} color={C.muted} />
        <Text style={[s.resultTxt, { color: C.muted }]}>Cancelled — nothing was sent.</Text>
      </View>
    );

  return (
    <View style={[s.card, shadow(8)]}>
      <View style={s.head}>
        <Ionicons name={isEmail ? "mail-outline" : "calendar-outline"} size={16} color={C.blue} />
        <Text style={s.headTxt}>
          {isEmail ? "Draft email — review before sending" : "New event — review before adding"}
        </Text>
      </View>

      {isEmail ? (
        <>
          <Field label="TO" value={f.to} editing={editing} onChange={(v) => setF({ ...f, to: v })} />
          <Field label="SUBJECT" value={f.subject} editing={editing} onChange={(v) => setF({ ...f, subject: v })} />
          <Field label="BODY" value={f.body} editing={editing} multiline onChange={(v) => setF({ ...f, body: v })} />
        </>
      ) : (
        <>
          <Field label="TITLE" value={f.title} editing={editing} onChange={(v) => setF({ ...f, title: v })} />
          <Field label="WHEN" value={f.start} editing={editing} onChange={(v) => setF({ ...f, start: v })} />
          <Field label="END (OPTIONAL)" value={f.end || ""} editing={editing} onChange={(v) => setF({ ...f, end: v })} />
        </>
      )}

      {!!msg && <Text style={s.err}>{msg}</Text>}

      <View style={s.btns}>
        <TouchableOpacity onPress={approve} disabled={status === "sending"} activeOpacity={0.85} style={{ flex: 1 }}>
          <LinearGradient colors={C.userGrad} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={s.approve}>
            <Text style={s.approveTxt}>{status === "sending" ? "Sending…" : "Approve"}</Text>
          </LinearGradient>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => setEditing((e) => !e)} style={s.ghost}>
          <Text style={s.ghostTxt}>{editing ? "Done" : "Edit"}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => setStatus("rejected")} style={[s.ghost, { borderColor: "#F3D0D0" }]}>
          <Text style={[s.ghostTxt, { color: C.danger }]}>Reject</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: "#F8FBFF", borderWidth: 1, borderColor: "#DCEAFB", borderRadius: R.lg, padding: 16, marginTop: 4, maxWidth: "94%" },
  head: { flexDirection: "row", alignItems: "center", gap: 7, marginBottom: 14 },
  headTxt: { color: C.blueDark, fontWeight: "700", fontSize: 13 },
  label: { fontSize: 10.5, fontWeight: "800", color: C.muted, letterSpacing: 0.6, marginBottom: 4 },
  val: { fontSize: 14.5, color: C.ink, lineHeight: 21 },
  input: { borderWidth: 1, borderColor: "#CFDCEE", borderRadius: R.sm, paddingHorizontal: 12, paddingVertical: 9, fontSize: 14.5, color: C.ink, backgroundColor: "#fff" },
  err: { color: C.danger, fontSize: 13, marginBottom: 8 },
  btns: { flexDirection: "row", gap: 8, marginTop: 4 },
  approve: { paddingVertical: 12, borderRadius: R.sm, alignItems: "center" },
  approveTxt: { color: "#fff", fontWeight: "800", fontSize: 14 },
  ghost: { paddingVertical: 12, paddingHorizontal: 16, borderRadius: R.sm, borderWidth: 1, borderColor: C.line, backgroundColor: "#fff", alignItems: "center" },
  ghostTxt: { color: C.ink2, fontWeight: "700", fontSize: 14 },
  result: { flexDirection: "row", alignItems: "center", gap: 8, padding: 13, borderRadius: R.md, marginTop: 4, maxWidth: "94%" },
  resultTxt: { fontWeight: "600", fontSize: 14, flexShrink: 1 },
});
