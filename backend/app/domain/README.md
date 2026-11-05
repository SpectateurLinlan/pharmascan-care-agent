# domain

纯安全、剂量、库存和时间规则；不依赖 I/O 或 UI。

| 文件/子包 | 内容 |
|---|---|
| [dose_attention.py](dose_attention.py) | Display attention window only; never an intake or catch-up dosing decision. |
| [dose_display.py](dose_display.py) | Conservative pure display arithmetic. Unknown evidence always abstains. |
| [enrollment_inputs.py](enrollment_inputs.py) | Pure input normalization shared by preview and the existing draft writer. |
| [errors.py](errors.py) | Domain error hierarchy with stable error codes (API error envelope). |
| [health_safety.py](health_safety.py) | Small conditional safety notice, NOT a validated triage or diagnosis model. |
| [interval_schedule.py](interval_schedule.py) | Elapsed-hour schedules use a reviewed local calendar anchor, never a read-time guess. |
| [inventory.py](inventory.py) | Pure stock rules; no strength conversion and no inferred consumption. |
| [policy.py](policy.py) | Deterministic safety & evidence policy (pure functions only). |
| [reference_policy.py](reference_policy.py) | No image/class/model score can independently authorize a dose. |
| [regimen_overlap.py](regimen_overlap.py) | Pure, conservative identity and inclusive course-window comparisons. |

新增实现应留在本层职责内；依赖与信任边界以 docs/ARCHITECTURE.md 为准。
