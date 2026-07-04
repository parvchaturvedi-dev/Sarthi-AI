// Card for a device action Sarthi wants to run (open app / call / message /
// navigate / search). User taps to run it — nothing fires automatically.
import React, { useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import { C, R, shadow } from "../../lib/theme";
import { executeDeviceAction, actionLabel, NEEDS_OK } from "../../lib/device";

const ICON = {
  open_app: "apps", call: "call", sms: "chatbox-ellipses", whatsapp: "logo-whatsapp",
  maps: "navigate", web: "search", youtube: "logo-youtube", email: "mail",
};

export default function DeviceActionCard({ action }) {
  const [status, setStatus] = useState(""); // "", done, cancelled
  const [err, setErr] = useState("");

  async function run() {
    setErr("");
    try {
      await executeDeviceAction(action);
      setStatus("done");
    } catch (e) {
      setErr(e.message || "Couldn't do that.");
    }
  }

  if (status === "done")
    return (
      <View style={[s.result, { backgroundColor: C.okBg }]}>
        <Ionicons name="checkmark-circle" size={18} color={C.ok} />
        <Text style={[s.resultTxt, { color: C.ok }]}>Done — handed off to your phone.</Text>
      </View>
    );
  if (status === "cancelled")
    return (
      <View style={[s.result, { backgroundColor: "#F5F7FA" }]}>
        <Text style={[s.resultTxt, { color: C.muted }]}>Cancelled.</Text>
      </View>
    );

  const outward = NEEDS_OK.has(action.kind);
  return (
    <View style={[s.card, shadow(8)]}>
      <View style={s.head}>
        <View style={s.badge}>
          <Ionicons name={ICON[action.kind] || "phone-portrait"} size={16} color={C.blue} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>{actionLabel(action)}</Text>
          <Text style={s.sub}>{outward ? "Needs your OK before it goes out" : "Ready to open on your phone"}</Text>
        </View>
      </View>

      {!!err && <Text style={s.err}>⚠ {err}</Text>}

      <View style={s.btns}>
        <TouchableOpacity onPress={run} activeOpacity={0.85} style={{ flex: 1 }}>
          <LinearGradient colors={C.micGrad} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={s.go}>
            <Text style={s.goTxt}>{outward ? "Approve & open" : "Open"}</Text>
          </LinearGradient>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => setStatus("cancelled")} style={s.cancel}>
          <Text style={s.cancelTxt}>Cancel</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: "#F8FBFF", borderWidth: 1, borderColor: "#DCEAFB", borderRadius: R.lg, padding: 14, marginTop: 4, alignSelf: "stretch" },
  head: { flexDirection: "row", alignItems: "center", gap: 11, marginBottom: 14 },
  badge: { width: 38, height: 38, borderRadius: 12, backgroundColor: "#E7F0FF", alignItems: "center", justifyContent: "center" },
  title: { fontSize: 15, fontWeight: "800", color: C.ink },
  sub: { fontSize: 12, color: C.muted, marginTop: 2 },
  err: { color: C.danger, fontSize: 13, marginBottom: 8 },
  btns: { flexDirection: "row", gap: 8 },
  go: { paddingVertical: 12, borderRadius: R.sm, alignItems: "center" },
  goTxt: { color: "#fff", fontWeight: "800", fontSize: 14 },
  cancel: { paddingVertical: 12, paddingHorizontal: 18, borderRadius: R.sm, borderWidth: 1, borderColor: C.line, backgroundColor: "#fff", alignItems: "center" },
  cancelTxt: { color: C.ink2, fontWeight: "700", fontSize: 14 },
  result: { flexDirection: "row", alignItems: "center", gap: 8, padding: 13, borderRadius: R.md, marginTop: 4, maxWidth: "94%" },
  resultTxt: { fontWeight: "600", fontSize: 14, flexShrink: 1 },
});
