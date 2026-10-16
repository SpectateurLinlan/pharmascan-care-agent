import type {CSSProperties,ReactNode} from 'react';
export type IconName='speaker'|'house'|'pill'|'clipboard'|'user'|'settings'|'bell'|'languages'|'chevron-left'|'chevron-right'|'chevron-down'|'plus'|'message'|'camera'|'image'|'shield'|'alert'|'info'|'check'|'clock'|'calendar'|'file'|'heart'|'close';
const paths:Record<IconName,ReactNode>={
 speaker:<><path d="m11 5-6 4H2v6h3l6 4Z"/><path d="M15 8a6 6 0 0 1 0 8M18 5a10 10 0 0 1 0 14"/></>,
 house:<><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z"/></>,
 pill:<><path d="m10 4-6 6a5.65 5.65 0 0 0 8 8l6-6a5.65 5.65 0 0 0-8-8Z"/><path d="m7 7 8 8"/></>,
 clipboard:<><rect x="5" y="5" width="14" height="16" rx="2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M10 12h5m-5 5h5M8 12h.01M8 17h.01"/></>,
 user:<><circle cx="12" cy="7" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></>,
 settings:<><circle cx="12" cy="12" r="3.25"/><path d="M19.1 14.6a1.5 1.5 0 0 0 .3 1.65l.05.05a1.9 1.9 0 0 1-2.7 2.7l-.05-.05a1.5 1.5 0 0 0-1.65-.3 1.5 1.5 0 0 0-.9 1.37v.13a1.9 1.9 0 0 1-3.8 0v-.07a1.5 1.5 0 0 0-.98-1.37 1.5 1.5 0 0 0-1.65.3l-.05.05a1.9 1.9 0 0 1-2.7-2.7l.05-.05a1.5 1.5 0 0 0 .3-1.65 1.5 1.5 0 0 0-1.37-.9H4.1a1.9 1.9 0 0 1 0-3.8h.07a1.5 1.5 0 0 0 1.37-.98 1.5 1.5 0 0 0-.3-1.65l-.05-.05a1.9 1.9 0 0 1 2.7-2.7l.05.05a1.5 1.5 0 0 0 1.65.3h.07a1.5 1.5 0 0 0 .9-1.37V4.1a1.9 1.9 0 0 1 3.8 0v.07a1.5 1.5 0 0 0 .9 1.37 1.5 1.5 0 0 0 1.65-.3l.05-.05a1.9 1.9 0 0 1 2.7 2.7l-.05.05a1.5 1.5 0 0 0-.3 1.65v.07a1.5 1.5 0 0 0 1.37.9h.13a1.9 1.9 0 0 1 0 3.8h-.07a1.5 1.5 0 0 0-1.37.9Z"/></>,
 bell:<><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4"/></>,
 languages:<><path d="M3 5h12M9 3v2m3 0c0 6-4 9-9 11m2-8c1 4 5 7 9 8m0 5 4-11 4 11m-6.5-4h5"/></>,
 'chevron-left':<path d="m15 5-7 7 7 7"/>, 'chevron-right':<path d="m9 5 7 7-7 7"/>, 'chevron-down':<path d="m5 9 7 7 7-7"/>,
 plus:<path d="M12 5v14M5 12h14"/>,
 message:<path d="M4 4h16v13H9l-5 4Z"/>,
 camera:<><path d="M4 8h3l1.5-2h7L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z"/><circle cx="12" cy="13" r="3.5"/></>,
 image:<><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="m4 18 5-5 4 3 4-5 4 5"/></>,
 shield:<><path d="M12 3l7 3v6c0 4-3 7.5-7 9-4-1.5-7-5-7-9V6Z"/><path d="m9 12 2 2 4-4"/></>,
 alert:<><path d="M12 4l9 16H3Z"/><path d="M12 10v4M12 17h.01"/></>,
 info:<><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></>,
 check:<path d="m5 13 4 4L19 7"/>,
 clock:<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
 calendar:<><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/></>,
 file:<><path d="M6 3h8l4 4v14H6Z"/><path d="M14 3v4h4"/></>,
 heart:<path d="M12 20s-7-4.5-7-9a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 4.5-7 9-7 9Z"/>,
 close:<path d="m6 6 12 12M18 6 6 18"/>,
};
/** Authored geometry with consistent stroke; no font glyph/network dependency. */
export function Icon({name,style}:{name:IconName;style?:CSSProperties}){return <svg className="app-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" style={style}>{paths[name]}</svg>;}
