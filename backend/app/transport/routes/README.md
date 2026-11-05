# routes

Public typed adapters owned by this backend component; no direct cross-private access.

| File | Responsibility / public definitions |
|---|---|
| [agent.py](agent.py) | Patient-owned conversations and stateless model orchestration through typed tools. |
| [assistant_workflows.py](assistant_workflows.py) | Authenticated workflow HTTP boundary over public application services. |
| [caregivers.py](caregivers.py) | Authenticated private contact CRUD, without delivery or access delegation. |
| [demo.py](demo.py) | Demo bootstrap endpoint. |
| [doses.py](doses.py) | Due-dose lookup, self-report confirmation and dose history endpoints. |
| [evidence.py](evidence.py) | Typed patient evidence APIs. All identity comes from verified AuthContext. |
| [feedback.py](feedback.py) | Owned feedback submissions; no external contact or medical advice delivery. |
| [health.py](health.py) | Health and capability endpoints. |
| [late_reports.py](late_reports.py) | Patient-only late reports: explicit two-phase confirmation, never Agent replay. |
| [long_term.py](long_term.py) | Authenticated public long-term care API; confirmations are human UI actions. |
| [medications.py](medications.py) | Medication endpoints: list, draft, review, confirm, activate. |
| [patient_records.py](patient_records.py) | Authenticated patient records; owner identity is never a payload field. |
| [preferences.py](preferences.py) | Identity comes exclusively from the verified principal. |
| [reminders.py](reminders.py) | Authenticated reminder preferences; app active/reopen delivery only. |
| [sources.py](sources.py) | Authenticated, consented read-only label preview. No activation side effects. |
| [speech.py](speech.py) | Authenticated speech I/O only; transcript submission remains an explicit action. |
| [usage.py](usage.py) | Own demo allowance only; no public counter mutation endpoint. |
| [visual.py](visual.py) | Authenticated image evidence request through application service. |
