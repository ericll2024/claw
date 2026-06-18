from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..db import AppDatabase
from .config import MFoodSettings


class MFoodOrderMonitor:
    def __init__(self, db: AppDatabase):
        self.db = db

    def run(
        self,
        target_date: str = "",
        start_date: str = "",
        end_date: str = "",
        export_order_diff_md: bool = False,
        output_dir: str = "",
    ) -> dict[str, Any]:
        mfood_all = MFoodSettings.load_private(self.db)
        settings = mfood_all["order_monitor"]
        login_settings = mfood_all["login"]
        shence_settings = mfood_all["shence"]

        # Helper to get custom non-default settings
        def get_custom_setting(key, default_val=""):
            val = settings.get(key, "")
            return val if val and val != default_val else ""

        manager_account = (
            os.environ.get("MFOOD_MANAGER_ACCOUNT") or 
            os.environ.get("MFOOD_ACCOUNT") or
            login_settings.get("account") or
            get_custom_setting("manager_account")
        )

        manager_password_md5 = (
            os.environ.get("MFOOD_MANAGER_PASSWORD_MD5") or 
            os.environ.get("MFOOD_PASSWORD_MD5") or
            login_settings.get("password_md5") or
            get_custom_setting("manager_password_md5")
        )

        sensors_api_key = (
            os.environ.get("MFOOD_SENSORS_API_KEY") or
            shence_settings.get("sensors_api_key") or
            get_custom_setting("sensors_api_key")
        )

        sensors_project = (
            os.environ.get("MFOOD_SENSORS_PROJECT") or
            shence_settings.get("sensors_project") or 
            get_custom_setting("sensors_project", "production") or
            "production"
        )

        monitoring_dir_val = (
            os.environ.get("MFOOD_MONITORING_DIR") or
            get_custom_setting("monitoring_dir", "/Users/eric/Documents/project/mfood/神策數據/monitoring") or
            "/Users/eric/Documents/project/mfood/神策數據/monitoring"
        )

        timezone_val = (
            os.environ.get("MFOOD_TIMEZONE") or
            get_custom_setting("timezone", "Asia/Shanghai") or
            "Asia/Shanghai"
        )

        if not manager_account or not manager_password_md5 or not sensors_api_key:
            raise RuntimeError("mFood 订单对账配置缺失：请填写 mFood 登录密码、神策 API Key 或設置對應環境變量")

        monitoring_dir = Path(monitoring_dir_val).expanduser().resolve()
        if not monitoring_dir.exists():
            raise RuntimeError(f"mFood monitoring 目录不存在：{monitoring_dir}")

        if str(monitoring_dir) not in sys.path:
            sys.path.insert(0, str(monitoring_dir))
        from openclaw_monitor import OpenClawCredentials, OpenClawDailyMonitor, OpenClawMonitorOptions

        credentials = OpenClawCredentials(
            sensors_api_key=sensors_api_key,
            sensors_project=sensors_project,
            manager_account=manager_account,
            manager_password_md5=manager_password_md5,
        )
        options = OpenClawMonitorOptions(
            timezone=timezone_val,
            start_date=None,
            end_date=None,
            takeout_finished_order_threshold=Decimal(str(settings.get("takeout_threshold") or "300")),
            market_finished_order_threshold=Decimal(str(settings.get("market_threshold") or "300")),
        )
        monitor = OpenClawDailyMonitor(credentials=credentials, options=options)
        if export_order_diff_md:
            reporter = monitor.build_order_diff_reporter()
            results = reporter.run(target_date=target_date or None, start_date=start_date or None, end_date=end_date or None)
            paths = reporter.write_results(results, output_dir=output_dir or None)
            return {
                "mode": "order_diff",
                "results": [result.to_dict() for result in results],
                "files": [str(path) for path in paths],
            }
        report = monitor.run(target_date=target_date or None, start_date=start_date or None, end_date=end_date or None)
        return report.to_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run mFood order monitor through Traeclaw config")
    parser.add_argument("--date", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--export-order-diff-md", action="store_true")
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args(argv)
    root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT", Path(__file__).resolve().parents[3])).resolve()
    db_path = Path(os.environ.get("TRAECLAW_DB_PATH", root / "code" / "data" / "traeclaw.sqlite3"))
    db = AppDatabase(db_path)
    db.initialize()
    try:
        result = MFoodOrderMonitor(db).run(
            target_date=args.date,
            start_date=args.start_date,
            end_date=args.end_date,
            export_order_diff_md=args.export_order_diff_md,
            output_dir=args.output_dir,
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
