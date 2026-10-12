/**
 * Assistant screen.
 *
 * The reply is produced by a *deterministic rule router*, not a language
 * model, because no LLM provider key is available in this build (B03). Every
 * reply displays its mode so it can never be mistaken for a live LLM agent.
 *
 * Voice input uses the browser SpeechRecognition API when present, and falls
 * back to typing. It never sends audio anywhere by itself.
 */

import { useState } from 'react';
import { api, type AgentMessageResponse } from '../api/client';
import { Card, ErrorNotice, Tag } from './primitives';

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
}

function getSpeechRecognition(): SpeechRecognitionLike | null {
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!Ctor) return null;
  return new Ctor();
}

export function AssistantScreen({
  sessionId,
  onSession,
}: {
  sessionId: string | null;
  onSession: (id: string) => void;
}) {
  const [text, setText] = useState('');
  const [turns, setTurns] = useState<AgentMessageResponse[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);

  const speechAvailable = getSpeechRecognition() !== null;

  async function send() {
    const message = text.trim();
    if (message === '') return;
    setBusy(true);
    setError(null);
    try {
      const reply = await api.sendMessage({
        text: message,
        session_id: sessionId,
        client_turn_id: `turn-${Date.now()}`,
        slots: {},
      });
      onSession(reply.session_id);
      setTurns((previous) => [...previous, reply]);
      setText('');
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  }

  function toggleVoice() {
    const recognition = getSpeechRecognition();
    if (!recognition) return;
    if (listening) {
      recognition.stop();
      setListening(false);
      return;
    }
    recognition.lang = 'en-SG';
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const first = event.results[0];
      if (first && first[0]) {
        setText(first[0].transcript);
      }
    };
    recognition.onerror = () => setListening(false);
    recognition.onend = () => setListening(false);
    recognition.start();
    setListening(true);
  }

  return (
    <Card
      title="Assistant"
      hint="Ask about your medication. Replies are written by a fixed rule set, not a language model."
    >
      <div className="field">
        <label htmlFor="assistant-text">Your message</label>
        <input
          id="assistant-text"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !busy) void send();
          }}
          placeholder="e.g. I took my morning tablet"
        />
      </div>

      <div className="actions">
        <button className="primary" onClick={send} disabled={busy || text.trim() === ''}>
          Send
        </button>
        <button onClick={toggleVoice} disabled={!speechAvailable}>
          {listening ? 'Stop listening' : 'Speak instead'}{' '}
          {!speechAvailable ? <Tag muted>unavailable</Tag> : null}
        </button>
      </div>

      {error ? <ErrorNotice error={error} /> : null}

      {turns.length > 0 ? (
        <ul className="transcript">
          {turns.map((turn, index) => (
            <li className="turn" key={index}>
              <span className="turn__mode">
                intent: {turn.intent} · session: {turn.session_state} ·{' '}
                <Tag>mode: {turn.mode}</Tag>
              </span>
              <span className="turn__text">{turn.message}</span>
              {turn.tool_traces.length > 0 ? (
                <details>
                  <summary>{turn.tool_traces.length} tool step(s)</summary>
                  <ul className="traces">
                    {turn.tool_traces.map((trace, traceIndex) => (
                      <li key={traceIndex}>
                        {trace.tool_name} — {trace.status}
                        {trace.error_code ? ` (${trace.error_code})` : ''}
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="notice">
          No messages yet. This assistant cannot give medical advice — it only
          records what you tell it.
        </p>
      )}
    </Card>
  );
}
