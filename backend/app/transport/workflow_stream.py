"""SSE owns its request resources until the bounded worker actually stops."""

import asyncio
import json

import anyio
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse


def frame(kind: str, value: dict) -> str:
    return f"event: {kind}\ndata: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}\n\n"


class WorkflowStreamResponse(StreamingResponse):
    def __init__(self, *, service, owner, run_id, work, close_request=None):
        self._service, self._owner, self._run_id = service, owner, run_id
        self._work, self._close = work, close_request
        self._worker = None
        self._finished = False
        super().__init__(
            self._iterate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
                "X-Agent-Run-ID": str(run_id),
            },
        )

    async def _execute(self):
        try:
            return await run_in_threadpool(self._service.execute, self._owner, self._run_id, self._work)
        except Exception:
            # Service has recorded a safe terminal reason. Never stream raw errors.
            return None

    async def _finish(self):
        if self._finished:
            return
        self._finished = True
        with anyio.CancelScope(shield=True):
            try:
                if self._worker is not None:
                    if not self._worker.done():
                        self._service.cancel(self._owner, self._run_id)
                    await asyncio.shield(self._worker)
            finally:
                if self._close is not None:
                    await run_in_threadpool(self._close)

    async def _iterate(self):
        cursor = 0
        try:
            while True:
                snapshot = self._service.read(self._owner, self._run_id)
                for event in snapshot.events[cursor:]:
                    yield frame("progress", event.model_dump(mode="json"))
                    cursor = event.sequence
                if self._worker.done():
                    # Refresh once after worker completion, including terminal metadata.
                    snapshot = self._service.read(self._owner, self._run_id)
                    if cursor < len(snapshot.events):
                        continue
                    result = self._worker.result()
                    if snapshot.status == "completed" and result is not None:
                        yield frame("result", {"run_id": str(self._run_id), "result": result.model_dump(mode="json")})
                    return
                await asyncio.sleep(0.025)
        finally:
            await self._finish()

    async def __call__(self, scope, receive, send):
        self._worker = asyncio.create_task(self._execute())
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._finish()
