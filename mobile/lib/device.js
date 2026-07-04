// Executes a device action on the phone via Android intents / URL schemes.
// This is the real (Expo Go-safe) layer of "Control Your Device": open apps,
// dial, message, navigate, search. Full in-app screen tapping needs a native
// Accessibility build (phase 2).
import { Linking, Platform } from "react-native";
import * as IntentLauncher from "expo-intent-launcher";
import { launchApp as nativeLaunch, hasAgent } from "./agent";

// Package names — native launch by package is the most reliable "open app".
const PKG = {
  whatsapp: "com.whatsapp", youtube: "com.google.android.youtube",
  instagram: "com.instagram.android", maps: "com.google.android.apps.maps",
  chrome: "com.android.chrome", google: "com.google.android.googlequicksearchbox",
  gmail: "com.google.android.gm", spotify: "com.spotify.music",
  phonepe: "com.phonepe.app", paytm: "net.one97.paytm",
  gpay: "com.google.android.apps.nbu.paisa.user", facebook: "com.facebook.katana",
  telegram: "org.telegram.messenger", playstore: "com.android.vending",
};

const enc = encodeURIComponent;

// app -> primary scheme (with a web/store fallback where useful)
const APP_SCHEME = {
  whatsapp: "whatsapp://send",
  youtube: "vnd.youtube://",
  instagram: "instagram://app",
  maps: "geo:0,0",
  chrome: "googlechrome://",
  gmail: "googlegmail://",
  spotify: "spotify://",
  playstore: "market://",
  facebook: "fb://",
  telegram: "tg://",
  twitter: "twitter://",
  linkedin: "linkedin://",
  phone: "tel:",
};
const APP_WEB = {
  whatsapp: "https://web.whatsapp.com",
  youtube: "https://www.youtube.com",
  instagram: "https://instagram.com",
  maps: "https://maps.google.com",
  chrome: "https://www.google.com",
  gmail: "https://mail.google.com",
  spotify: "https://open.spotify.com",
  playstore: "https://play.google.com",
  facebook: "https://facebook.com",
  twitter: "https://twitter.com",
  linkedin: "https://linkedin.com",
};

async function open(url, fallback) {
  try {
    await Linking.openURL(url);
    return true;
  } catch (e) {
    if (fallback) {
      await Linking.openURL(fallback);
      return true;
    }
    throw e;
  }
}

// A short, human label for what an action will do (shown on the card button).
export function actionLabel(a) {
  switch (a?.kind) {
    case "open_app": return `Open ${cap(a.app)}`;
    case "call": return `Call ${a.number || ""}`.trim();
    case "sms": return `Message ${a.number || ""}`.trim();
    case "whatsapp": return `WhatsApp ${a.number || "chat"}`.trim();
    case "maps": return `Navigate: ${a.query || ""}`.trim();
    case "web": return `Search: ${a.query || a.url || ""}`.trim();
    case "youtube": return a.query ? `YouTube: ${a.query}` : "Open YouTube";
    case "email": return `Email ${a.to || ""}`.trim();
    default: return "Do it";
  }
}

// Outward actions we treat as needing an explicit OK (message/call/email).
export const NEEDS_OK = new Set(["call", "sms", "whatsapp", "email"]);

export async function executeDeviceAction(a) {
  if (!a || !a.kind) throw new Error("No action");
  switch (a.kind) {
    case "open_app":
      return openApp(a.app);
    case "call":
      return open(`tel:${clean(a.number)}`);
    case "sms": {
      const b = a.body ? `${Platform.OS === "ios" ? "&" : "?"}body=${enc(a.body)}` : "";
      return open(`sms:${clean(a.number)}${b}`);
    }
    case "whatsapp": {
      const phone = clean(a.number);
      const q = [phone ? `phone=${phone}` : "", a.message ? `text=${enc(a.message)}` : ""].filter(Boolean).join("&");
      return open(`whatsapp://send${q ? "?" + q : ""}`, `https://wa.me/${phone}${a.message ? `?text=${enc(a.message)}` : ""}`);
    }
    case "maps":
      return open(`geo:0,0?q=${enc(a.query || "")}`, `https://www.google.com/maps/search/?api=1&query=${enc(a.query || "")}`);
    case "web":
      return open(a.url || `https://www.google.com/search?q=${enc(a.query || "")}`);
    case "youtube":
      return open(a.query ? `https://www.youtube.com/results?search_query=${enc(a.query)}` : "https://www.youtube.com");
    case "email": {
      const q = [a.subject ? `subject=${enc(a.subject)}` : "", a.body ? `body=${enc(a.body)}` : ""].filter(Boolean).join("&");
      return open(`mailto:${a.to || ""}${q ? "?" + q : ""}`);
    }
    default:
      throw new Error(`Unknown action: ${a.kind}`);
  }
}

async function openApp(app) {
  // most reliable: native launch by package (custom build only)
  if (hasAgent && PKG[app]) {
    const ok = await nativeLaunch(PKG[app]);
    if (ok) return true;
  }
  if (Platform.OS === "android") {
    // system apps via intents
    if (app === "camera") return IntentLauncher.startActivityAsync("android.media.action.STILL_IMAGE_CAMERA");
    if (app === "settings") return Linking.openSettings();
    if (app === "photos") return IntentLauncher.startActivityAsync("android.intent.action.VIEW", { type: "image/*" });
    if (app === "files") return IntentLauncher.startActivityAsync("android.intent.action.GET_CONTENT", { type: "*/*" });
  }
  const scheme = APP_SCHEME[app];
  if (scheme) return open(scheme, APP_WEB[app]);
  if (APP_WEB[app]) return open(APP_WEB[app]);
  if (app === "google") return open("https://www.google.com");
  throw new Error(`I don't know how to open ${app} yet.`);
}

const clean = (n) => (n || "").replace(/[^\d+]/g, "");
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
