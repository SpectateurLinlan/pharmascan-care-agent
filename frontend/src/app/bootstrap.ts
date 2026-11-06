import type { StartupDraft } from './startupDraft';

interface ApplicationModule {
  mountApplication(root: HTMLElement, draft: StartupDraft): void;
}

/** The entry needs no React, Auth, API client or full translation dictionary. */
export function startApplication(root: HTMLElement, load: () => Promise<ApplicationModule>): void {
  const input = root.querySelector<HTMLInputElement>('#startup-message')!;
  const status = root.querySelector<HTMLElement>('#startup-status')!;
  const retry = root.querySelector<HTMLButtonElement>('#startup-retry')!;
  let composing = input.dataset.composing === 'true';
  const failedStyles = new Set<HTMLLinkElement>();
  let loading = false;
  let mounted = false;
  let ready: ApplicationModule | undefined;

  function handover() {
    if (!ready || composing || mounted) return;
    const draft: StartupDraft = {
      text: input.value,
      focused: document.activeElement === input,
      selection: {
        start: input.selectionStart ?? input.value.length,
        end: input.selectionEnd ?? input.value.length,
      },
    };
    ready.mountApplication(root, draft);
    mounted = true;
    input.removeEventListener('compositionstart', beginComposition);
    input.removeEventListener('compositionend', endComposition);
    retry.removeEventListener('click', run);
    document.removeEventListener('error', rememberFailedStyle, true);
  }

  function beginComposition() {
    composing = true;
  }

  function endComposition() {
    composing = false;
    handover();
  }

  function rememberFailedStyle(event: Event) {
    const link = event.target;
    if (!(link instanceof HTMLLinkElement) || link.rel !== 'stylesheet') return;
    const url = new URL(link.href, document.baseURI);
    if (
      url.origin === location.origin &&
      url.pathname.startsWith('/assets/') &&
      url.pathname.endsWith('.css')
    )
      failedStyles.add(link);
  }

  async function repairStyles() {
    // Vite remembers attempted preloads, including failed CSS. Retry the links
    // explicitly and await them before a second import can mount the application.
    await Promise.all(
      Array.from(
        failedStyles,
        (link) =>
          new Promise<void>((resolve, reject) => {
            const replacement = link.cloneNode(false) as HTMLLinkElement;
            replacement.addEventListener(
              'load',
              () => {
                failedStyles.delete(replacement);
                resolve();
              },
              { once: true },
            );
            replacement.addEventListener(
              'error',
              () => {
                failedStyles.add(replacement);
                reject(new Error('Application stylesheet unavailable'));
              },
              { once: true },
            );
            failedStyles.delete(link);
            if (link.isConnected) link.replaceWith(replacement);
            else document.head.append(replacement);
          }),
      ),
    );
  }

  async function run() {
    if (loading || mounted) return;
    loading = true;
    retry.hidden = true;
    status.setAttribute('role', 'status');
    status.textContent = 'Loading MediThread. You can type while we prepare the app.';
    try {
      await repairStyles();
      ready = await load();
      performance.mark?.('medithread:runtime-ready');
      handover();
    } catch {
      status.setAttribute('role', 'alert');
      status.textContent =
        'MediThread could not be loaded. Your unsent message is kept on this page.';
      retry.hidden = false;
    } finally {
      loading = false;
    }
  }

  input.addEventListener('compositionstart', beginComposition);
  input.addEventListener('compositionend', endComposition);
  retry.addEventListener('click', run);
  document.addEventListener('error', rememberFailedStyle, true);
  performance.mark?.('medithread:bootstrap-ready');
  requestAnimationFrame(() => {
    void run();
  });
}
