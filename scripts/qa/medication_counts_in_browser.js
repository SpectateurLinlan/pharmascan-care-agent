/** Existing localhost Vite app only. Uses the app-owned SDK/client, never parses storage. */
void (async () => {
  if (!['http://localhost:5173', 'http://127.0.0.1:5173'].includes(location.origin)) {
    console.info('BLOCKED: run only on the existing localhost:5173 app.');
    return;
  }
  if (typeof window.medithreadMedicationCounts !== 'function') {
    console.info('Diagnostic not loaded. Save ongoing work, reload this local Vite page, then retry. This does not mean you are signed out.');
    return;
  }
  try {
    const result = await window.medithreadMedicationCounts();
    console.info('MediThread read-only diagnostic:', result.result);
    console.table(result.endpoints.map(row => ({ ...row, states: row.states ? JSON.stringify(row.states) : null })));
    console.table(result.observed_requests);
  } catch {
    console.info('Diagnostic unavailable; no conclusion about sign-in. No credentials or records were printed.');
  }
})();
