// Home — greeting, quick-prompt chips, and action cards. Left phone in the ref.
import React, { useEffect, useState } from "react";
import { View, Text, ScrollView, TouchableOpacity, Image, StyleSheet } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { C, R, shadow } from "../../lib/theme";
import { ensureAuth, getUser, getSessions } from "../../lib/api";

const CHIPS = [
  { label: "Draft an email", prompt: "Help me draft an email" },
  { label: "Today's schedule", prompt: "What's on my calendar today?" },
  { label: "Open an app", prompt: "Open Chrome and search for today's news" },
  { label: "Quick facts", prompt: "Tell me an interesting fact" },
  { label: "Summarize", prompt: "Summarize this for me: " },
  { label: "Reminders", prompt: "Remind me to " },
];

function Chip({ label, onPress }) {
  return (
    <TouchableOpacity style={s.chip} onPress={onPress} activeOpacity={0.8}>
      <Text style={s.chipTxt}>{label}</Text>
    </TouchableOpacity>
  );
}

export default function HomeScreen({ navigation }) {
  const [name, setName] = useState("");
  const [recents, setRecents] = useState([]);

  const loadRecents = () => getSessions().then((d) => setRecents(d.sessions || [])).catch(() => {});

  useEffect(() => {
    ensureAuth().then(() => {
      const u = getUser();
      if (u?.name) setName(u.name.split(" ")[0]);
    });
    loadRecents();
    const unsub = navigation.addListener("focus", loadRecents); // refresh after chatting
    return unsub;
  }, [navigation]);

  const ask = (prompt) => navigation.navigate("Chat", { prefill: prompt });

  return (
    <LinearGradient colors={[C.bgTop, C.bgBot]} style={{ flex: 1 }}>
      <SafeAreaView style={{ flex: 1 }} edges={["top"]}>
        <View style={s.header}>
          <Image source={require("../../assets/logo.png")} style={s.avatar} />
          <View style={{ flexDirection: "row", gap: 10 }}>
            <TouchableOpacity style={s.iconBtn}>
              <Ionicons name="notifications-outline" size={20} color={C.ink2} />
            </TouchableOpacity>
            <TouchableOpacity style={s.iconBtn} onPress={() => navigation.navigate("Profile")}>
              <Ionicons name="menu" size={20} color={C.ink2} />
            </TouchableOpacity>
          </View>
        </View>

        <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: 24 }}>
          <Text style={s.greet}>
            <Text style={{ color: C.blue }}>Hi{name ? ` ${name}` : ""}!</Text> How can{"\n"}I help you today?
          </Text>

          <View style={s.chips}>
            {CHIPS.map((c) => (
              <Chip key={c.label} label={c.label} onPress={() => ask(c.prompt)} />
            ))}
          </View>

          <View style={s.row}>
            <TouchableOpacity style={[s.actCard, shadow(8)]} activeOpacity={0.9} onPress={() => navigation.navigate("Chat", { voice: true })}>
              <View style={[s.actIcon, { backgroundColor: "#E7F0FF" }]}>
                <Ionicons name="mic" size={20} color={C.blue} />
              </View>
              <Text style={s.actTitle}>Talk with Sarthi</Text>
              <Text style={s.actSub}>Speak naturally and get instant answers.</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[s.actCard, shadow(8)]} activeOpacity={0.9} onPress={() => navigation.navigate("Chat")}>
              <View style={[s.actIcon, { backgroundColor: "#EAF6F1" }]}>
                <Ionicons name="chatbubble-ellipses-outline" size={20} color={C.ok} />
              </View>
              <Text style={s.actTitle}>Chat with Sarthi</Text>
              <Text style={s.actSub}>Type your request in real time.</Text>
            </TouchableOpacity>
          </View>

          <TouchableOpacity activeOpacity={0.92} onPress={() => navigation.navigate("Chat", { mode: "pc" })}>
            <LinearGradient colors={["#EAF2FF", "#F6FAFF"]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={[s.wide, shadow(8)]}>
              <View style={{ flex: 1 }}>
                <Text style={s.wideTitle}>Control your PC</Text>
                <Text style={s.wideSub}>Ask Sarthi to open apps, search the web, and send mail — with your approval.</Text>
                <View style={s.tryBtn}>
                  <Text style={s.tryTxt}>Try it now</Text>
                  <Ionicons name="arrow-forward" size={14} color={C.blue} />
                </View>
              </View>
              <View style={s.wideIcon}>
                <Ionicons name="desktop-outline" size={30} color={C.blue} />
              </View>
            </LinearGradient>
          </TouchableOpacity>

          <TouchableOpacity activeOpacity={0.92} onPress={() => navigation.navigate("Chat", { mode: "device" })}>
            <LinearGradient colors={["#EAF7F1", "#F6FCFA"]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={[s.wide, { borderColor: "#D6EFE4" }, shadow(8)]}>
              <View style={{ flex: 1 }}>
                <Text style={s.wideTitle}>Control Your Device</Text>
                <Text style={s.wideSub}>Open apps, WhatsApp, call, navigate or search on this phone — by voice or chat, with your approval.</Text>
                <View style={s.tryBtn}>
                  <Text style={[s.tryTxt, { color: C.ok }]}>Try it now</Text>
                  <Ionicons name="arrow-forward" size={14} color={C.ok} />
                </View>
              </View>
              <View style={s.wideIcon}>
                <Ionicons name="phone-portrait-outline" size={30} color={C.ok} />
              </View>
            </LinearGradient>
          </TouchableOpacity>

          {recents.length > 0 && (
            <View style={{ marginTop: 26 }}>
              <View style={s.recentHead}>
                <Text style={s.recentTitle}>Recent chats</Text>
                <TouchableOpacity onPress={() => navigation.navigate("Chat")}>
                  <Text style={s.newChat}>New chat</Text>
                </TouchableOpacity>
              </View>
              {recents.slice(0, 8).map((r) => (
                <TouchableOpacity key={r.id} style={s.recentRow} activeOpacity={0.8}
                  onPress={() => navigation.navigate("Chat", { sessionId: r.id })}>
                  <View style={s.recentIcon}>
                    <Ionicons name="chatbubble-ellipses-outline" size={17} color={C.blue} />
                  </View>
                  <Text style={s.recentTxt} numberOfLines={1}>{r.title || "Chat"}</Text>
                  <Ionicons name="chevron-forward" size={16} color={C.muted} />
                </TouchableOpacity>
              ))}
            </View>
          )}
        </ScrollView>
      </SafeAreaView>
    </LinearGradient>
  );
}

