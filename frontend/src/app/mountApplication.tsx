/** Deferred React/CSS composition; bootstrap owns only the local startup input. */
import React from 'react';
import ReactDOM from 'react-dom/client';
import { flushSync } from 'react-dom';
import { App } from './App';
import '../styles/index.css';
import { installWorkflowDiagnostics } from '../api/workflowDiagnostics';
import type { StartupDraft } from './startupDraft';

export function mountApplication(root: HTMLElement, initialDraft: StartupDraft): void {
  if (
    import.meta.env.DEV &&
    ['http://localhost:5173', 'http://127.0.0.1:5173'].includes(window.location.origin)
  ) {
    const stopWorkflows = installWorkflowDiagnostics(window);
    import.meta.hot?.dispose(stopWorkflows);

    void import('../api/localDiagnostics').then(({ installLocalDiagnostics }) => {
      const dispose = installLocalDiagnostics(window);
      import.meta.hot?.dispose(dispose);
    });
  }
  const application = ReactDOM.createRoot(root);
  // Commit within the snapshot's event task; no keystroke can reach a stale shell.
  flushSync(() =>
    application.render(
      <React.StrictMode>
        <App initialDraft={initialDraft} />
      </React.StrictMode>,
    ),
  );
}
