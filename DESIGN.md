# PharmaScan Care interface system

Operate mode: patients should see today's tasks, understand the evidence and confirm an action without reading implementation details. Preserve the established sea-green identity and English/Chinese localization.

## Tokens and hierarchy

Source of truth: `frontend/src/styles.css`. Light palette: canvas `#f4f6f7`, surface `#ffffff`, alternate `#eef2f3`, text `#12262a`, muted `#52686d`, accent `#0f6f6c` and white primary-button text. Dark equivalents use the existing `prefers-color-scheme` tokens. Status always includes words, not color alone.

System sans-serif typography scales from the root with patient preference100–150%. Use rem-based text; let long names wrap. Card radius14px; consistent spacing and borders distinguish task groups without heavy decoration. Interactive targets are at least44px. Focus remains visible and keyboard order follows visual order.

## Surfaces

- Four equal primary destinations: Today / Medicines / Records / Me. Authored24px SVG icons use a consistent2px stroke and visible text labels.
- Today lists medicine/time/count summaries and expands one detail. No hidden slides fetch duplicate dose data. The composer stays accessible above navigation.
- Assistant is an in-place conversation layer with compact/full views and viewport-aware height. Background is inert; close returns focus to the origin. Confirmation sheets remain separate controlled actions.
- Me has one identity area, a single guest account-link action and grouped rows. Settings and login are child destinations. Header shortcuts point to these same destinations.
- Enrollment starts with an upload and automatic routing; uncertain results expose a manual correction. Strength, units per dose and calculated display total remain separate.
- Optional saved conversation history is text-only and paginated; clinical facts and dose confirmations are never reconstructed from historical buttons.

Use descriptive loading, retry, empty and final action states. Keep technical defenses in developer documents; show patients the purpose, missing information and next safe action.

## Review boundaries

Responsive browser acceptance covers390/430/768/1280px, English/Chinese, normal and enlarged text. Physical software-keyboard, device speech, lock-screen Push and actual calendar import require separate device acceptance. No generated raster assets or decorative motion were introduced.
