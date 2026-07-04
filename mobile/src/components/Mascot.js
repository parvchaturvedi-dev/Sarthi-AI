// Sarthi mascot — a friendly little robot, drawn with SVG so it scales crisply.
import React from "react";
import { View } from "react-native";
import Svg, { Defs, LinearGradient, Stop, Rect, Circle, Path, G, Ellipse } from "react-native-svg";
import { C } from "../../lib/theme";

export default function Mascot({ size = 180 }) {
  const w = size;
  const h = size * 1.05;
  return (
    <View style={{ width: w, height: h }}>
      <Svg width={w} height={h} viewBox="0 0 200 210">
        <Defs>
          <LinearGradient id="body" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor="#FFFFFF" />
            <Stop offset="1" stopColor="#EAF1FB" />
          </LinearGradient>
          <LinearGradient id="glow" x1="0" y1="0" x2="1" y2="1">
            <Stop offset="0" stopColor={C.blue2} />
            <Stop offset="1" stopColor={C.blue} />
          </LinearGradient>
        </Defs>

        {/* soft shadow */}
        <Ellipse cx="100" cy="196" rx="52" ry="10" fill="#Bcd3f0" opacity="0.5" />

        {/* antenna */}
        <Path d="M100 30 L100 14" stroke={C.blue} strokeWidth="4" strokeLinecap="round" />
        <Circle cx="100" cy="10" r="6" fill="url(#glow)" />

        {/* head */}
        <Rect x="46" y="30" width="108" height="92" rx="34" fill="url(#body)" stroke="#DCE7F6" strokeWidth="2" />
        {/* ears */}
        <Rect x="38" y="60" width="12" height="30" rx="6" fill="url(#glow)" />
        <Rect x="150" y="60" width="12" height="30" rx="6" fill="url(#glow)" />

        {/* face screen */}
        <Rect x="60" y="46" width="80" height="60" rx="26" fill={C.faceDark} />
        {/* happy eyes */}
        <Path d="M78 74 Q84 64 90 74" stroke="#FFFFFF" strokeWidth="5" strokeLinecap="round" fill="none" />
        <Path d="M110 74 Q116 64 122 74" stroke="#FFFFFF" strokeWidth="5" strokeLinecap="round" fill="none" />
        {/* smile */}
        <Path d="M86 88 Q100 98 114 88" stroke="#FFFFFF" strokeWidth="4.5" strokeLinecap="round" fill="none" />
        {/* blush */}
        <Circle cx="72" cy="90" r="5" fill={C.blue2} opacity="0.5" />
        <Circle cx="128" cy="90" r="5" fill={C.blue2} opacity="0.5" />

        {/* body */}
        <Rect x="62" y="120" width="76" height="60" rx="26" fill="url(#body)" stroke="#DCE7F6" strokeWidth="2" />
        <Rect x="86" y="134" width="28" height="18" rx="9" fill="url(#glow)" opacity="0.85" />

        {/* waving arm */}
        <G>
          <Path d="M138 138 Q168 130 166 104" stroke="url(#body)" strokeWidth="14" strokeLinecap="round" fill="none" />
          <Path d="M138 138 Q168 130 166 104" stroke="#DCE7F6" strokeWidth="15" strokeLinecap="round" fill="none" opacity="0.4" />
          <Circle cx="166" cy="100" r="11" fill="url(#body)" stroke="#DCE7F6" strokeWidth="2" />
        </G>
        <Path d="M62 142 Q42 148 44 168" stroke="url(#body)" strokeWidth="14" strokeLinecap="round" fill="none" />
        <Circle cx="44" cy="172" r="10" fill="url(#body)" stroke="#DCE7F6" strokeWidth="2" />
      </Svg>
    </View>
  );
}
