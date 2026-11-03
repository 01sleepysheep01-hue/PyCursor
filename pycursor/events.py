from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Event:
    seq: int
    type: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "type": self.type,
            "timestamp": self.timestamp,
            **self.data,
        }


class EventBus:
    """Thread-safe append-only event bus used by the SSE endpoint."""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._condition = threading.Condition()
        self._closed = False

    def emit(self, event_type: str, **data: Any) -> Event:
        with self._condition:
            event = Event(len(self._events) + 1, event_type, data)
            self._events.append(event)
            self._condition.notify_all()
            return event

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed

    @property
    def length(self) -> int:
        with self._condition:
            return len(self._events)

    def wait_many(
        self,
        after_seq: int,
        *,
        timeout: float = 15.0,
        stop: threading.Event | None = None,
    ) -> list[Event]:
        with self._condition:
            if len(self._events) <= after_seq and not self._closed:
                self._condition.wait(timeout=timeout)
            if after_seq < 0:
                after_seq = 0
            return list(self._events[after_seq:])


EventSink = Callable[[str, dict[str, Any]], None]


def make_event_sink(bus: EventBus) -> EventSink:
    def sink(event_type: str, data: dict[str, Any]) -> None:
        bus.emit(event_type, **data)

    return sink


def serialize_sse(event: Event) -> bytes:
    payload = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.seq}\nevent: {event.type}\ndata: {payload}\n\n".encode("utf-8")

