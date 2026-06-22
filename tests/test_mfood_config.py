from traeclaw.db import AppDatabase
from traeclaw.mfood.config import MFoodSettings


def test_mfood_settings_round_trip_masks_secret_values(tmp_path):
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()

    MFoodSettings.save(
        db,
        {
            "login": {
                "profile": "default",
                "account": "manager-a",
                "password_md5": "0123456789abcdef0123456789abcdef",
            },
            "shence": {
                "api_url": "https://shence-db-admin.mfoodapp.com",
                "sensors_api_key": "sensors-secret-key",
                "sensors_project": "production",
            },
            "order_monitor": {
                "monitoring_dir": "/tmp/monitoring",
                "manager_account": "manager-a",
                "manager_password_md5": "abcdefabcdefabcdefabcdefabcdefab",
                "sensors_api_key": "monitor-secret-key",
                "sensors_project": "production",
                "takeout_threshold": "300",
                "market_threshold": "300",
                "timezone": "Asia/Shanghai",
            },
        },
    )

    public = MFoodSettings.load_public(db)
    private = MFoodSettings.load_private(db)

    assert public["login"]["configured"] is True
    assert public["login"]["password_md5"] == "************cdef"
    assert public["shence"]["sensors_api_key"] == "************-key"
    assert public["order_monitor"]["manager_password_md5"] == "************efab"
    assert private["login"]["password_md5"] == "0123456789abcdef0123456789abcdef"
    assert private["order_monitor"]["takeout_threshold"] == "300"





def test_mfood_order_monitor_fallback_logic(tmp_path, monkeypatch):
    import sys
    from unittest.mock import MagicMock
    
    # Create a dummy monitor directory to bypass existence checks
    dummy_monitor_dir = tmp_path / "dummy_monitor"
    dummy_monitor_dir.mkdir()
    
    # Mock openclaw_monitor module
    mock_openclaw = MagicMock()
    sys.modules["openclaw_monitor"] = mock_openclaw
    
    from traeclaw.mfood.order_monitor import MFoodOrderMonitor
    
    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()
    
    # 1. Save only threshold values, without login credentials or shence keys
    MFoodSettings.save(
        db,
        {
            "order_monitor": {
                "takeout_threshold": "100",
                "market_threshold": "200",
            }
        }
    )
    
    monitor = MFoodOrderMonitor(db)
    
    # Calling run() without configuration and environment variables should raise RuntimeError
    import pytest
    with pytest.raises(RuntimeError) as excinfo:
        monkeypatch.setenv("MFOOD_MONITORING_DIR", str(dummy_monitor_dir))
        monitor.run()
    assert "mFood 订单对账配置缺失" in str(excinfo.value)
    
    # 2. Add login settings and shence settings to enable cross-section fallback
    MFoodSettings.save(
        db,
        {
            "login": {
                "account": "login-user",
                "password_md5": "login-pass-md5-dummy-hash-value-12345",
            },
            "shence": {
                "sensors_api_key": "shence-api-key-value",
                "sensors_project": "shence-project-name",
            }
        }
    )
    
    # Mock OpenClawDailyMonitor execution
    mock_monitor_instance = MagicMock()
    mock_openclaw.OpenClawDailyMonitor.return_value = mock_monitor_instance
    mock_monitor_instance.run.return_value.to_dict.return_value = {"status": "ok"}
    
    res = monitor.run()
    assert res.get("status") == "ok"
    assert "summary_text" in res
    
    # Verify OpenClawCredentials parameters retrieved from other settings sections
    mock_openclaw.OpenClawCredentials.assert_called_once_with(
        sensors_api_key="shence-api-key-value",
        sensors_project="shence-project-name",
        manager_account="login-user",
        manager_password_md5="login-pass-md5-dummy-hash-value-12345",
    )
    
    # Verify OpenClawMonitorOptions thresholds are correctly converted
    mock_openclaw.OpenClawMonitorOptions.assert_called_once()
    _, kwargs = mock_openclaw.OpenClawMonitorOptions.call_args
    from decimal import Decimal
    assert kwargs["takeout_finished_order_threshold"] == Decimal("100")
    assert kwargs["market_finished_order_threshold"] == Decimal("200")


