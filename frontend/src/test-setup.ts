/**
 * Vitest setup: provide the small browser surface the API client touches.
 *
 * Only `window.localStorage` and `window.crypto` are needed, so a jsdom
 * dependency is not justified — a minimal stub keeps the test run fast.
 */

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

Object.defineProperty(globalThis, 'window', {
  value: { localStorage: localStorageStub },
  writable: true,
  configurable: true,
});
