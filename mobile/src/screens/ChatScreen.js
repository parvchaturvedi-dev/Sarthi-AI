// Chat — bubbles, inline approval cards, device-action cards, TTS read-aloud,
// and REAL voice input (record -> whisper on the PC backend). Serves both the
// "Sarthi" assistant mode and the "Control Your Device" mode.
import React, { useEffect, useRef, useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity, FlatList, StyleSheet,
  KeyboardAvoidingView, Platform, ActivityIndicator, Alert,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useAudioRecorder, AudioModule, RecordingPresets, setAudioModeAsync } from "expo-audio";
import { C, R, shadow } from "../../lib/theme";
import { chat, devicePlan, transcribe, ensureAuth, isOnline, getSession, stopSpeaking } from "../../lib/api";
import { offlineChat, offlinePlanDevice, isSearchQuery, offlineSearch } from "../../lib/offline";
import { speakText, stopVoice, pickVoice } from "../../lib/voice";
import { hasAgent, agentEnabled, openAccessibilitySettings } from "../../lib/agent";
import { isOperateGoal, isDeviceCommand, runOperate } from "../../lib/operate";
import ApprovalCard from "../components/ApprovalCard";
import DeviceActionCard from "../components/DeviceActionCard";
import MicButton from "../components/MicButton";

let idc = 0;
const uid = () => `m${++idc}`;

