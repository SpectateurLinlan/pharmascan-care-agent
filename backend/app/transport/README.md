# transport

身份校验、HTTP 请求/响应、路由和 composition root；患者与 worker 分离。

| 文件/子包 | 内容 |
|---|---|
| [app_factory.py](app_factory.py) | FastAPI application factory. |
| [auth.py](auth.py) | Authenticated patient context. |
| [care_binding.py](care_binding.py) | Fixed patient routes may opt into current Assistant review checks. |
| [container.py](container.py) | Composition root for the HTTP transport. |
| [deps.py](deps.py) | Per-request dependency access. |
| [dispatcher.py](dispatcher.py) | Separate worker ASGI factory. Never mounted in the patient application. |
| [error_mapping.py](error_mapping.py) | Domain error -> HTTP status mapping. |
| [media_binding.py](media_binding.py) | Paired task headers opt native patient requests into current media review guards. |
| [persistent_workflow_composition.py](persistent_workflow_composition.py) | Patient ports share one verified JWT; the verifier has a separate lazy identity. |
| [persistent_workflow_graph.py](persistent_workflow_graph.py) | Complete request-local candidate. Construction never enables a live rollout. |
| `routes/` | 患者已授权 HTTP 路由，按业务资源划分 |
| [schemas.py](schemas.py) | Typed HTTP request/response schemas for the transport layer. |
| [worker_container.py](worker_container.py) | Administrative composition root. Never imported by patient app/container. |
| [workflow_binding.py](workflow_binding.py) | Optional paired headers for native patient actions. |
| [workflow_schemas.py](workflow_schemas.py) | Versioned HTTP DTOs; no transport dependency in application messages. |
| [workflow_stream.py](workflow_stream.py) | SSE owns its request resources until the bounded worker actually stops. |

新增实现应留在本层职责内；依赖与信任边界以 docs/ARCHITECTURE.md 为准。
