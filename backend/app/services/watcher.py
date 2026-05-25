from __future__ import annotations

import asyncio
import time
from typing import Callable

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer


class MediaEventHandler(FileSystemEventHandler):
    """Watchdog event handler that debounces file events before firing a callback.

    The on_change callback is an async coroutine with signature:
        async def on_change(path: str, event_type: str, root_folder_id: str) -> None
    """

    def __init__(
        self,
        root_folder_id: str,
        on_change: Callable,
        settle_seconds: int = 2,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.root_folder_id = root_folder_id
        self.on_change = on_change
        self.settle_seconds = settle_seconds
        self._pending: dict[str, float] = {}
        self._loop = loop

    def _get_loop(self) -> asyncio.AbstractEventLoop | None:
        if self._loop is not None:
            return self._loop
        try:
            return asyncio.get_event_loop()
        except RuntimeError:
            return None

    def _schedule(self, path: str, event_type: str) -> None:
        """Record that this path needs processing after settle_seconds."""
        self._pending[path] = time.time() + self.settle_seconds
        loop = self._get_loop()
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._delayed_fire(path, event_type),
                loop,
            )

    async def _delayed_fire(self, path: str, event_type: str) -> None:
        """Wait for the settle period, then fire the callback if not superseded."""
        await asyncio.sleep(self.settle_seconds)
        fire_at = self._pending.get(path, 0.0)
        if time.time() >= fire_at:
            self._pending.pop(path, None)
            try:
                await self.on_change(path, event_type, self.root_folder_id)
            except Exception:
                pass  # Don't crash the watcher thread

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._schedule(event.src_path, "created")

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._schedule(event.src_path, "modified")

    def on_moved(self, event: FileMovedEvent) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._schedule(event.dest_path, "moved")

    def on_deleted(self, event: FileDeletedEvent) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._schedule(event.src_path, "deleted")


class WatcherManager:
    """Manages one watchdog Observer per root folder."""

    def __init__(self) -> None:
        self._observers: dict[str, Observer] = {}

    def start(
        self,
        root_folder_id: str,
        path: str,
        on_change: Callable,
        settle_seconds: int = 2,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """Start watching a root folder. No-op if already watching."""
        if root_folder_id in self._observers:
            return

        observer = Observer()
        handler = MediaEventHandler(root_folder_id, on_change, settle_seconds, loop)
        observer.schedule(handler, path, recursive=True)
        observer.start()
        self._observers[root_folder_id] = observer

    def stop(self, root_folder_id: str) -> None:
        """Stop watching a root folder."""
        obs = self._observers.pop(root_folder_id, None)
        if obs:
            obs.stop()
            obs.join()

    def stop_all(self) -> None:
        """Stop all active observers."""
        for rfid in list(self._observers.keys()):
            self.stop(rfid)

    @property
    def active_roots(self) -> list[str]:
        """Return the list of root folder IDs currently being watched."""
        return list(self._observers.keys())


# Singleton instance used throughout the application
watcher_manager = WatcherManager()
