/** Ephemeral recording normalization; no audio persistence or automatic action. */
export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  if (sampleRate <= 0 || samples.length === 0 || samples.length / sampleRate > 30) {
    throw new Error('Please record a short message of up to 30 seconds.');
  }
  const count = Math.floor(samples.length * 16000 / sampleRate);
  const data = new ArrayBuffer(44 + count * 2);
  const view = new DataView(data);
  const text = (at: number, value: string) => [...value].forEach((letter, i) => view.setUint8(at + i, letter.charCodeAt(0)));
  text(0, 'RIFF'); view.setUint32(4, 36 + count * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); text(36, 'data'); view.setUint32(40, count * 2, true);
  for (let i = 0; i < count; i++) {
    const sample = Math.max(-1, Math.min(1, samples[Math.floor(i * sampleRate / 16000)] ?? 0));
    view.setInt16(44 + i * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
  }
  return new Blob([data], { type: 'audio/wav' });
}

export async function normalizeRecording(blob: Blob): Promise<Blob> {
  if (blob.size > 3_000_000) throw new Error('The recording is too large. Please try a shorter message.');
  const context = new AudioContext();
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer());
    const samples = new Float32Array(decoded.length);
    for (let channel = 0; channel < decoded.numberOfChannels; channel++) {
      const source = decoded.getChannelData(channel);
      for (let i = 0; i < samples.length; i++) samples[i] = (samples[i] ?? 0) + (source[i] ?? 0) / decoded.numberOfChannels;
    }
    return encodeWav(samples, decoded.sampleRate);
  } finally { await context.close(); }
}