export default function ChatScreen({ navigation, route }) {
  // mode: "sarthi" (chat, mobile-only sound) | "pc" (Control PC, sound on both) | "device" (Control this phone)
  const mode = route.params?.mode || "sarthi";
  const device = mode === "device";
  const pcCtrl = mode === "pc";
  const [msgs, setMsgs] = useState([
    {
      id: uid(), role: "bot",
      text: device
        ? "Tell me what to do on your phone — e.g. “open YouTube”, “WhatsApp 98xxxx I'm running late”, or “navigate to the airport”. I'll show you each action before it runs."
        : pcCtrl
        ? "Control your PC from here — e.g. “open Notepad”, “search the web for…”, “send a mail”. The PC will speak too so you get feedback at the machine."
        : "Hi! I'm Sarthi. Ask me anything, or tell me a task — I'll always show you a draft before sending or acting.",
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [speakOn, setSpeakOn] = useState(true);
  const [recording, setRecording] = useState(false);
  const [net, setNet] = useState(null); // "online" | "offline"
  const [confirmReq, setConfirmReq] = useState(null); // {label} — operate send/pay approval
  const sid = useRef(null);
  const cancelled = useRef(false);
  const confirmResolver = useRef(null);
  const listRef = useRef(null);
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);

  useEffect(() => { ensureAuth(); pickVoice(); }, []);

  useEffect(() => {
    const p = route.params?.prefill;
    if (p) setInput(p);
    if (route.params?.voice) setTimeout(startRec, 400);
    if (route.params?.sessionId) loadSession(route.params.sessionId);
  }, [route.params]);

  const scroll = () => setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 80);
  const botMsg = (text) => setMsgs((m) => [...m, { id: uid(), role: "bot", text }]);

  async function loadSession(id) {
    try {
      const d = await getSession(id);
      sid.current = id;
      const turns = (d.turns || []).map((t) => ({ id: uid(), role: t.role === "user" ? "user" : "bot", text: t.content }));
      if (turns.length) setMsgs(turns);
      scroll();
    } catch {}
  }

  function speak(t, online) {
    if (!speakOn || !t) { setSpeaking(false); return; }
    setSpeaking(true);
    speakText(t, !!online, () => setSpeaking(false));
  }

  // Stop the current response: cut TTS (phone + PC) and drop the in-flight reply.
  function stop() {
    cancelled.current = true;
    stopVoice();
    setSpeaking(false);
    if (pcCtrl || (!device && net === "online")) stopSpeaking(); // silence the PC too
    setBusy(false);
  }

  async function send(textArg) {
    const text = (textArg ?? input).trim();
    if (!text || busy) return;
    cancelled.current = false;
    setInput("");
    setMsgs((m) => [...m, { id: uid(), role: "user", text }]);
    setBusy(true);
    scroll();
    try {
      const online = await isOnline();
      setNet(online ? "online" : "offline");
      // route phone commands to the device path from ANY mode (except Control-PC)
      const deviceCmd = device || (!pcCtrl && isDeviceCommand(text));
      if (deviceCmd) {
        if (isOperateGoal(text)) {
          // full in-app automation via the accessibility agent
          if (!hasAgent) {
            botMsg("⚠ In-app control module isn't in this build. Reinstall the latest APK, then check Profile → Device control → Test.");
          } else {
            const enabled = await agentEnabled();
            if (!enabled) {
              botMsg("To act inside apps I need the accessibility service ON. Opening Settings — turn on “Sarthi Device Control”, then ask me again.");
              openAccessibilitySettings();
            } else {
              await runOperate(text, {
                onStep: (t) => botMsg(t),
                onConfirm: (label) => new Promise((res) => { confirmResolver.current = res; setConfirmReq({ label }); }),
                shouldStop: () => cancelled.current,
              });
            }
          }
        } else {
          const d = online ? await devicePlan(text) : await offlinePlanDevice(text);
          if (cancelled.current) return;
          const add = [{ id: uid(), role: "bot", text: d.reply || "Okay." }];
          if (d.action) add.push({ id: uid(), role: "device", action: d.action });
          setMsgs((m) => [...m, ...add]);
          speak(d.reply, online);
        }
      } else if (online) {
        const d = await chat(text, sid.current, pcCtrl); // speak on PC only in Control-PC mode
        if (cancelled.current) return;
        sid.current = d.session_id ?? sid.current;
        const replies = d.replies?.length ? d.replies : ["(no response)"];
        const add = replies.map((r) => ({ id: uid(), role: "bot", text: r }));
        if (d.pending) add.push({ id: uid(), role: "pending", action: d.pending });
        setMsgs((m) => [...m, ...add]);
        speak(replies.join(". "), true);
      } else {
        // offline (PC unreachable): live web search if the phone has internet, else the on-device model
        let reply = null;
        if (isSearchQuery(text)) reply = await offlineSearch(text);
        if (!reply) reply = await offlineChat(text);
        if (cancelled.current) return;
        botMsg(reply || "…");
        speak(reply, false);
      }
    } catch (e) {
      if (!cancelled.current)
        botMsg(`⚠ ${e.message}\n\nOnline needs the PC backend + matching Server URL. Offline needs the on-device model (Profile → Offline brain).`);
    } finally {
      setBusy(false);
      scroll();
    }
  }

  async function startRec() {
    try {
      const perm = await AudioModule.requestRecordingPermissionsAsync();
      if (!perm.granted) {
        Alert.alert("Microphone needed", "Allow mic access to talk to Sarthi.");
        return;
      }
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
      setRecording(true);
    } catch (e) {
      botMsg("Couldn't start recording: " + e.message);
    }
  }

  async function stopRec() {
    setRecording(false);
    setBusy(true);
    try {
      await recorder.stop();
      const uri = recorder.uri;
      if (!uri) throw new Error("No audio captured");
      const text = await transcribe(uri);
      if (text && text.trim()) {
        setBusy(false);
        send(text.trim());
      } else {
        setBusy(false);
        botMsg("Didn't catch that — tap the mic and try again.");
      }
    } catch (e) {
      setBusy(false);
      botMsg("Voice failed: " + e.message + "\n(Make sure the PC backend is running — it does the transcription.)");
    }
  }

  const onMic = () => (recording ? stopRec() : startRec());

  const renderItem = ({ item }) => {
    if (item.role === "pending")
      return <View style={[s.line, { alignItems: "flex-start" }]}><ApprovalCard action={item.action} /></View>;
    if (item.role === "device")
      return <View style={[s.line, { alignItems: "flex-start" }]}><DeviceActionCard action={item.action} /></View>;
    const mine = item.role === "user";
    return (
      <View style={[s.line, { alignItems: mine ? "flex-end" : "flex-start" }]}>
        {mine ? (
          <LinearGradient colors={C.userGrad} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={[s.bubble, s.userBubble]}>
            <Text style={s.userTxt}>{item.text}</Text>
          </LinearGradient>
        ) : (
          <View style={[s.bubble, s.botBubble]}><Text style={s.botTxt}>{item.text}</Text></View>
        )}
      </View>
    );
  };

  return (
    <LinearGradient colors={[C.bgTop, C.bgBot]} style={{ flex: 1 }}>
      <SafeAreaView style={{ flex: 1 }} edges={["top"]}>
        <View style={s.header}>
          <TouchableOpacity onPress={() => navigation.navigate("Home")} style={s.hIcon}>
            <Ionicons name="chevron-back" size={22} color={C.ink} />
          </TouchableOpacity>
          <View style={{ alignItems: "center" }}>
            <Text style={s.hTitle}>{device ? "Control Device" : pcCtrl ? "Control PC" : "Sarthi AI"}</Text>
            <Text style={[s.hSub, net === "offline" && { color: C.muted }]}>
              {recording ? "listening…" : busy ? "thinking…" : net === "offline" ? "offline · on-device" : net === "online" ? "online · PC brain" : "ready"}
            </Text>
          </View>
          <TouchableOpacity onPress={() => setSpeakOn((v) => !v)} style={s.hIcon}>
            <Ionicons name={speakOn ? "volume-high" : "volume-mute"} size={20} color={speakOn ? C.blue : C.muted} />
          </TouchableOpacity>
        </View>

        <FlatList
          ref={listRef}
          data={msgs}
          keyExtractor={(m) => m.id}
          renderItem={renderItem}
          contentContainerStyle={{ padding: 16, paddingBottom: 8 }}
          onContentSizeChange={scroll}
          showsVerticalScrollIndicator={false}
        />

        {(busy || recording || speaking) && (
          <View style={s.typing}>
            {recording ? <Ionicons name="mic" size={16} color={C.danger} /> : speaking ? <Ionicons name="volume-high" size={16} color={C.blue} /> : <ActivityIndicator size="small" color={C.blue} />}
            <Text style={s.typingTxt}>{recording ? "Listening — tap the mic to stop" : speaking ? "Speaking — tap ■ to stop" : "Working — tap ■ to stop"}</Text>
          </View>
        )}

        {confirmReq && (
          <View style={s.confirmBar}>
            <Text style={s.confirmTxt}>{confirmReq.label}</Text>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <TouchableOpacity onPress={() => { confirmResolver.current?.(true); setConfirmReq(null); }} style={s.confirmYes}>
                <Text style={s.confirmYesTxt}>Approve</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => { confirmResolver.current?.(false); setConfirmReq(null); }} style={s.confirmNo}>
                <Text style={s.confirmNoTxt}>Reject</Text>
              </TouchableOpacity>
            </View>
          </View>
        )}

        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={[s.composer, shadow(10)]}>
            <TextInput
              style={s.input}
              placeholder={device ? "Tell Sarthi what to do…" : "Message Sarthi…"}
              placeholderTextColor={C.muted}
              value={input}
              onChangeText={setInput}
              multiline
              onSubmitEditing={() => send()}
            />
            {busy || speaking ? (
              <TouchableOpacity onPress={stop} activeOpacity={0.85}>
                <View style={[s.sendBtn, { backgroundColor: C.danger }]}>
                  <Ionicons name="stop" size={20} color="#fff" />
                </View>
              </TouchableOpacity>
            ) : input.trim() ? (
              <TouchableOpacity onPress={() => send()} activeOpacity={0.85}>
                <LinearGradient colors={C.micGrad} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={s.sendBtn}>
                  <Ionicons name="arrow-up" size={22} color="#fff" />
                </LinearGradient>
              </TouchableOpacity>
            ) : (
              <View style={{ marginRight: -6 }}>
                <MicButton size={46} onPress={onMic} active={recording} />
              </View>
            )}
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </LinearGradient>
  );
}

