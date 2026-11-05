# agent

有界编排、能力注册、typed tools 和策略入口；不直接调用 SQL/私有仓库。

| 文件/子包 | 内容 |
|---|---|
| [capabilities.py](capabilities.py) | Static user capability registry; adapters are bound at the composition root. |
| [conversation.py](conversation.py) | Bounded model orchestration over the existing tools/session/safety system. |
| [current_medication.py](current_medication.py) | Bounded, read-only discovery before clarifying a contextual medicine-use question. |
| [instructions.py](instructions.py) | Versioned actual provider instructions; hashed per bounded run. |
| [knowledge_intent.py](knowledge_intent.py) | Recognise explicit education questions; never infer an indication or dose. |
| [localized_reply.py](localized_reply.py) | Chinese rendering of supported typed tool outcomes; never dosing inference. |
| [long_term_tools.py](long_term_tools.py) | Bounded long-term read tools and proposals; this adapter cannot confirm writes. |
| [medication_resolution.py](medication_resolution.py) | Conservative read-only comparison of trusted, otherwise equivalent products. |
| [memory.py](memory.py) | Only successful typed tool results may establish patient references. |
| [model_tools.py](model_tools.py) | Model arguments never include identity or confirmation/write credentials. |
| [orchestrator.py](orchestrator.py) | Bounded agent orchestrator + deterministic degraded-mode intent router. |
| [patient_read_reply.py](patient_read_reply.py) | Data-driven patient renderers. Stored times and reports never prove ingestion. |
| [read_dialogue.py](read_dialogue.py) | Bounded read planning over existing tools and the existing session context. |
| [registry.py](registry.py) | Tool registry: allowlisted handlers that call application services only. |
| [schedule_reply.py](schedule_reply.py) | Patient-readable schedule facts grounded only in typed application results. |
| [status_reply.py](status_reply.py) | Render dates and individual dose states without inferring ingestion. |
| [tools.py](tools.py) | Typed tool contracts: allowlisted names, typed requests and results. |

新增实现应留在本层职责内；依赖与信任边界以 docs/ARCHITECTURE.md 为准。
