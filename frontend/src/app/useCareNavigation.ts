/** Patient navigation owns route history, return paths and the unsaved-input leave guard. */
import { useCallback, useEffect, useRef, useState } from 'react';

import { roots, parents, normalize, valid } from '../shared/contracts/routes';

export { roots, isCareRoute } from '../shared/contracts/routes';

function authCallback() {
  return (
    /(?:access_token|refresh_token)=/.test(window.location.hash) ||
    new URLSearchParams(window.location.search).has('code')
  );
}

function initial(): string[] {
  const route = normalize(window.location.hash.slice(1).split('?')[0] || 'today');
  const stored: unknown = window.history.state?.careRoute;
  if (
    Array.isArray(stored) &&
    stored.length <= 12 &&
    stored.every((item) => typeof item === 'string' && valid(item)) &&
    stored.at(-1) === route
  )
    return stored as string[];
  return valid(route) ? [route] : ['today'];
}

function currentRouteHref(route: string) {
  if (window.location.hash.startsWith(`#${route}?`)) return window.location.hash;
  if (
    (route === 'gallery' || route === 'care-tasks') &&
    window.location.hash.startsWith(`#${route}`)
  )
    return window.location.hash;
  return `#${route}`;
}

/** Root selection replaces only its current entry; child tasks retain their origin. */
export function useCareNavigation(blocked: boolean, leaveBlocked = false) {
  const [stack, setStack] = useState(initial);
  const [pending, setPending] = useState<string[] | null>(null);
  const pendingHref = useRef<string | null>(null);
  const leaving = useRef(leaveBlocked);
  leaving.current = leaveBlocked;
  const current = useRef(stack);
  current.current = stack;
  const locked = useRef(blocked);
  locked.current = blocked;
  useEffect(() => {
    // Let the identity SDK consume and scrub email/OAuth callbacks first.
    if (!authCallback())
      window.history.replaceState(
        { ...window.history.state, careRoute: current.current },
        '',
        currentRouteHref(current.current.at(-1) ?? 'today'),
      );
    const pop = () => {
      if (locked.current) {
        window.history.pushState({ careRoute: current.current }, '', `#${current.current.at(-1)}`);
        return;
      }
      const next = initial();
      if (leaving.current) {
        window.history.pushState({ careRoute: current.current }, '', `#${current.current.at(-1)}`);
        setPending(next);
        return;
      }
      setStack(next);
    };
    const unload = (event: BeforeUnloadEvent) => {
      if (leaving.current) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', unload);
    window.addEventListener('popstate', pop);
    return () => {
      window.removeEventListener('popstate', pop);
      window.removeEventListener('beforeunload', unload);
    };
  }, []);
  const navigate = useCallback(
    (
      value: string,
      query?: Record<string, string>,
      options?: { preserveOrigin?: boolean; replace?: boolean },
    ) => {
      const next = normalize(value);
      if (locked.current || authCallback() || !valid(next) || next === current.current.at(-1))
        return;
      const isRoot = roots.some((root) => root === next);
      const preserveOrigin = options?.preserveOrigin === true;
      const updated = isRoot && !preserveOrigin ? [next] : [...current.current, next].slice(-12);
      const search = query ? new URLSearchParams(query).toString() : '';
      const href = `#${next}${search ? '?' + search : ''}`;
      if (leaving.current) {
        pendingHref.current = href;
        setPending(updated);
        return;
      }
      window.history[
        options?.replace === true || (isRoot && !preserveOrigin) ? 'replaceState' : 'pushState'
      ]({ careRoute: updated }, '', href);
      setStack(updated);
      document.documentElement.scrollTop = 0;
    },
    [],
  );
  const restore = useCallback(
    (value: string, query?: Record<string, string>, routeStack?: readonly string[]) => {
      const route = normalize(value);
      if (authCallback() || !valid(route)) return;
      const restored =
        routeStack &&
        routeStack.length > 0 &&
        routeStack.length <= 12 &&
        routeStack.every((item) => valid(item)) &&
        routeStack.at(-1) === route
          ? [...routeStack]
          : [route];
      const search = query ? new URLSearchParams(query).toString() : '';
      window.history.replaceState(
        { ...window.history.state, careRoute: restored },
        '',
        `#${route}${search ? '?' + search : ''}`,
      );
      current.current = restored;
      setStack(restored);
      setPending(null);
      pendingHref.current = null;
      document.documentElement.scrollTop = 0;
    },
    [],
  );

  function back() {
    if (locked.current) return;
    if (stack.length > 1) window.history.back();
    else {
      const parent = parents[stack[0] ?? ''] ?? 'today';
      if (leaving.current) {
        setPending([parent]);
        return;
      }
      window.history.replaceState({ careRoute: [parent] }, '', `#${parent}`);
      setStack([parent]);
    }
  }

  const confirmLeave = () => {
    if (!pending) return;
    window.history.replaceState(
      { careRoute: pending },
      '',
      pendingHref.current ?? `#${pending.at(-1)}`,
    );
    pendingHref.current = null;
    setStack(pending);
    setPending(null);
  };
  return {
    pending,
    confirmLeave,
    cancelLeave: () => {
      pendingHref.current = null;
      setPending(null);
    },
    tab: stack.at(-1) ?? 'today',
    navigate,
    restore,
    back,
    isRoot: stack.length === 1 && roots.some((root) => root === stack.at(-1)),
  };
}