const s = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 14, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: C.line },
  hIcon: { width: 40, height: 40, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: "#fff", borderWidth: 1, borderColor: C.line },
  hTitle: { fontSize: 16, fontWeight: "800", color: C.ink },
  hSub: { fontSize: 11.5, color: C.ok, fontWeight: "600" },
  line: { marginBottom: 12, width: "100%" },
  bubble: { maxWidth: "82%", paddingVertical: 11, paddingHorizontal: 15, borderRadius: R.lg },
  userBubble: { borderTopRightRadius: 6 },
  botBubble: { backgroundColor: C.botBubble, borderTopLeftRadius: 6 },
  userTxt: { color: "#fff", fontSize: 15, lineHeight: 21 },
  botTxt: { color: C.ink, fontSize: 15, lineHeight: 21 },
  typing: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 20, paddingBottom: 6 },
  typingTxt: { color: C.muted, fontSize: 12.5 },
  composer: { flexDirection: "row", alignItems: "flex-end", gap: 10, backgroundColor: "#fff", margin: 12, marginTop: 4, padding: 8, paddingLeft: 16, borderRadius: R.xl, borderWidth: 1, borderColor: C.line },
  input: { flex: 1, fontSize: 15, color: C.ink, maxHeight: 120, paddingVertical: 8 },
  sendBtn: { width: 46, height: 46, borderRadius: 23, alignItems: "center", justifyContent: "center" },
  confirmBar: { marginHorizontal: 12, marginBottom: 4, padding: 12, borderRadius: R.md, backgroundColor: "#FFF7E6", borderWidth: 1, borderColor: "#F5D98B", gap: 10 },
  confirmTxt: { color: "#8A5A00", fontSize: 13.5, fontWeight: "600" },
  confirmYes: { flex: 1, backgroundColor: C.ok, paddingVertical: 10, borderRadius: 10, alignItems: "center" },
  confirmYesTxt: { color: "#fff", fontWeight: "800", fontSize: 13.5 },
  confirmNo: { paddingVertical: 10, paddingHorizontal: 18, borderRadius: 10, borderWidth: 1, borderColor: "#EAD0D0", backgroundColor: "#fff", alignItems: "center" },
  confirmNoTxt: { color: C.danger, fontWeight: "700", fontSize: 13.5 },
});
