// Sign in — email/password, Google, or guest. Because the phone reaches the PC
// over your Wi-Fi, "Find my PC" auto-locates it first so login can go through.
import React, { useState, useEffect } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Alert, ScrollView } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as Google from "expo-auth-session/providers/google";
import * as WebBrowser from "expo-web-browser";
import { C, R, shadow } from "../../lib/theme";
import { login, register, googleAuth, guestLogin, discoverPCs, setBase, getBase } from "../../lib/api";
import { GOOGLE_ANDROID_CLIENT_ID } from "../../lib/google";

WebBrowser.maybeCompleteAuthSession();

export default function LoginScreen({ navigation }) {
  const [mode, setMode] = useState("login"); // login | register
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [pcNote, setPcNote] = useState("");

  const [gReq, gResp, gPrompt] = Google.useAuthRequest({
    androidClientId: GOOGLE_ANDROID_CLIENT_ID,
    scopes: ["openid", "email", "profile"],
  });

  useEffect(() => {
    (async () => {
      if (gResp?.type === "success") {
        const idToken = gResp.authentication?.idToken || gResp.params?.id_token;
        if (!idToken) { setBusy(false); Alert.alert("Google", "Couldn't get an ID token. Check the Web client ID setup on the PC (GOOGLE_LOGIN_CLIENT_ID)."); return; }
        try { await googleAuth(idToken); enter(); }
        catch (e) { Alert.alert("Google sign-in failed", e.message); }
        finally { setBusy(false); }
      } else if (gResp && gResp.type !== "success") setBusy(false);
    })();
  }, [gResp]);

  function enter() { navigation.replace("Main", { screen: "Home" }); }

  async function findPC() {
    setBusy(true);
    setPcNote("Scanning your Wi-Fi…");
    try {
      const pcs = await discoverPCs((frac) => setPcNote(`Scanning… ${Math.round(frac * 100)}%`));
      if (!pcs.length) { setPcNote("No PC found. Is the backend running on your PC (same Wi-Fi)?"); return; }
      await setBase(pcs[0].base);
      setPcNote(pcs.length === 1 ? `Found ${pcs[0].name} · ${pcs[0].base}` : `${pcs.length} PCs found — using ${pcs[0].name}. Pick another later in Profile.`);
    } catch (e) {
      setPcNote("Scan failed: " + e.message);
    } finally { setBusy(false); }
  }

  async function submit() {
    if (!email.trim() || !pw) { Alert.alert("Please fill in email and password"); return; }
    setBusy(true);
    try {
      if (mode === "register") await register(name.trim() || "there", email.trim(), pw);
      else await login(email.trim(), pw);
      enter();
    } catch (e) {
      Alert.alert(mode === "register" ? "Couldn't register" : "Login failed",
        e.message + "\n\nIf it can't reach the PC, tap 'Find my PC' first.");
    } finally { setBusy(false); }
  }

  async function doGoogle() { setBusy(true); try { await gPrompt(); } catch (e) { setBusy(false); Alert.alert("Google", e.message); } }
  async function doGuest() { setBusy(true); try { await guestLogin(); enter(); } catch { enter(); } finally { setBusy(false); } }

  const isReg = mode === "register";

  return (
    <LinearGradient colors={[C.bgTop, C.bgBot]} style={{ flex: 1 }}>
      <SafeAreaView style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: 24, paddingTop: 40, flexGrow: 1, justifyContent: "center" }} keyboardShouldPersistTaps="handled">
          <View style={{ alignItems: "center", marginBottom: 22 }}>
            <View style={[s.logo, shadow(8)]}><Ionicons name="sparkles" size={30} color={C.blue} /></View>
            <Text style={s.title}>{isReg ? "Create your account" : "Welcome to Sarthi"}</Text>
            <Text style={s.sub}>{isReg ? "One account for your phone & PC." : "Sign in to sync with your PC."}</Text>
          </View>

          <View style={[s.card, shadow(6)]}>
            {isReg && (
              <TextInput value={name} onChangeText={setName} placeholder="Your name" placeholderTextColor={C.muted} style={s.input} />
            )}
            <TextInput value={email} onChangeText={setEmail} placeholder="Email" placeholderTextColor={C.muted} autoCapitalize="none" autoCorrect={false} keyboardType="email-address" style={s.input} />
            <TextInput value={pw} onChangeText={setPw} placeholder="Password" placeholderTextColor={C.muted} secureTextEntry autoCapitalize="none" style={s.input} />

            <TouchableOpacity onPress={submit} disabled={busy} activeOpacity={0.85}>
              <LinearGradient colors={C.micGrad} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={s.primary}>
                <Text style={s.primaryTxt}>{busy ? "Please wait…" : isReg ? "Create account" : "Sign in"}</Text>
              </LinearGradient>
            </TouchableOpacity>

            <View style={s.orRow}><View style={s.line} /><Text style={s.or}>or</Text><View style={s.line} /></View>

            <TouchableOpacity onPress={doGoogle} disabled={!gReq || busy} style={s.google} activeOpacity={0.85}>
              <Ionicons name="logo-google" size={18} color={C.blue} />
              <Text style={s.googleTxt}>Continue with Google</Text>
            </TouchableOpacity>

            <TouchableOpacity onPress={findPC} disabled={busy} style={[s.google, { marginTop: 10, borderColor: C.line }]} activeOpacity={0.85}>
              <Ionicons name="wifi" size={18} color={C.ink2} />
              <Text style={[s.googleTxt, { color: C.ink2 }]}>Find my PC on Wi-Fi</Text>
            </TouchableOpacity>
            {!!pcNote && <Text style={s.pcNote}>{pcNote}</Text>}
          </View>

          <TouchableOpacity onPress={() => setMode(isReg ? "login" : "register")} style={{ marginTop: 18, alignItems: "center" }}>
            <Text style={s.switch}>{isReg ? "Already have an account? Sign in" : "New here? Create an account"}</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={doGuest} disabled={busy} style={{ marginTop: 14, alignItems: "center" }}>
            <Text style={s.guest}>Continue as guest</Text>
          </TouchableOpacity>
        </ScrollView>
      </SafeAreaView>
    </LinearGradient>
  );
}

