// Profile / Settings — mode toggle, server URL, connector status, about.
import React, { useEffect, useState } from "react";
import { View, Text, TextInput, TouchableOpacity, ScrollView, Switch, Image, StyleSheet, Alert } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { C, R, shadow } from "../../lib/theme";
import { loadBase, getBase, setBase, getSettings, setMode, ensureAuth, getUser, ping, getBrainModels, setBrain, discoverPCs, pairPC, logout, accountEmail } from "../../lib/api";
import { modelInfo, downloadModel, deleteModel, MODEL } from "../../lib/offline";
import { hasAgent, agentEnabled, openAccessibilitySettings, probe, canDrawOverlays, requestOverlayPermission, startOverlay, stopOverlay, setOverlayPersistent } from "../../lib/agent";
import * as Google from "expo-auth-session/providers/google";
import * as WebBrowser from "expo-web-browser";
import { GOOGLE_ANDROID_CLIENT_ID, GOOGLE_SCOPES, saveGoogleSession, clearGoogleSession, googleEmail, fetchGoogleEmail } from "../../lib/google";

WebBrowser.maybeCompleteAuthSession();

const PROVIDER_LABEL = { openai: "ChatGPT", claude: "Claude", gemini: "Gemini", grok: "Grok" };

function Card({ children }) {
  return <View style={[s.card, shadow(6)]}>{children}</View>;
}

