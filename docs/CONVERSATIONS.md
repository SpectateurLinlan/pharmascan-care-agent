# Persistent conversations

Conversation identity is separate from a short-lived executable Agent Session. The application service owns authorization, opt-in persistence, bounded text restoration and request idempotency. HTTP and React consume typed DTOs; the orchestrator still executes only the existing public tools.

Additive schema: owned `conversations`; nullable conversation association on existing turns and runtime sessions; owned `conversation_requests` claims to prevent a duplicate message from rerunning tools. Legacy turns are never backfilled or grouped by dates. Old message API remains compatible. Existing save/clear controls remain authoritative; new durable rows require saving consent. New history is not truncated to fit model context. Attachment metadata records only a patient-readable presence marker; existing chat processing does not durably save the image itself. This implementation does not invent persistent attachment references.

Resume creates a fresh executable session and selects at most six bounded text exchanges. Historical text is untrusted conversation, not current medical facts, tool authority or confirmation state. All medical/tool reads remain patient-scoped and current. No saved tool calls are replayed. Context also obeys an aggregate UTF-8 budget below the existing database cap.

Deployment order: additive migration, compatible backend, then frontend. Old append retention must ignore new conversation-owned turns; existing clear removes new and legacy messages and clears recent session text. No production data backfill. A failed migration rolls back atomically. Pre-deployment rollback may restore function definitions and remove new empty structures only after proving there is no new user data; otherwise prefer a forward correction.

Acceptance: A/B identity and drafts, reload and continuation, cross-user rejection, old confirmations not restored, consent off, duplicate requests, six long Chinese turns, photo separation, local dates, actual persistence and SQL/RLS tests, and responsive real-browser journeys. Production schema verification does not imply application deployment or real-provider acceptance.

## Public HTTP contract

- `GET /api/agent/conversations`: owned, nonempty conversations, ordered by activity with a keyset cursor.
- `GET /api/agent/conversations/{id}`: up to 50 exchanges by default; older-page cursor. User/assistant text and attachment presence are separate typed fields.
- `POST /api/agent/conversations/{id}/resume`: owned read plus a fresh runtime session containing bounded untrusted text, no executable historical state.
- `POST /api/agent/navigation-context`: validates owned medication/regimen IDs through enrollment and supplies the display name. Navigation text is not medical verification.
- Existing `POST /api/agent/messages`: additive optional `conversation_id` and `navigation_context`. A present null conversation ID opts a new client into thread behavior; an omitted field keeps old-client behavior. The first saved send creates an identity derived from a patient-scoped request UUID, never from a date. `conversation_id` and `history_saved` are returned explicitly.
- Existing save preferences and confirmed history clear remain the only privacy controls. Disabling future saving does not silently erase saved history. Existing short-lived runtime-context behavior remains separate from durable history; no physical timed-erasure guarantee is added.

Conversation/message IDs and patient identity are never supplied by the model. Claims use a payload digest and return new/completed/busy; completed retries return saved text without replaying actions. Failed/in-progress requests remain quarantined; inspect the conversation and clinical records before explicitly making a new request. A history-storage outage returns the produced answer with `history_saved=false` rather than claiming it was saved.

## UI and context

The existing mounted `AssistantScreen` serves Today and the full workspace. Per-conversation drafts, attachments and safe in-memory runtime state stay together; only the selected ID is stored in owner-scoped browser storage. A cached live view retains unsaved continuation; a refresh/uncached restore uses the server resume API. Expired runtime sessions renew under the same owned conversation. Live messages are shown six at a time with an explicit earlier-message control; all remain in memory, and saved history has independent server pagination.

Saving a turn retains up to 2,000 user characters and 32,000 assistant characters; legacy readers receive their existing 4,000-character assistant field. Overlong input is rejected rather than silently truncated. Context selects at most six bounded exchanges and an aggregate 16KB UTF-8 budget below the existing 20KB database constraint. Older full messages remain queryable. Tools, pending confirmations, old photo evidence and medical references are not restored as current authority. Ambiguous references need a fresh tool read or clarification.

Desktop history can be toggled beside the timeline; mobile history replaces it temporarily. Compact quick tasks are expandable. The visual viewport controls keyboard placement; physical device keyboard/microphone behavior still requires device acceptance. Page source is separately authorized and scoped to each view, with a return action. Global navigation adds no source claim.

## Migration and recovery

[`202610170026_conversation_threads.sql`](../supabase/migrations/202610170026_conversation_threads.sql) is additive and backward compatible. New tables force owner RLS; authenticated clients can read but use owner/consent-checking security-definer RPCs to write. Composite FKs enforce owner/thread/session/request associations. Old append retention excludes durable thread rows. No legacy history is backfilled or rewritten.

[`202610170026_empty_only.sql`](../supabase/rollback/202610170026_empty_only.sql) is a **manual, empty-data-only** recovery artifact, tested transactionally in isolated PostgreSQL. It refuses any new conversation/request or linked session/message data. Never run it automatically or after users have adopted the feature. Restore the previous functions only while preserving their grants; reconcile only migration026's ledger entry in the same maintenance transaction. Once new data exists, preserve it and prefer a separately reviewed forward correction.

Migration026 was applied and catalog-verified during UX Polish C; this does not mean a frontend/backend release was performed. Real Gemini, hosted JWT lifecycle and physical keyboard/audio checks are separate acceptance gates. BUG-04–09 medical-answer correctness work remains separate.
