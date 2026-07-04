// JS side of the on-device accessibility agent (native module SarthiAgent).
// Only present in the custom dev build; guards keep it safe if absent.
import { NativeModules, Platform } from "react-native";

const A = NativeModules.SarthiAgent;
export const hasAgent = Platform.OS === "android" && !!A;

export async function agentEnabled() {
  try { return await A.isEnabled(); } catch { return false; }
}

// Diagnostic: reports exactly where in-app control breaks.
export async function probe() {
  const out = { hasAgent, enabled: false, count: -1, error: null };
  if (!A) { out.error = "native module SarthiAgent NOT found in this build"; return out; }
  try { out.enabled = await A.isEnabled(); } catch (e) { out.error = "isEnabled: " + (e.message || e.code); return out; }
  try { const s = JSON.parse(await A.readScreen()); out.count = Array.isArray(s) ? s.length : -1; }
  catch (e) { out.error = "readScreen: " + (e.message || e.code || String(e)); }
  return out;
}
export function openAccessibilitySettings() {
  try { A.openAccessibilitySettings(); } catch {}
}
export async function launchApp(pkg) {
  try { return await A.launchApp(pkg); } catch { return false; }
}
export async function readScreen() {
  try { return JSON.parse(await A.readScreen()); } catch { return []; }
}
export async function tapText(text) {
  try { return await A.tapText(text); } catch { return false; }
}
export async function typeText(text) {
  try { return await A.typeText(text); } catch { return false; }
}
export async function back() {
  try { return await A.back(); } catch { return false; }
}
export async function scroll(forward = true) {
  try { return await A.scroll(forward); } catch { return false; }
}

// --- floating overlay + keep-alive foreground service ---
let _persistent = false;
export function isOverlayPersistent() { return _persistent; }
export function setOverlayPersistent(v) { _persistent = v; }

export async function canDrawOverlays() {
  try { return await A.canDrawOverlays(); } catch { return false; }
}
export function requestOverlayPermission() { try { A.requestOverlayPermission(); } catch {} }
export function startOverlay() { try { A.startOverlay(); } catch {} }
export function stopOverlay() { try { A.stopOverlay(); } catch {} }
