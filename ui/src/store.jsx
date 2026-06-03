// store.jsx — shared context, the model catalog, and demo helpers.
import { createContext, useContext } from "react";

export const StoreCtx = createContext(null);
export const useStore = () => useContext(StoreCtx);

// Canonical model catalog (display metadata). Ids match the Python backend
// (`<backend>/<model>`), so live state can map onto these directly.
export const MODELS = [
  { id: "faster-whisper/turbo", name: "faster-whisper · turbo", provider: "Local", brand: null, local: true, backend: "faster-whisper",
    desc: "Runs on this machine — no key, nothing leaves your device." },
  { id: "openai/gpt-4o-mini-transcribe", name: "gpt-4o-mini-transcribe", provider: "OpenAI", brand: "openai", backend: "openai",
    desc: "Fast, accurate hosted transcription.", keyName: "OpenAI API key", keyPrefix: "sk-" },
  { id: "xai/grok-speech-to-text", name: "grok-speech-to-text", provider: "xAI", brand: "xai", backend: "xai",
    desc: "Grok speech-to-text, hosted.", keyName: "xAI API key", keyPrefix: "xai-" },
  { id: "gemini/gemini-3-flash-preview", name: "gemini-3-flash-preview", provider: "Google", brand: "gemini", backend: "gemini",
    desc: "Gemini multimodal, hosted.", keyName: "Gemini API key", keyPrefix: "AIza" },
];
export const modelById = (id) => MODELS.find((m) => m.id === id) || MODELS[0];

export const DEMO_PHRASES = [
  "Can you push the release branch and tag it before the standup at ten.",
  "Reminder to follow up with the Stalwart team about the OAuth scopes this afternoon.",
  "Let's move the sync to Thursday and keep Friday clear for the demo build.",
  "Draft a short note thanking the beta testers and ask them for crash reports.",
  "Add a section to the doctor command that checks the microphone permissions.",
  "The turbo model feels noticeably faster on this machine than the hosted ones.",
];

export function nowLabel() {
  const d = new Date();
  return clockLabel(d);
}

export function clockLabel(ts) {
  const d = ts instanceof Date ? ts : new Date(ts);
  let h = d.getHours();
  const m = String(d.getMinutes()).padStart(2, "0");
  const ap = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${h}:${m} ${ap}`;
}

export function formatHistoryTime(createdAt) {
  const t = typeof createdAt === "number" ? createdAt : Date.parse(createdAt);
  if (Number.isNaN(t)) return "";
  const secs = Math.floor((Date.now() - t) / 1000);
  let rel;
  if (secs < 45) rel = "just now";
  else if (secs < 3600) rel = `${Math.max(1, Math.floor(secs / 60))}m ago`;
  else if (secs < 86400) rel = `${Math.floor(secs / 3600)}h ago`;
  else rel = `${Math.floor(secs / 86400)}d ago`;
  return `${clockLabel(t)} · ${rel}`;
}
