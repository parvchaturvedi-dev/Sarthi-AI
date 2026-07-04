// Sarthi mobile — design tokens. Light, friendly, voice-first.
import { Platform } from "react-native";

export const C = {
  bgTop: "#E9F2FF",
  bgBot: "#FDFEFF",
  surface: "#FFFFFF",
  ink: "#141A24",
  ink2: "#586173",
  muted: "#98A2B3",
  line: "#E7EEF7",
  chip: "#FFFFFF",
  blue: "#2E7DF6",
  blue2: "#5AA0FF",
  blueDark: "#1C63D4",
  botBubble: "#F1F5FB",
  userGrad: ["#4C9BFF", "#2B7FFF"],
  micGrad: ["#5AA0FF", "#2E7DF6"],
  faceDark: "#1D2431",
  ok: "#12A18C",
  okBg: "#E4F6F1",
  danger: "#E5484D",
  dangerBg: "#FDECEC",
};

export const shadow = (e = 10, color = "#1B3A6B") =>
  Platform.select({
    ios: {
      shadowColor: color,
      shadowOpacity: 0.14,
      shadowRadius: e,
      shadowOffset: { width: 0, height: e / 2 },
    },
    android: { elevation: e / 1.4 },
    default: {},
  });

export const R = { sm: 10, md: 14, lg: 20, xl: 28, pill: 999 };
