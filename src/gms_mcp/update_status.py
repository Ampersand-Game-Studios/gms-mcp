from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .update_notifier import check_for_updates


@dataclass(frozen=True)
class UpdateStatus:
    status: str
    message: str
    current_version: str
    latest_version: str
    source: str | None
    url: str | None
    checked_at: str | None
    used_cache: bool
    last_notified_at: str | None
    notification_due: bool
    update_available: bool
    upgrade_command: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "UpdateStatus":
        return cls(
            status=str(payload.get("status") or "unknown"),
            message=str(payload.get("message") or ""),
            current_version=str(payload.get("current_version") or "0.0.0"),
            latest_version=str(payload.get("latest_version") or payload.get("current_version") or "0.0.0"),
            source=payload.get("source") if isinstance(payload.get("source"), str) else None,
            url=payload.get("url") if isinstance(payload.get("url"), str) else None,
            checked_at=payload.get("checked_at") if isinstance(payload.get("checked_at"), str) else None,
            used_cache=bool(payload.get("used_cache")),
            last_notified_at=payload.get("last_notified_at")
            if isinstance(payload.get("last_notified_at"), str)
            else None,
            notification_due=bool(payload.get("notification_due")),
            update_available=bool(payload.get("update_available")),
            upgrade_command=str(payload.get("upgrade_command") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "source": self.source,
            "url": self.url,
            "checked_at": self.checked_at,
            "used_cache": self.used_cache,
            "last_notified_at": self.last_notified_at,
            "notification_due": self.notification_due,
            "update_available": self.update_available,
            "upgrade_command": self.upgrade_command,
        }

    def to_notification_record(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "latest_version": self.latest_version,
            "source": self.source,
            "url": self.url,
            "checked_at": self.checked_at,
            "current_version": self.current_version,
        }


def get_update_status(*, force_refresh: bool = False) -> UpdateStatus:
    return UpdateStatus.from_payload(check_for_updates(force_refresh=force_refresh))
