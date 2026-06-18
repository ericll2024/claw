from __future__ import annotations

from typing import Any

from ..db import AppDatabase, mask_secret


SECTIONS: dict[str, dict[str, Any]] = {
    "login": {
        "fields": {
            "profile": False,
            "account": False,
            "password_md5": True,
        },
        "required": ("password_md5",),
    },
    "shence": {
        "fields": {
            "api_url": False,
            "sensors_api_key": True,
            "sensors_project": False,
        },
        "required": ("sensors_api_key", "sensors_project"),
    },
    "order_monitor": {
        "fields": {
            "monitoring_dir": False,
            "manager_account": False,
            "manager_password_md5": True,
            "sensors_api_key": True,
            "sensors_project": False,
            "takeout_threshold": False,
            "market_threshold": False,
            "timezone": False,
        },
        "required": (),
    },
}

DEFAULTS = {
    "shence.api_url": "https://shence-db-admin.mfoodapp.com",
    "shence.sensors_project": "production",
    "order_monitor.sensors_project": "production",
    "order_monitor.takeout_threshold": "300",
    "order_monitor.market_threshold": "300",
    "order_monitor.timezone": "Asia/Shanghai",
    "order_monitor.monitoring_dir": "/Users/eric/Documents/project/mfood/神策數據/monitoring",
}


class MFoodSettings:
    @staticmethod
    def save(db: AppDatabase, payload: dict[str, Any]) -> None:
        for section, spec in SECTIONS.items():
            values = payload.get(section) or {}
            if not isinstance(values, dict):
                continue
            for field, is_secret in spec["fields"].items():
                if field not in values:
                    continue
                raw = values.get(field)
                value = "" if raw is None else str(raw).strip()
                if is_secret and not value:
                    continue
                db.set_setting(_key(section, field), value, is_secret=is_secret)

    @staticmethod
    def load_private(db: AppDatabase) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for section, spec in SECTIONS.items():
            section_values: dict[str, Any] = {}
            for field in spec["fields"]:
                default = DEFAULTS.get(f"{section}.{field}", "")
                section_values[field] = db.get_setting(_key(section, field), default)
            section_values["configured"] = all(section_values.get(field) for field in spec["required"])
            result[section] = section_values
        return result

    @staticmethod
    def load_public(db: AppDatabase) -> dict[str, dict[str, Any]]:
        private = MFoodSettings.load_private(db)
        result: dict[str, dict[str, Any]] = {}
        for section, spec in SECTIONS.items():
            values: dict[str, Any] = {}
            for field, value in private[section].items():
                if field == "configured":
                    values[field] = value
                elif spec["fields"].get(field):
                    values[field] = mask_secret(str(value))
                    values[f"{field}_configured"] = bool(value)
                else:
                    values[field] = value
            result[section] = values
        return result


def _key(section: str, field: str) -> str:
    return f"mfood.{section}.{field}"
