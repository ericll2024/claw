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
        try:
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
                get_custom_setting("monitoring_dir")
            )
            if not monitoring_dir_val:
                monitoring_dir_val = "/Users/eric/Documents/project/code/sensorsdata_monitor/monitoring"
                if not os.path.exists(monitoring_dir_val):
                    monitoring_dir_val = "/Users/eric/Documents/project/mfood/神策數據/monitoring"
            else:
                if not os.path.exists(monitoring_dir_val):
                    workspace_dir = "/Users/eric/Documents/project/code/sensorsdata_monitor/monitoring"
                    if os.path.exists(workspace_dir):
                        monitoring_dir_val = workspace_dir

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
            # Try to load thresholds from the external configuration file first
            config_path = Path("state/mfdb/order_monitor_config.json")
            ext_takeout_threshold = None
            ext_market_threshold = None
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        ext_config = json.load(f)
                        ext_takeout_threshold = ext_config.get("takeout_threshold")
                        ext_market_threshold = ext_config.get("market_threshold")
                except Exception:
                    pass

            takeout_threshold_val = (
                str(ext_takeout_threshold) if ext_takeout_threshold is not None else
                settings.get("takeout_threshold") or "300"
            )
            market_threshold_val = (
                str(ext_market_threshold) if ext_market_threshold is not None else
                settings.get("market_threshold") or "300"
            )

            options = OpenClawMonitorOptions(
                timezone=timezone_val,
                start_date=None,
                end_date=None,
                takeout_finished_order_threshold=Decimal(str(takeout_threshold_val)),
                market_finished_order_threshold=Decimal(str(market_threshold_val)),
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
            report_dict = report.to_dict()

            # Build custom summary report format
            takeout_result = None
            market_result = None
            for result in report.results:
                if result.name == "finished_order_count_check":
                    takeout_result = result
                elif result.name == "mall_finish_order_count_check":
                    market_result = result

            def fmt_dec(val):
                if val is None:
                    return "-"
                return str(int(val)) if val == val.to_integral() else str(val.normalize())

            takeout_status = "正常"
            takeout_shence = "-"
            takeout_backend = "-"
            if takeout_result:
                if takeout_result.status == "alert":
                    takeout_status = f"異常 (雙端差值 {fmt_dec(takeout_result.diff)} 超出閥值 {fmt_dec(takeout_result.threshold)})"
                elif takeout_result.status == "ok":
                    takeout_status = "正常"
                elif takeout_result.status == "error":
                    takeout_status = f"異常 (執行失敗: {takeout_result.error})"
                else:
                    takeout_status = f"異常 ({takeout_result.status})"
                
                takeout_shence = fmt_dec(takeout_result.left_value)
                takeout_backend = fmt_dec(takeout_result.right_value)

            market_status = "正常"
            market_shence = "-"
            market_backend = "-"
            if market_result:
                if market_result.status == "alert":
                    market_status = f"異常 (雙端差值 {fmt_dec(market_result.diff)} 超出閥值 {fmt_dec(market_result.threshold)})"
                elif market_result.status == "ok":
                    market_status = "正常"
                elif market_result.status == "error":
                    market_status = f"異常 (執行失敗: {market_result.error})"
                else:
                    market_status = f"異常 ({market_result.status})"
                
                market_shence = fmt_dec(market_result.left_value)
                market_backend = fmt_dec(market_result.right_value)

            # Extract abnormal order IDs only if threshold is exceeded (status == "alert")
            abnormal_lines = []
            if (takeout_result and takeout_result.status == "alert") or (market_result and market_result.status == "alert"):
                try:
                    diff_reports = monitor.run_order_diff_reports(
                        target_date=target_date or None,
                        start_date=start_date or None,
                        end_date=end_date or None
                    )
                    for diff_res in diff_reports:
                        category = "外賣" if diff_res.event_name == "FinishedOrder" else "超市"
                        is_abnormal = (
                            (category == "外賣" and takeout_result and takeout_result.status == "alert") or
                            (category == "超市" and market_result and market_result.status == "alert")
                        )
                        if is_abnormal:
                            if diff_res.only_in_sensors:
                                abnormal_lines.append(f"- {category}只在神策: " + ", ".join(diff_res.only_in_sensors))
                            if diff_res.only_in_backend:
                                backend_ids = [item.order_id for item in diff_res.only_in_backend]
                                abnormal_lines.append(f"- {category}只在後臺: " + ", ".join(backend_ids))
                except Exception as e:
                    abnormal_lines.append(f"獲取異常訂單明細失敗: {e}")

            if not abnormal_lines:
                abnormal_lines.append("无")

            abnormal_orders_str = "\n".join(abnormal_lines)

            summary_text = (
                f"外賣：{takeout_status}\n"
                f"神策：{takeout_shence}，管理後臺：{takeout_backend}\n"
                f"超市：{market_status}\n"
                f"神策：{market_shence}，管理後臺：{market_backend}\n"
                f"異常訂單：\n"
                f"{abnormal_orders_str}"
            )

            report_dict["summary_text"] = summary_text
            return report_dict
        except Exception as exc:
            if isinstance(exc, RuntimeError) and ("配置缺失" in str(exc) or "目录不存在" in str(exc)):
                raise exc
            import traceback
            tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
            tb_text = "".join(tb_lines[-4:])
            summary_text = (
                f"外賣：異常 (對賬任務執行出錯)\n"
                f"超市：異常 (對賬任務執行出錯)\n"
                f"異常日誌：\n{str(exc)}\n{tb_text.strip()}"
            )
            return {
                "status": "error",
                "error": str(exc),
                "summary_text": summary_text
            }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run mFood order monitor through Traeclaw config")
    parser.add_argument("--date", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--export-order-diff-md", action="store_true")
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args(argv)
    root = Path(os.environ.get("TRAECLAW_PROJECT_ROOT", Path(__file__).resolve().parents[3])).resolve()
    db_path = Path(os.environ.get("TRAECLAW_DB_PATH", root / "data" / "traeclaw.sqlite3"))
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
        if result.get("status") == "error":
            print(json.dumps(result, ensure_ascii=False))
            return 1
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
