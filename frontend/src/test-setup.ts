/**
 * Vitest setup: provide the small browser surface the API client touches.
 *
 * Only `window.localStorage` and `window.crypto` are needed, so a jsdom
 * dependency is not justified — a minimal stub keeps the test run fast.
 */

import { vi } from 'vitest';

// Local tests must never initiate real signup from a developer's dotenv.
vi.stubEnv('VITE_SUPABASE_URL', '');
vi.stubEnv('VITE_SUPABASE_PUBLISHABLE_KEY', '');

const store = new Map<string, string>();

const localStorageStub = {
  getItem: (key: string): string | null => store.get(key) ?? null,
  setItem: (key: string, value: string): void => {
    store.set(key, value);
  },
  removeItem: (key: string): void => {
    store.delete(key);
  },
  clear: (): void => {
    store.clear();
  },
};

if (typeof window === 'undefined') Object.defineProperty(globalThis, 'window', {
  value: { localStorage: localStorageStub },
  writable: true,
  configurable: true,
});