export default function ProfileScreen({ navigation }) {
  const [base, setBaseState] = useState(getBase());
  const [pcs, setPcs] = useState([]);            // Sarthi PCs found on the Wi-Fi
  const [scan, setScan] = useState("");          // scan status text
  const [name, setName] = useState("there");
  const [mode, setModeState] = useState("automation");
  const [google, setGoogle] = useState(null);
  const [status, setStatus] = useState("checking…");
  const [model, setModel] = useState({ exists: false, size: 0 });
  const [dl, setDl] = useState(null); // download progress 0..1, or null
  const [agentOn, setAgentOn] = useState(false);
  const [floating, setFloating] = useState(false);
  const [gEmail, setGEmail] = useState(null);
  const [gBusy, setGBusy] = useState(false);

  // PC brain (AI model) selection
  const [brainMode, setBrainMode] = useState("local");   // local | api
  const [brainProvider, setBrainProvider] = useState("openai");
  const [brainModel, setBrainModel] = useState("");       // chosen local model
  const [brainModelApi, setBrainModelApi] = useState(""); // optional api model override
  const [brainKey, setBrainKey] = useState("");
  const [apiKeySet, setApiKeySet] = useState(false);
  const [localModels, setLocalModels] = useState([]);
  const [brainBusy, setBrainBusy] = useState(false);
  const [brainStatus, setBrainStatus] = useState("");

  const [gReq, gResp, gPrompt] = Google.useAuthRequest({
    androidClientId: GOOGLE_ANDROID_CLIENT_ID,
    scopes: GOOGLE_SCOPES,
  });

  useEffect(() => { googleEmail().then(setGEmail); }, []);

  useEffect(() => {
    (async () => {
      if (gResp?.type === "success") {
        const tok = gResp.authentication?.accessToken;
        if (!tok) { setGBusy(false); return; }
        const email = await fetchGoogleEmail(tok);
        await saveGoogleSession(tok, email);
        setGEmail(email);
        setGBusy(false);
        Alert.alert("Connected", `Google connected as ${email || "your account"}. Gmail & Calendar now work from this phone.`);
      } else if (gResp && gResp.type !== "success") {
        setGBusy(false);
      }
    })();
  }, [gResp]);

  async function connectGoogle() {
    setGBusy(true);
    try { await gPrompt(); } catch (e) { setGBusy(false); Alert.alert("Couldn't connect", e.message); }
  }
  async function disconnectGoogle() {
    await clearGoogleSession();
    setGEmail(null);
  }

  async function refresh() {
    try {
      await ping();
      setStatus("connected");
      const st = await getSettings();
      if (st?.mode) setModeState(st.mode);
      setGoogle(st?.google?.email || st?.google_email || (st?.google?.connected ? "connected" : null));
      loadBrain(st?.brain);
    } catch (e) {
      setStatus("offline");
    }
  }

  async function loadBrain(brain) {
    try {
      const bm = await getBrainModels();
      setLocalModels(bm?.local_models || []);
    } catch {}
    const b = brain || {};
    if (b.mode) setBrainMode(b.mode);
    if (b.provider && b.mode === "api") setBrainProvider(b.provider);
    if (b.model) (b.mode === "api" ? setBrainModelApi : setBrainModel)(b.model);
    setApiKeySet(!!b.api_key_set);
  }

  async function saveBrain() {
    setBrainBusy(true);
    setBrainStatus("Saving…");
    const body =
      brainMode === "api"
        ? { mode: "api", provider: brainProvider, model: brainModelApi.trim(), api_key: brainKey.trim() }
        : { mode: "local", provider: "ollama", model: brainModel };
    try {
      const r = await setBrain(body);
      if (r?.working) {
        setBrainStatus("✓ Connected · " + (r.brain?.model || body.model || "local"));
        setBrainKey("");
        setApiKeySet(!!r.brain?.api_key_set);
      } else {
        setBrainStatus("⚠ " + (r?.error || "not working"));
      }
    } catch (e) {
      setBrainStatus("Error: " + e.message);
    } finally {
      setBrainBusy(false);
    }
  }

  useEffect(() => {
    (async () => {
      await loadBase();
      setBaseState(getBase());
      await ensureAuth();
      const u = getUser();
      if (u?.name) setName(u.name.split(" ")[0]);
      refresh();
      try { setModel(await modelInfo()); } catch {}
      if (hasAgent) { try { setAgentOn(await agentEnabled()); } catch {} }
    })();
  }, []);

  async function doDownload() {
    setDl(0);
    try {
      await downloadModel((frac) => setDl(frac));
      setModel(await modelInfo());
      Alert.alert("Offline brain ready", "Sarthi can now chat and control your device with the PC off.");
    } catch (e) {
      Alert.alert("Download failed", e.message);
    } finally {
      setDl(null);
    }
  }

  async function doDelete() {
    await deleteModel();
    setModel(await modelInfo());
  }

  const mb = (b) => Math.round((b || 0) / 1e6);

  async function toggleFloating(v) {
    if (v) {
      const can = await canDrawOverlays();
      if (!can) {
        requestOverlayPermission();
        Alert.alert("One-time permission", "Turn ON “Display over other apps” for Sarthi, then flip this switch again.");
        return;
      }
      startOverlay();
      setOverlayPersistent(true);
      setFloating(true);
    } else {
      stopOverlay();
      setOverlayPersistent(false);
      setFloating(false);
    }
  }

  async function doProbe() {
    const p = await probe();
    setAgentOn(!!p.enabled);
    Alert.alert(
      "Device control test",
      `Native module: ${p.hasAgent ? "FOUND ✓" : "MISSING ✗"}\n` +
      `Service enabled: ${p.enabled ? "YES ✓" : "NO ✗"}\n` +
      `Screen read: ${p.count >= 0 ? p.count + " items ✓" : "failed"}\n` +
      (p.error ? `\nError: ${p.error}` : "\nAll good — try “whatsapp pe X ko message bhejo”.")
    );
  }

  async function saveServer() {
    const v = await setBase(base);
    setBaseState(v);
    setStatus("checking…");
    refresh();
    Alert.alert("Server saved", v);
  }

  async function findPCs() {
    setScan("Scanning your Wi-Fi…");
    setPcs([]);
    try {
      const found = await discoverPCs((frac) => setScan(`Scanning… ${Math.round(frac * 100)}%`));
      setPcs(found);
      setScan(found.length ? `${found.length} PC${found.length > 1 ? "s" : ""} found` : "No PC found — is the backend running on the same Wi-Fi?");
    } catch (e) {
      setScan("Scan failed: " + e.message);
    }
  }

  async function connectPC(pc) {
    try {
      await pairPC(pc.base, accountEmail() || "", null);   // claim it for this account
      setBaseState(pc.base);
      setStatus("checking…");
      refresh();
      Alert.alert("Connected", `Now controlling ${pc.name} (${pc.base}).`);
    } catch (e) {
      Alert.alert("Couldn't connect", e.message);
    }
  }

  async function signOut() {
    await logout();
    navigation?.getParent()?.reset({ index: 0, routes: [{ name: "Login" }] });
  }

  async function toggleMode(v) {
    const next = v ? "automation" : "control";
    setModeState(next);
    try {
      await setMode(next);
    } catch {
      Alert.alert("Couldn't reach backend", "Is the PC server on?");
    }
  }

  const automation = mode === "automation";

  return (
    <LinearGradient colors={[C.bgTop, C.bgBot]} style={{ flex: 1 }}>
      <SafeAreaView style={{ flex: 1 }} edges={["top"]}>
        <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 40 }} showsVerticalScrollIndicator={false}>
          <View style={s.hero}>
            <Image source={require("../../assets/logo.png")} style={s.avatar} />
            <Text style={s.name}>Hi {name}</Text>
            <Text style={s.email}>Sarthi · your personal AI</Text>
            <View style={[s.pill, { backgroundColor: status === "connected" ? C.okBg : C.dangerBg }]}>
              <View style={[s.dot, { backgroundColor: status === "connected" ? C.ok : C.danger }]} />
              <Text style={[s.pillTxt, { color: status === "connected" ? C.ok : C.danger }]}>Backend {status}</Text>
            </View>
          </View>

          <Text style={s.section}>MODE</Text>
          <Card>
            <View style={s.rowBetween}>
              <View style={{ flex: 1, paddingRight: 12 }}>
                <Text style={s.rowTitle}>{automation ? "Automation" : "PC Control"}</Text>
                <Text style={s.rowSub}>
                  {automation
                    ? "Sarthi handles Gmail, Calendar & Drive silently in the background — with your approval before sending."
                    : "Sarthi operates your PC directly — opening apps, clicking, and typing."}
                </Text>
              </View>
              <Switch value={automation} onValueChange={toggleMode} trackColor={{ true: C.blue2, false: "#D3DBE6" }} thumbColor="#fff" />
            </View>
          </Card>

          <Text style={s.section}>AI MODEL (PC BRAIN)</Text>
          <Card>
            <Text style={s.rowSub}>
              How your PC's Sarthi thinks. Local keeps everything on the PC; API uses your own key.
              Image, PDF & memory stay on-device either way.
            </Text>
            <View style={s.chipRow}>
              {[["local", "Local · private"], ["api", "API key"]].map(([m, lbl]) => (
                <TouchableOpacity key={m} style={[s.chip, brainMode === m && s.chipOn]} onPress={() => setBrainMode(m)}>
                  <Text style={[s.chipTxt, brainMode === m && s.chipTxtOn]}>{lbl}</Text>
                </TouchableOpacity>
              ))}
            </View>

            {brainMode === "local" ? (
              <>
                <Text style={[s.rowSub, { marginTop: 14, fontWeight: "700", color: C.ink }]}>Model on your PC</Text>
                <View style={s.chipRow}>
                  {localModels.length ? (
                    localModels.map((m) => (
                      <TouchableOpacity key={m} style={[s.chip, brainModel === m && s.chipOn]} onPress={() => setBrainModel(m)}>
                        <Text style={[s.chipTxt, brainModel === m && s.chipTxtOn]}>{m}</Text>
                      </TouchableOpacity>
                    ))
                  ) : (
                    <Text style={s.rowSub}>No PC models found — is the server on?</Text>
                  )}
                </View>
              </>
            ) : (
              <>
                <Text style={[s.rowSub, { marginTop: 14, fontWeight: "700", color: C.ink }]}>Provider</Text>
                <View style={s.chipRow}>
                  {["openai", "claude", "gemini", "grok"].map((p) => (
                    <TouchableOpacity key={p} style={[s.chip, brainProvider === p && s.chipOn]} onPress={() => setBrainProvider(p)}>
                      <Text style={[s.chipTxt, brainProvider === p && s.chipTxtOn]}>{PROVIDER_LABEL[p]}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
                <TextInput
                  value={brainModelApi}
                  onChangeText={setBrainModelApi}
                  autoCapitalize="none"
                  autoCorrect={false}
                  placeholder="model (optional — blank = default)"
                  placeholderTextColor={C.muted}
                  style={s.input}
                />
                <TextInput
                  value={brainKey}
                  onChangeText={setBrainKey}
                  autoCapitalize="none"
                  autoCorrect={false}
                  secureTextEntry
                  placeholder={apiKeySet ? "key saved · type to replace" : "paste your API key"}
                  placeholderTextColor={C.muted}
                  style={[s.input, { marginTop: 0 }]}
                />
              </>
            )}

            <TouchableOpacity onPress={saveBrain} disabled={brainBusy} activeOpacity={0.85} style={{ marginTop: 4 }}>
              <LinearGradient colors={C.micGrad} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={s.saveBtn}>
                <Text style={s.saveTxt}>{brainBusy ? "Saving…" : "Save"}</Text>
              </LinearGradient>
            </TouchableOpacity>
            {!!brainStatus && <Text style={[s.rowSub, { marginTop: 10, textAlign: "center" }]}>{brainStatus}</Text>}
          </Card>

          <Text style={s.section}>CONNECTIONS</Text>
          <Card>
            <View style={s.rowBetween}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 10, flex: 1 }}>
                <View style={[s.gIcon]}>
                  <Ionicons name="logo-google" size={18} color={C.blue} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={s.rowTitle}>Google</Text>
                  <Text style={s.rowSub}>{gEmail ? `Connected on this phone · ${gEmail}` : "Connect Gmail, Calendar, Drive & Contacts — right here, no PC needed."}</Text>
                </View>
              </View>
              <Ionicons name={gEmail ? "checkmark-circle" : "ellipse-outline"} size={22} color={gEmail ? C.ok : C.muted} />
            </View>

            {gEmail ? (
              <>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
                  {["Gmail", "Calendar", "Drive", "Contacts"].map((x) => (
                    <View key={x} style={s.svcPill}>
                      <Ionicons name="checkmark" size={13} color={C.ok} />
                      <Text style={s.svcTxt}>{x}</Text>
                    </View>
                  ))}
                </View>
                <TouchableOpacity onPress={disconnectGoogle} style={[s.saveBtn, { backgroundColor: "#fff", borderWidth: 1, borderColor: "#F3D0D0", marginTop: 14 }]}>
                  <Text style={[s.saveTxt, { color: C.danger }]}>Disconnect</Text>
                </TouchableOpacity>
              </>
            ) : (
              <TouchableOpacity onPress={connectGoogle} disabled={!gReq || gBusy} activeOpacity={0.85} style={{ marginTop: 14 }}>
                <LinearGradient colors={C.micGrad} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={s.saveBtn}>
                  <Text style={s.saveTxt}>{gBusy ? "Connecting…" : "Connect Google"}</Text>
                </LinearGradient>
              </TouchableOpacity>
            )}
          </Card>

          <Text style={s.section}>CONNECT TO PC</Text>
          <Card>
            <Text style={s.rowSub}>Tap Find my PC and Sarthi locates your computer on the same Wi-Fi — no typing IPs. Connecting pairs it to your account.</Text>
            <TouchableOpacity onPress={findPCs} activeOpacity={0.85} style={[s.saveBtn, { backgroundColor: "#EEF4FF", marginTop: 14 }]}>
              <Text style={[s.saveTxt, { color: C.blue }]}>Find my PC on Wi-Fi</Text>
            </TouchableOpacity>
            {!!scan && <Text style={[s.rowSub, { marginTop: 10 }]}>{scan}</Text>}

            {pcs.map((pc) => {
              const mine = pc.owner && accountEmail() && pc.owner === accountEmail();
              const here = base === pc.base;
              return (
                <TouchableOpacity key={pc.base} onPress={() => connectPC(pc)} activeOpacity={0.85} style={s.pcRow}>
                  <Ionicons name="desktop-outline" size={20} color={C.blue} />
                  <View style={{ flex: 1 }}>
                    <Text style={s.rowTitle}>{pc.name}{mine ? "  · yours ✓" : ""}</Text>
                    <Text style={s.rowSub}>{pc.base}{pc.owner ? `  · ${pc.owner}` : "  · not paired"}</Text>
                  </View>
                  <Text style={[s.saveTxt, { color: here ? C.ok : C.blue, fontSize: 13 }]}>{here ? "Connected" : "Connect"}</Text>
                </TouchableOpacity>
              );
            })}

            <Text style={[s.rowSub, { marginTop: 16, fontWeight: "700", color: C.ink }]}>Or enter the address manually</Text>
            <TextInput
              value={base}
              onChangeText={setBaseState}
              autoCapitalize="none"
              autoCorrect={false}
              placeholder="http://192.168.x.x:8760"
              placeholderTextColor={C.muted}
              style={s.input}
            />
            <TouchableOpacity onPress={saveServer} activeOpacity={0.85}>
              <LinearGradient colors={C.micGrad} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={s.saveBtn}>
                <Text style={s.saveTxt}>Save & test</Text>
              </LinearGradient>
            </TouchableOpacity>
          </Card>

          <Text style={s.section}>DEVICE CONTROL</Text>
          <Card>
            <View style={s.rowBetween}>
              <View style={{ flex: 1, paddingRight: 12 }}>
                <Text style={s.rowTitle}>In-app automation</Text>
                <Text style={s.rowSub}>Let Sarthi open apps and tap/type inside them (WhatsApp, PhonePe…). You approve any send or payment.</Text>
              </View>
              <Ionicons name={agentOn ? "checkmark-circle" : "ellipse-outline"} size={22} color={agentOn ? C.ok : C.muted} />
            </View>
            <View style={[s.rowBetween, { marginTop: 14, paddingTop: 12, borderTopWidth: 1, borderTopColor: C.line }]}>
              <View style={{ flex: 1, paddingRight: 12 }}>
                <Text style={s.rowTitle}>Floating assistant</Text>
                <Text style={s.rowSub}>A voice bubble on top of every app. Tap to talk, double-tap to close. Also keeps Sarthi running during a task.</Text>
              </View>
              <Switch value={floating} onValueChange={toggleFloating} trackColor={{ true: C.blue2, false: "#D3DBE6" }} thumbColor="#fff" />
            </View>
            <Text style={[s.rowSub, { marginTop: 12 }]}>Native module: {hasAgent ? "found ✓" : "missing ✗"}</Text>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 14 }}>
              <TouchableOpacity onPress={openAccessibilitySettings} style={[s.saveBtn, { flex: 1, backgroundColor: "#fff", borderWidth: 1, borderColor: C.line }]}>
                <Text style={[s.saveTxt, { color: C.blue }]}>Enable in settings</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={doProbe} style={[s.saveBtn, { paddingHorizontal: 22, backgroundColor: "#EEF4FF" }]}>
                <Text style={[s.saveTxt, { color: C.blue }]}>Test</Text>
              </TouchableOpacity>
            </View>
          </Card>

          <Text style={s.section}>OFFLINE BRAIN</Text>
          <Card>
            <View style={s.rowBetween}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 10, flex: 1, paddingRight: 10 }}>
                <View style={[s.gIcon, { backgroundColor: "#EDEBFF" }]}>
                  <Ionicons name="hardware-chip-outline" size={18} color="#6b5bff" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={s.rowTitle}>On-device model</Text>
                  <Text style={s.rowSub}>
                    {dl != null
                      ? `Downloading… ${Math.round(dl * 100)}%`
                      : model.exists
                      ? `Ready · ${mb(model.size)} MB · works with PC off`
                      : `Qwen 1.5B · ~${MODEL.sizeMB} MB one-time download`}
                  </Text>
                </View>
              </View>
              {model.exists && dl == null && (
                <Ionicons name="checkmark-circle" size={22} color={C.ok} />
              )}
            </View>

            {dl != null && (
              <View style={s.track}>
                <View style={[s.fill, { width: `${Math.round(dl * 100)}%` }]} />
              </View>
            )}

            {dl == null &&
              (model.exists ? (
                <TouchableOpacity onPress={doDelete} style={[s.saveBtn, { backgroundColor: "#fff", borderWidth: 1, borderColor: "#F3D0D0", marginTop: 14 }]}>
                  <Text style={[s.saveTxt, { color: C.danger }]}>Delete model</Text>
                </TouchableOpacity>
              ) : (
                <TouchableOpacity onPress={doDownload} activeOpacity={0.85} style={{ marginTop: 14 }}>
                  <LinearGradient colors={["#7b6bff", "#5b4bff"]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={s.saveBtn}>
                    <Text style={s.saveTxt}>Download for offline</Text>
                  </LinearGradient>
                </TouchableOpacity>
              ))}
          </Card>

          <TouchableOpacity onPress={signOut} activeOpacity={0.85} style={[s.saveBtn, { backgroundColor: "#fff", borderWidth: 1, borderColor: "#F3D0D0", marginTop: 24 }]}>
            <Text style={[s.saveTxt, { color: C.danger }]}>Sign out{accountEmail() ? ` · ${accountEmail()}` : ""}</Text>
          </TouchableOpacity>
          <Text style={s.about}>Sarthi mobile · online uses your PC brain, offline uses the on-device model</Text>
        </ScrollView>
      </SafeAreaView>
    </LinearGradient>
  );
}

