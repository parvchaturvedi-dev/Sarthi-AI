// Glowing mic button with a gentle pulse ring. Voice-first centrepiece.
import React, { useEffect, useRef } from "react";
import { Animated, Easing, TouchableOpacity, View, StyleSheet } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import { C, shadow } from "../../lib/theme";

export default function MicButton({ size = 72, onPress, active = false }) {
  const pulse = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 1300, easing: Easing.out(Easing.ease), useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0, duration: 0, useNativeDriver: true }),
      ])
    );
    if (active) loop.start();
    return () => loop.stop();
  }, [active]);

  const ringScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 1.9] });
  const ringOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.45, 0] });

  return (
    <View style={{ alignItems: "center", justifyContent: "center", width: size * 1.9, height: size * 1.9 }}>
      {active && (
        <Animated.View
          style={[
            styles.ring,
            { width: size, height: size, borderRadius: size / 2, transform: [{ scale: ringScale }], opacity: ringOpacity },
          ]}
        />
      )}
      <View style={[styles.halo, { width: size + 16, height: size + 16, borderRadius: (size + 16) / 2 }]} />
      <TouchableOpacity activeOpacity={0.85} onPress={onPress}>
        <LinearGradient
          colors={C.micGrad}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={[styles.btn, { width: size, height: size, borderRadius: size / 2 }, shadow(14, C.blue)]}
        >
          <Ionicons name="mic" size={size * 0.42} color="#fff" />
        </LinearGradient>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  ring: { position: "absolute", backgroundColor: C.blue2 },
  halo: { position: "absolute", backgroundColor: "#DCEBFF" },
  btn: { alignItems: "center", justifyContent: "center" },
});
