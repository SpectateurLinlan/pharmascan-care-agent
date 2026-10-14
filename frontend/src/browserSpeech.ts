/** Native browser STT. Browsers may use a remote recognition service. */
export type SpeechState = 'idle' | 'requesting' | 'listening' | 'processing' | 'review';
export interface RecognitionResultEvent { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string; confidence: number } }> }
export interface RecognitionErrorEvent { error: string }
export interface NativeRecognition {
  lang: string; continuous: boolean; interimResults: boolean; maxAlternatives: number;
  onstart: (() => void) | null; onaudioend: (() => void) | null; onend: (() => void) | null;
  onresult: ((event: RecognitionResultEvent) => void) | null;
  onerror: ((event: RecognitionErrorEvent) => void) | null;
  start(): void; stop(): void; abort(): void;
}
export type RecognitionConstructor = new () => NativeRecognition;
export interface SpeechRecognitionPort { create(): NativeRecognition }
export function browserSpeechProvider(scope: Window = window): SpeechRecognitionPort | null {
  const host = scope as Window & { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor };
  const Constructor = host.SpeechRecognition ?? host.webkitSpeechRecognition;
  return Constructor ? { create: () => new Constructor() } : null;
}
export function recognitionError(code: string): string {
  const messages: Record<string, string> = {
    'not-allowed': 'Microphone permission was denied. You can still type.',
    'service-not-allowed': 'Speech recognition is blocked. Please type instead.',
    'audio-capture': 'No microphone is available. Please type instead.',
    'no-speech': 'No speech was heard. Try again or type.',
    network: 'Speech recognition could not connect. Try again or type.',
    aborted: 'Listening cancelled. You can still type.',
  };
  return messages[code] ?? 'Speech recognition failed. Please review or type your message.';
}
