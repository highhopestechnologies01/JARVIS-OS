"use client";

import { useState, useRef, useEffect } from "react";

type VoiceState = "idle" | "listening" | "processing" | "speaking" | "error";

export function VoicePanel() {
  const [state, setState] = useState<VoiceState>("idle");
  const [transcript, setTranscript] = useState("");
  const [response, setResponse] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);

  const HERMES_URL = process.env.NEXT_PUBLIC_HERMES_URL ?? "http://localhost:8001";

  useEffect(() => {
    if (typeof window === "undefined") return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SpeechRecognitionAPI: any =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognitionAPI) return;

    const recognition = new SpeechRecognitionAPI();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-US";

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = async (event: any) => {
      const text = event.results[0][0].transcript;
      setTranscript(text);
      setState("processing");
      await sendToHermes(text);
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onerror = (event: any) => {
      setErrorMsg(`Mic error: ${event.error}`);
      setState("error");
    };

    recognition.onend = () => {
      if (state === "listening") setState("idle");
    };

    recognitionRef.current = recognition;
  }, []);

  const sendToHermes = async (text: string) => {
    try {
      const res = await fetch(`${HERMES_URL}/api/v1/voice/command`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await res.json();
      setResponse(data.response);
      speak(data.response);
    } catch {
      setErrorMsg("Could not reach Hermes.");
      setState("error");
    }
  };

  const speak = (text: string) => {
    if (!window.speechSynthesis) {
      setState("idle");
      return;
    }
    setState("speaking");
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.95;
    utterance.pitch = 0.9;
    utterance.onend = () => setState("idle");
    window.speechSynthesis.speak(utterance);
  };

  const handleMicClick = () => {
    if (state === "listening") {
      recognitionRef.current?.stop();
      setState("idle");
      return;
    }
    if (state === "speaking") {
      window.speechSynthesis?.cancel();
      setState("idle");
      return;
    }
    setTranscript("");
    setResponse("");
    setErrorMsg("");
    setState("listening");
    recognitionRef.current?.start();
  };

  const stateConfig = {
    idle:       { label: "Speak to JARVIS",  color: "bg-jarvis-border",  pulse: false, icon: "🎙️" },
    listening:  { label: "Listening...",      color: "bg-jarvis-blue",    pulse: true,  icon: "🎙️" },
    processing: { label: "Processing...",     color: "bg-jarvis-yellow",  pulse: true,  icon: "⚙️" },
    speaking:   { label: "Speaking...",       color: "bg-jarvis-green",   pulse: true,  icon: "🔊" },
    error:      { label: "Error",             color: "bg-jarvis-red",     pulse: false, icon: "⚠️" },
  };

  const cfg = stateConfig[state];

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-5">
      <h2 className="text-jarvis-text font-semibold text-sm uppercase tracking-wider mb-4">
        Voice Interface
      </h2>

      {/* Mic button */}
      <div className="flex flex-col items-center gap-4 py-4">
        <button
          onClick={handleMicClick}
          disabled={state === "processing"}
          className={`
            w-20 h-20 rounded-full flex items-center justify-center text-3xl
            transition-all duration-300 cursor-pointer
            ${cfg.color} ${cfg.pulse ? "animate-pulse" : ""}
            ${state === "processing" ? "opacity-60 cursor-not-allowed" : "hover:opacity-80"}
            border-2 border-jarvis-border
          `}
        >
          {cfg.icon}
        </button>
        <span className="text-jarvis-muted text-xs font-mono">{cfg.label}</span>
      </div>

      {/* Transcript */}
      {transcript && (
        <div className="mt-3 p-3 bg-jarvis-bg rounded-lg border border-jarvis-border">
          <p className="text-jarvis-muted text-xs uppercase tracking-wider mb-1">You said</p>
          <p className="text-jarvis-text text-sm">{transcript}</p>
        </div>
      )}

      {/* Response */}
      {response && (
        <div className="mt-3 p-3 bg-jarvis-green/5 rounded-lg border border-jarvis-green/20">
          <p className="text-jarvis-green text-xs uppercase tracking-wider mb-1">JARVIS</p>
          <p className="text-jarvis-text text-sm leading-relaxed">{response}</p>
        </div>
      )}

      {/* Error */}
      {errorMsg && (
        <div className="mt-3 p-3 bg-jarvis-red/10 rounded-lg border border-jarvis-red/20">
          <p className="text-jarvis-red text-xs">{errorMsg}</p>
        </div>
      )}
    </div>
  );
}
