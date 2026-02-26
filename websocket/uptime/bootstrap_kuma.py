import os
import time
from typing import Any, Dict, List, Optional

from uptime_kuma_api import MonitorType, NotificationType, UptimeKumaApi


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default)).strip()


def _entities(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        out: List[Dict[str, Any]] = []
        for item in value.values():
            if isinstance(item, dict):
                out.append(item)
        return out
    return []


def _extract_id(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if isinstance(value, dict):
        for key in ("id", "monitorID", "monitorId", "notificationID", "notificationId"):
            raw = value.get(key)
            if isinstance(raw, int):
                return raw
            if isinstance(raw, str) and raw.isdigit():
                return int(raw)
    return None


def _wait_for_kuma(url: str, attempts: int = 60, delay_seconds: int = 5) -> None:
    last_err: Optional[Exception] = None
    for i in range(1, attempts + 1):
        try:
            with UptimeKumaApi(url):
                print(f"[kuma-bootstrap] Kuma reachable (attempt {i}/{attempts})")
                return
        except Exception as exc:  # pragma: no cover - network boot race
            last_err = exc
            print(f"[kuma-bootstrap] waiting Kuma ({i}/{attempts}): {exc}")
            time.sleep(delay_seconds)
    raise RuntimeError(f"Kuma not reachable at {url}: {last_err}")


def _find_by_name(items: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    for item in items:
        if str(item.get("name", "")).strip() == name:
            return item
    return None


def _ensure_notification(
    api: UptimeKumaApi,
    existing_notifications: List[Dict[str, Any]],
    payload: Dict[str, Any],
) -> None:
    name = str(payload.get("name", "")).strip()
    current = _find_by_name(existing_notifications, name)
    if current:
        nid = _extract_id(current)
        if nid is not None:
            api.edit_notification(id_=nid, **payload)
            print(f"[kuma-bootstrap] updated notification: {name}")
            return
    api.add_notification(**payload)
    print(f"[kuma-bootstrap] created notification: {name}")


def _ensure_monitor(
    api: UptimeKumaApi,
    existing_monitors: List[Dict[str, Any]],
    payload: Dict[str, Any],
) -> int:
    name = str(payload.get("name", "")).strip()
    current = _find_by_name(existing_monitors, name)
    if current:
        mid = _extract_id(current)
        if mid is not None:
            api.edit_monitor(id_=mid, **payload)
            print(f"[kuma-bootstrap] updated monitor: {name}")
            return mid
    created = api.add_monitor(**payload)
    new_id = _extract_id(created)
    if new_id is None:
        refreshed = _entities(api.get_monitors())
        created_item = _find_by_name(refreshed, name)
        new_id = _extract_id(created_item) if created_item else None
    if new_id is None:
        raise RuntimeError(f"Failed to resolve monitor id for: {name}")
    print(f"[kuma-bootstrap] created monitor: {name}")
    return new_id


def _ensure_status_page(
    api: UptimeKumaApi,
    slug: str,
    title: str,
    description: str,
    groups: List[Dict[str, Any]],
) -> None:
    pages = _entities(api.get_status_pages())
    exists = any(str(page.get("slug", "")).strip() == slug for page in pages)
    if not exists:
        api.add_status_page(slug=slug, title=title)
        print(f"[kuma-bootstrap] created status page: {slug}")

    api.save_status_page(
        slug=slug,
        title=title,
        description=description,
        icon="",
        theme="light",
        published=True,
        showTags=False,
        publicGroupList=groups,
    )
    print(f"[kuma-bootstrap] updated status page: {slug}")


def main() -> None:
    kuma_url = _env("UPTIME_KUMA_URL", "http://uptime-kuma:3001")
    username = _env("UPTIME_KUMA_USERNAME", "admin")
    password = _env("UPTIME_KUMA_PASSWORD", "change-me-now")
    status_slug = _env("UPTIME_STATUS_PAGE_SLUG", "osmo-status")
    status_title = _env("UPTIME_STATUS_PAGE_TITLE", "Osmo Status")
    status_description = _env(
        "UPTIME_STATUS_PAGE_DESCRIPTION",
        "Real-time status for Osmo backend services",
    )
    api_public_health_url = _env("UPTIME_API_PUBLIC_HEALTH_URL", "")
    frontend_public_url = _env("UPTIME_FRONTEND_PUBLIC_URL", "")
    discord_webhook = _env("UPTIME_DISCORD_WEBHOOK_URL", "")
    telegram_bot_token = _env("UPTIME_TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id = _env("UPTIME_TELEGRAM_CHAT_ID", "")
    generic_webhook = _env("UPTIME_WEBHOOK_URL", "")

    if password == "change-me-now":
        print("[kuma-bootstrap] WARNING: UPTIME_KUMA_PASSWORD still default value.")

    _wait_for_kuma(kuma_url)

    with UptimeKumaApi(kuma_url) as api:
        if api.need_setup():
            api.setup(username=username, password=password)
            print("[kuma-bootstrap] initial admin user created")

        api.login(username=username, password=password)
        print("[kuma-bootstrap] login success")

        notifications = _entities(api.get_notifications())
        if discord_webhook:
            _ensure_notification(
                api,
                notifications,
                {
                    "name": "Osmo Discord Alerts",
                    "type": NotificationType.DISCORD,
                    "isDefault": True,
                    "applyExisting": True,
                    "discordWebhookUrl": discord_webhook,
                },
            )
            notifications = _entities(api.get_notifications())

        if telegram_bot_token and telegram_chat_id:
            _ensure_notification(
                api,
                notifications,
                {
                    "name": "Osmo Telegram Alerts",
                    "type": NotificationType.TELEGRAM,
                    "isDefault": True,
                    "applyExisting": True,
                    "telegramBotToken": telegram_bot_token,
                    "telegramChatID": telegram_chat_id,
                },
            )
            notifications = _entities(api.get_notifications())

        if generic_webhook:
            _ensure_notification(
                api,
                notifications,
                {
                    "name": "Osmo Webhook Alerts",
                    "type": NotificationType.WEBHOOK,
                    "isDefault": True,
                    "applyExisting": True,
                    "webhookURL": generic_webhook,
                    "webhookContentType": "json",
                },
            )

        monitors = _entities(api.get_monitors())
        monitor_ids: Dict[str, int] = {}

        monitor_ids["kuma_ui"] = _ensure_monitor(
            api,
            monitors,
            {
                "type": MonitorType.HTTP,
                "name": "Uptime Kuma UI",
                "url": "http://uptime-kuma:3001",
                "interval": 60,
                "maxretries": 2,
                "retryInterval": 30,
            },
        )
        monitors = _entities(api.get_monitors())

        monitor_ids["api_internal"] = _ensure_monitor(
            api,
            monitors,
            {
                "type": MonitorType.HTTP,
                "name": "Backend API Health (internal)",
                "url": "http://backend:8000/health",
                "interval": 30,
                "maxretries": 3,
                "retryInterval": 30,
            },
        )
        monitors = _entities(api.get_monitors())

        monitor_ids["api_tcp"] = _ensure_monitor(
            api,
            monitors,
            {
                "type": MonitorType.PORT,
                "name": "Backend API TCP 8000",
                "hostname": "backend",
                "port": 8000,
                "interval": 30,
                "maxretries": 3,
                "retryInterval": 30,
            },
        )
        monitors = _entities(api.get_monitors())

        monitor_ids["redis_tcp"] = _ensure_monitor(
            api,
            monitors,
            {
                "type": MonitorType.PORT,
                "name": "Redis TCP 6379",
                "hostname": "redis",
                "port": 6379,
                "interval": 60,
                "maxretries": 3,
                "retryInterval": 30,
            },
        )
        monitors = _entities(api.get_monitors())

        monitor_ids["postgres_tcp"] = _ensure_monitor(
            api,
            monitors,
            {
                "type": MonitorType.PORT,
                "name": "Postgres TCP 5432",
                "hostname": "db",
                "port": 5432,
                "interval": 60,
                "maxretries": 3,
                "retryInterval": 30,
            },
        )
        monitors = _entities(api.get_monitors())

        if api_public_health_url:
            public_url = api_public_health_url
            if not public_url.endswith("/health"):
                public_url = public_url.rstrip("/") + "/health"
            monitor_ids["api_public"] = _ensure_monitor(
                api,
                monitors,
                {
                    "type": MonitorType.HTTP,
                    "name": "Backend API Health (public)",
                    "url": public_url,
                    "interval": 30,
                    "maxretries": 3,
                    "retryInterval": 30,
                },
            )
            monitors = _entities(api.get_monitors())

        if frontend_public_url:
            monitor_ids["frontend_public"] = _ensure_monitor(
                api,
                monitors,
                {
                    "type": MonitorType.HTTP,
                    "name": "Frontend Public",
                    "url": frontend_public_url,
                    "interval": 60,
                    "maxretries": 3,
                    "retryInterval": 30,
                },
            )

        core_monitor_list = [
            {"id": monitor_ids["api_internal"]},
            {"id": monitor_ids["api_tcp"]},
        ]
        if "api_public" in monitor_ids:
            core_monitor_list.append({"id": monitor_ids["api_public"]})

        infra_monitor_list = [
            {"id": monitor_ids["redis_tcp"]},
            {"id": monitor_ids["postgres_tcp"]},
            {"id": monitor_ids["kuma_ui"]},
        ]

        public_groups: List[Dict[str, Any]] = [
            {"name": "Core API", "weight": 1, "monitorList": core_monitor_list},
            {"name": "Infrastructure", "weight": 2, "monitorList": infra_monitor_list},
        ]
        if "frontend_public" in monitor_ids:
            public_groups.insert(
                1,
                {
                    "name": "Frontends",
                    "weight": 2,
                    "monitorList": [{"id": monitor_ids["frontend_public"]}],
                },
            )

        _ensure_status_page(
            api=api,
            slug=status_slug,
            title=status_title,
            description=status_description,
            groups=public_groups,
        )

        print(f"[kuma-bootstrap] done. Status page: /status/{status_slug}")


if __name__ == "__main__":
    main()
