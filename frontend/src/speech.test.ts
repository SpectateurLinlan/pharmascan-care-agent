import { describe, expect, it } from 'vitest';
import { encodeWav } from './speech';

describe('ephemeral audio normalization', () => {
  it('produces mono 16kHz PCM with a bounded WAV header', async () => {
    const blob = encodeWav(new Float32Array([0, 1, -1, 0.5]), 16000);
    const view = new DataView(await blob.arrayBuffer());
    expect(blob.type).toBe('audio/wav');
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getInt16(46, true)).toBe(32767);
    expect(view.getInt16(48, true)).toBe(-32768);
  });
  it('refuses empty, oversized or invalid-rate recordings', () => {
    expect(() => encodeWav(new Float32Array(), 16000)).toThrow();
    expect(() => encodeWav(new Float32Array(16000 * 31), 16000)).toThrow();
    expect(() => encodeWav(new Float32Array([0]), 0)).toThrow();
  });
});
