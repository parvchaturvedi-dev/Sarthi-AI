// Speech output. Online → play the PC's natural edge-tts voice (matches the
// desktop accent). Offline → device TTS with the best available voice.
import { createAudioPlayer } from "expo-audio";
import * as Speech from "expo-speech";
import { getBase } from "./api";

let player = null;
let doneTimer = null;
let bestVoice = undefined;

// Pick a natural-sounding device voice once (used offline). Prefers Indian
// English / Hindi network (higher quality) voices.
export async function pickVoice() {
  try {
    const vs = await Speech.getAvailableVoicesAsync();
    const score = (v) => {
      const lang = (v.language || "").toLowerCase();
      const q = String(v.quality || "").toLowerCase();
      let s = 0;
      if (lang.startsWith("en-in") || lang.startsWith("hi-in")) s += 4;
      else if (lang.startsWith("en")) s += 1;
      if (q.includes("enhanced") || /network|neural/i.test(v.identifier || "")) s += 2;
      return s;
    };
    const best = (vs || []).slice().sort((a, b) => score(b) - score(a))[0];
    if (best && score(best) > 0) bestVoice = best.identifier;
  } catch {}
}

function clearTimer() {
  if (doneTimer) { clearTimeout(doneTimer); doneTimer = null; }
}

export function stopVoice() {
  clearTimer();
  try { Speech.stop(); } catch {}
  try { if (player) { player.pause(); player.remove?.(); } } catch {}
  player = null;
}

// speakText(text, online, onDone). onDone fires when playback finishes/stops.
export function speakText(text, online, onDone) {
  stopVoice();
  const t = (text || "").trim();
  if (!t) { onDone?.(); return; }

  const finish = () => { clearTimer(); onDone?.(); };
  // safety timer so the "speaking" state always clears even if events are missed
  const guardMs = Math.min(60000, t.length * 90 + 4000);

  if (online) {
    try {
      const uri = getBase() + "/api/tts?text=" + encodeURIComponent(t.slice(0, 900));
      player = createAudioPlayer({ uri });
      player.play();
      try {
        player.addListener("playbackStatusUpdate", (st) => {
          if (st?.didJustFinish) finish();
        });
      } catch {}
      doneTimer = setTimeout(finish, guardMs);
      return;
    } catch {
      // fall through to device TTS
    }
  }
  Speech.speak(t, {
    voice: bestVoice, rate: 1.0, pitch: 1.0,
    onDone: finish, onStopped: finish, onError: finish,
  });
  doneTimer = setTimeout(finish, guardMs);
}