const s = StyleSheet.create({
  logo: { width: 66, height: 66, borderRadius: 20, backgroundColor: "#fff", alignItems: "center", justifyContent: "center", marginBottom: 14 },
  title: { fontSize: 23, fontWeight: "800", color: C.ink, textAlign: "center" },
  sub: { fontSize: 13.5, color: C.ink2, marginTop: 6, textAlign: "center" },
  card: { backgroundColor: "#fff", borderRadius: R.lg, padding: 18, borderWidth: 1, borderColor: C.line },
  input: { borderWidth: 1, borderColor: C.line, borderRadius: R.md, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, color: C.ink, marginBottom: 12, backgroundColor: "#F8FBFF" },
  primary: { paddingVertical: 14, borderRadius: R.md, alignItems: "center", marginTop: 2 },
  primaryTxt: { color: "#fff", fontWeight: "800", fontSize: 15.5 },
  orRow: { flexDirection: "row", alignItems: "center", gap: 10, marginVertical: 16 },
  line: { flex: 1, height: 1, backgroundColor: C.line },
  or: { color: C.muted, fontSize: 12, fontWeight: "700" },
  google: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, borderWidth: 1.5, borderColor: "#DCE6F5", borderRadius: R.md, paddingVertical: 12, backgroundColor: "#fff" },
  googleTxt: { color: C.blue, fontWeight: "800", fontSize: 14.5 },
  pcNote: { color: C.ink2, fontSize: 12.5, marginTop: 10, textAlign: "center", lineHeight: 18 },
  switch: { color: C.blue, fontWeight: "700", fontSize: 14 },
  guest: { color: C.muted, fontWeight: "700", fontSize: 13.5 },
});
