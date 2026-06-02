// store.jsx — shared context, data model, and the canned dictation demo.
const StoreCtx = React.createContext(null);
const useStore = () => React.useContext(StoreCtx);

const MODELS = [
  { id: "faster-whisper/turbo", name: "faster-whisper · turbo", provider: "Local", local: true,
    desc: "Runs on this machine — no key, nothing leaves your device.", brand: null },
  { id: "openai/gpt-4o-mini-transcribe", name: "gpt-4o-mini-transcribe", provider: "OpenAI", brand: "openai",
    desc: "Fast, accurate hosted transcription.", keyName: "OpenAI API key", keyPrefix: "sk-" },
  { id: "xai/grok-speech-to-text", name: "grok-speech-to-text", provider: "xAI", brand: "xai",
    desc: "Grok speech-to-text, hosted.", keyName: "xAI API key", keyPrefix: "xai-" },
  { id: "gemini/gemini-3-flash-preview", name: "gemini-3-flash-preview", provider: "Google", brand: "gemini",
    desc: "Gemini multimodal, hosted.", keyName: "Gemini API key", keyPrefix: "AIza" },
];
const modelById = id => MODELS.find(m => m.id === id);

const DEMO_PHRASES = [
  "Can you push the release branch and tag it before the standup at ten.",
  "Reminder to follow up with the Stalwart team about the OAuth scopes this afternoon.",
  "Let's move the sync to Thursday and keep Friday clear for the demo build.",
  "Draft a short note thanking the beta testers and ask them for crash reports.",
  "Add a section to the doctor command that checks the microphone permissions.",
  "The turbo model feels noticeably faster on this machine than the hosted ones.",
];

function nowLabel() {
  const d = new Date();
  let h = d.getHours(), m = String(d.getMinutes()).padStart(2, "0");
  const ap = h >= 12 ? "PM" : "AM"; h = h % 12 || 12;
  return `${h}:${m} ${ap}`;
}

Object.assign(window, { StoreCtx, useStore, MODELS, modelById, DEMO_PHRASES, nowLabel });