const s = StyleSheet.create({
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: 20, paddingVertical: 8 },
  avatar: { width: 40, height: 40, borderRadius: 12, backgroundColor: "#fff" },
  iconBtn: { width: 40, height: 40, borderRadius: 12, backgroundColor: "#fff", alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: C.line },
  greet: { fontSize: 26, lineHeight: 33, fontWeight: "800", color: C.ink, paddingHorizontal: 20, marginTop: 10, letterSpacing: -0.4 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 9, paddingHorizontal: 20, marginTop: 18 },
  chip: { backgroundColor: "#fff", borderRadius: R.pill, paddingHorizontal: 15, paddingVertical: 10, borderWidth: 1, borderColor: C.line },
  chipTxt: { color: C.ink2, fontWeight: "600", fontSize: 13 },
  row: { flexDirection: "row", gap: 12, paddingHorizontal: 20, marginTop: 22 },
  actCard: { flex: 1, backgroundColor: "#fff", borderRadius: R.lg, padding: 15, borderWidth: 1, borderColor: C.line },
  actIcon: { width: 40, height: 40, borderRadius: 12, alignItems: "center", justifyContent: "center", marginBottom: 12 },
  actTitle: { fontSize: 15, fontWeight: "800", color: C.ink, marginBottom: 4 },
  actSub: { fontSize: 12.5, color: C.muted, lineHeight: 17 },
  wide: { flexDirection: "row", alignItems: "center", gap: 14, borderRadius: R.lg, padding: 18, marginHorizontal: 20, marginTop: 14, borderWidth: 1, borderColor: "#E1ECFB" },
  wideTitle: { fontSize: 17, fontWeight: "800", color: C.ink, marginBottom: 5 },
  wideSub: { fontSize: 12.5, color: C.ink2, lineHeight: 18, marginBottom: 12 },
  tryBtn: { flexDirection: "row", alignItems: "center", gap: 5, alignSelf: "flex-start", backgroundColor: "#fff", paddingHorizontal: 13, paddingVertical: 8, borderRadius: R.pill },
  tryTxt: { color: C.blue, fontWeight: "800", fontSize: 12.5 },
  wideIcon: { width: 62, height: 62, borderRadius: 18, backgroundColor: "#fff", alignItems: "center", justifyContent: "center" },
  recentHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: 20, marginBottom: 10 },
  recentTitle: { fontSize: 16, fontWeight: "800", color: C.ink },
  newChat: { fontSize: 13, fontWeight: "700", color: C.blue },
  recentRow: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: "#fff", marginHorizontal: 20, marginBottom: 8, paddingHorizontal: 14, paddingVertical: 13, borderRadius: R.md, borderWidth: 1, borderColor: C.line },
  recentIcon: { width: 34, height: 34, borderRadius: 10, backgroundColor: "#EEF4FF", alignItems: "center", justifyContent: "center" },
  recentTxt: { flex: 1, fontSize: 14.5, color: C.ink, fontWeight: "600" },
});