const s = StyleSheet.create({
  hero: { alignItems: "center", marginBottom: 8 },
  avatar: { width: 76, height: 76, borderRadius: 22, backgroundColor: "#fff", marginBottom: 12 },
  name: { fontSize: 22, fontWeight: "800", color: C.ink },
  email: { fontSize: 13, color: C.muted, marginTop: 3 },
  pill: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 6, borderRadius: R.pill, marginTop: 12 },
  dot: { width: 7, height: 7, borderRadius: 4 },
  pillTxt: { fontSize: 12, fontWeight: "700" },
  section: { fontSize: 11, fontWeight: "800", color: C.muted, letterSpacing: 0.8, marginTop: 24, marginBottom: 10, marginLeft: 4 },
  card: { backgroundColor: "#fff", borderRadius: R.lg, padding: 16, borderWidth: 1, borderColor: C.line },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  rowTitle: { fontSize: 15.5, fontWeight: "800", color: C.ink, marginBottom: 3 },
  rowSub: { fontSize: 12.5, color: C.ink2, lineHeight: 18 },
  gIcon: { width: 40, height: 40, borderRadius: 12, backgroundColor: "#EEF4FF", alignItems: "center", justifyContent: "center" },
  input: { borderWidth: 1, borderColor: C.line, borderRadius: R.md, paddingHorizontal: 14, paddingVertical: 11, fontSize: 14.5, color: C.ink, marginTop: 12, marginBottom: 12, backgroundColor: "#F8FBFF" },
  saveBtn: { paddingVertical: 12, borderRadius: R.md, alignItems: "center" },
  saveTxt: { color: "#fff", fontWeight: "800", fontSize: 14.5 },
  svcPill: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: C.okBg, paddingHorizontal: 11, paddingVertical: 6, borderRadius: R.pill },
  svcTxt: { color: C.ok, fontWeight: "700", fontSize: 12 },
  track: { height: 8, borderRadius: 4, backgroundColor: "#ECECFB", marginTop: 14, overflow: "hidden" },
  fill: { height: 8, borderRadius: 4, backgroundColor: "#6b5bff" },
  about: { textAlign: "center", color: C.muted, fontSize: 12, marginTop: 26 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 10 },
  chip: { paddingHorizontal: 14, paddingVertical: 9, borderRadius: R.pill, borderWidth: 1, borderColor: C.line, backgroundColor: "#fff" },
  chipOn: { borderColor: C.blue, backgroundColor: "#EEF4FF" },
  chipTxt: { fontSize: 13, fontWeight: "700", color: C.ink2 },
  chipTxtOn: { color: C.blue },
  pcRow: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 12, paddingTop: 12, borderTopWidth: 1, borderTopColor: C.line },
});
