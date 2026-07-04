// On-phone operate loop: launch an app, then read the screen → decide one
// action → tap/type → repeat, until the goal is done. Uses the PC brain when
// online, the on-device model when offline. Irreversible taps (send/pay)
// pause for the user's approval.
import { launchApp, readScreen, tapText, typeText, back, scroll, startOverlay, stopOverlay, isOverlayPersistent } from "./agent";
import { deviceOperate, isOnline } from "./api";
import { offlineOperateStep } from "./offline";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const APP_PACKAGES = {
  whatsapp: "com.whatsapp",
  phonepe: "com.phonepe.app",
  paytm: "net.one97.paytm",
  gpay: "com.google.android.apps.nbu.paisa.user",
  "google pay": "com.google.android.apps.nbu.paisa.user",
  instagram: "com.instagram.android",
  youtube: "com.google.android.youtube",
  gmail: "com.google.android.gm",
  telegram: "org.telegram.messenger",
  chrome: "com.android.chrome",
  maps: "com.google.android.apps.maps",
  spotify: "com.spotify.music",
};

export function detectApp(goal) {
  const t = (goal || "").toLowerCase();
  for (const name of Object.keys(APP_PACKAGES)) {
    if (t.includes(name)) return { name, pkg: APP_PACKAGES[name] };
  }
  return null;
}

// Does this goal look like an in-app task (needs the operate loop), vs. a
// simple "just open it" (handled by intents)?
// Is this a phone command at all (open an app / call / navigate / operate)?
// Used so device commands work even from the normal chat, not just device mode.
export function isDeviceCommand(t) {
  const s = (t || "").toLowerCase();
  if (detectApp(s)) return true;
  return /\b(open|khol|kholo|launch|call|dial|sms|navigate|directions|maps|camera|settings)\b/.test(s);
}

export function isOperateGoal(goal) {
  const t = (goal || "").toLowerCase();
  if (!detectApp(t)) return false;
  // substring match (no word boundaries) so "bhejo", "karo", "message" etc. all hit
  return /(message|msg|send|bhej|likh|reply|pay|paisa|de do|kar|search|dhoond|dhund|find|call|open kar)/i.test(t);
}

/**
 * runOperate(goal, { onStep, onConfirm })
 *  onStep(text)      → post a status line to the chat
 *  onConfirm(label)  → returns a Promise<boolean> (user approves the send/pay)
 *  shouldStop()      → returns true to abort
 */
export async function runOperate(goal, { onStep, onConfirm, shouldStop } = {}) {
  const app = detectApp(goal);
  if (!app) { onStep?.("I couldn't tell which app to use."); return; }

  // Keep the app process alive (foreground service) so the loop keeps running
  // even after we switch to the other app.
  startOverlay();
  try {
    const online = await isOnline();
    onStep?.(`Opening ${app.name}…`);
    const ok = await launchApp(app.pkg);
    if (!ok) { onStep?.(`I couldn't open ${app.name} — is it installed?`); return; }
    await sleep(2000);

    const history = [];
    let emptyReads = 0;
    for (let i = 0; i < 12; i++) {
    if (shouldStop?.()) { onStep?.("Stopped."); return; }
    const screen = await readScreen();
    if (!screen || screen.length === 0) {
      if (++emptyReads >= 3) {
        onStep?.("I can't read the screen. Check Profile → Device control → Test — the accessibility service may not actually be reading.");
        return;
      }
      await sleep(1200);
      continue;
    }
    emptyReads = 0;
    const step = online
      ? await deviceOperate(goal, screen, history)
      : await offlineOperateStep(goal, screen, history);
    const act = String(step.action || "").toLowerCase();
    if (step.say) onStep?.(step.say);

    if (act === "done") { onStep?.("Done ✅"); return; }
    if (act === "ask") { onStep?.(step.label || "I'm stuck — tell me the next step."); return; }
    if (act === "confirm") {
      const approved = onConfirm ? await onConfirm(step.label || "Confirm this action?") : false;
      if (!approved) { onStep?.("Cancelled — not sent."); return; }
      if (step.text) await tapText(step.text);
      history.push(`confirmed & tapped ${step.text}`);
      await sleep(1400);
      continue;
    }
    if (act === "tap") {
      const done = await tapText(step.text || "");
      history.push(`tap "${step.text}"${done ? "" : " (not found)"}`);
    } else if (act === "type") {
      await typeText(step.text || "");
      history.push(`type "${step.text}"`);
    } else if (act === "scroll") {
      await scroll(true);
      history.push("scroll");
    } else if (act === "back") {
      await back();
      history.push("back");
    } else {
      history.push(`unknown action ${act}`);
    }
      await sleep(1500);
    }
    onStep?.("Stopped after several steps — tell me if it needs more.");
  } finally {
    if (!isOverlayPersistent()) stopOverlay();
  }
}
