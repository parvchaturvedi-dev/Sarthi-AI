// Hero / welcome — the middle phone in the reference. Big mascot, a hello
// bubble, and the voice-first mic. Enter the app from here.
import React from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import Mascot from "../components/Mascot";
import MicButton from "../components/MicButton";
import { C, R, shadow } from "../../lib/theme";

export default function SplashScreen({ navigation }) {
  const go = (screen) => navigation.replace("Main", { screen });

  return (
    <LinearGradient colors={[C.bgTop, C.bgBot]} style={{ flex: 1 }}>
      <SafeAreaView style={{ flex: 1 }}>
        <View style={s.top}>
          <View style={{ width: 40 }} />
          <TouchableOpacity onPress={() => go("Home")} style={s.skip}>
            <Text style={s.skipTxt}>Skip</Text>
          </TouchableOpacity>
        </View>

        <View style={s.headline}>
          <Text style={s.h1}>
            Your <Text style={{ color: C.blue }}>Smart{"\n"}Assistant</Text> for{"\n"}Daily Tasks
          </Text>
        </View>

        <View style={s.stage}>
          <View style={[s.bubble, shadow(8)]}>
            <Text style={s.bubbleTxt}>Hi! I'm Sarthi 👋{"\n"}Here to help you</Text>
          </View>
          <Mascot size={196} />
        </View>

        <View style={s.dock}>
          <TouchableOpacity style={s.round} onPress={() => go("Chat")}>
            <Ionicons name="chatbubble-ellipses-outline" size={22} color={C.ink2} />
          </TouchableOpacity>
          <MicButton size={74} active onPress={() => go("Chat")} />
          <TouchableOpacity style={s.round} onPress={() => go("Home")}>
            <Ionicons name="grid-outline" size={22} color={C.ink2} />
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    </LinearGradient>
  );
}

const s = StyleSheet.create({
  top: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: 20, paddingTop: 6 },
  skip: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: R.pill, backgroundColor: "#FFFFFFAA" },
  skipTxt: { color: C.ink2, fontWeight: "700", fontSize: 13 },
  headline: { alignItems: "center", marginTop: 8 },
  h1: { fontSize: 30, lineHeight: 38, fontWeight: "800", color: C.ink, textAlign: "center", letterSpacing: -0.5 },
  stage: { flex: 1, alignItems: "center", justifyContent: "center" },
  bubble: { backgroundColor: "#fff", borderRadius: R.lg, borderTopRightRadius: 6, paddingVertical: 12, paddingHorizontal: 16, marginBottom: -6, borderWidth: 1, borderColor: C.line },
  bubbleTxt: { color: C.ink, fontSize: 14.5, fontWeight: "600", lineHeight: 20, textAlign: "center" },
  dock: { flexDirection: "row", alignItems: "center", justifyContent: "space-around", paddingHorizontal: 34, paddingBottom: 18 },
  round: { width: 48, height: 48, borderRadius: 24, backgroundColor: "#fff", alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: C.line },
});
