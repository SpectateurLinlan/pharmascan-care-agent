# assistant_capabilities

Public typed adapters owned by this backend component; no direct cross-private access.

| File | Responsibility / public definitions |
|---|---|
| [accounts.py](accounts.py) | Auth secrets and identity changes belong only to the existing secure patient UI. |
| [care.py](care.py) | Care preparation never writes clinical records; patient APIs own confirmation. |
| [care_drafts.py](care_drafts.py) | Typed projection of a care draft through existing public contracts. |
| [contacts.py](contacts.py) | Consented contact drafts use only the owned public caregiver service. |
| [conversations.py](conversations.py) | Owned bounded conversation projections; historical text is never executable input. |
| [draft_recovery.py](draft_recovery.py) | Recover owned unfinished regimens without replacing prior task authority. |
| [enrollment.py](enrollment.py) | Enrollment collection; existing services retain review/activation authority. |
| [feedback.py](feedback.py) | Feedback drafts cannot send email or make a clinical communication. |
| [image_compare.py](image_compare.py) | Pure photo check preparation; processing is an independent explicit request. |
| [knowledge.py](knowledge.py) | Pure local name preparation; task reads never contact knowledge providers. |
| [late_reports.py](late_reports.py) | Existing historical patient review only; never an Agent report writer. |
| [media.py](media.py) | Pure owned media metadata projections; bytes remain behind native patient APIs. |
| [media_drafts.py](media_drafts.py) | Owned lifecycle drafts and explicit native payloads; no binary reads or writes. |
| [media_mutations.py](media_mutations.py) | Media review receipts never grant the model authority to perform patient writes. |
| [medication_management.py](medication_management.py) | Owned medication reads and patient-reviewed maintenance over public services. |
| [notification_devices.py](notification_devices.py) | Device intent opens a safe page; no credentials or model write authority. |
| [pdf_upload.py](pdf_upload.py) | Prepare a library upload; only the independent patient API can materialize it. |
| [photo_upload.py](photo_upload.py) | Prepare a gallery upload; only the independent patient API can materialize it. |
| [plan_changes.py](plan_changes.py) | Change recorded instructions through the existing independent review flow. |
| [preferences.py](preferences.py) | Public preference draft operations, separate from native patient persistence. |
| [records.py](records.py) | Actual patient record projections; no occurrence/report/challenge publication. |
| [reminder_mutations.py](reminder_mutations.py) | Prepare reminder drafts; only the independent native patient APIs may save. |
| [reminders.py](reminders.py) | Reminder projections never materialize occurrences or invoke device permissions. |
| [reports.py](reports.py) | Prepare only an owned patient UI; actual self-report APIs keep write authority. |
| [settings_mutations.py](settings_mutations.py) | Shared current-review protocol for nonsecret native settings/contact operations. |
| [source_preview.py](source_preview.py) | Prepare source type and owned raw original without running extraction. |
| [sources.py](sources.py) | Source preparation and actual patient-result capture; no clinical write executor. |
| [support.py](support.py) | Static patient device/navigation actions; preparation never uses device APIs. |
