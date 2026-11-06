/** Volatile handover only; never persisted, submitted or reused for a new owner. */
export interface StartupDraft {
  text: string;
  focused: boolean;
  selection: { start: number; end: number };
}
