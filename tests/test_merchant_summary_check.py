import json
import pytest
from unittest.mock import patch, MagicMock
import sqlite3

import scripts.mFood.merchant_summary_check as msc


def test_merchant_summary_check_with_store_ids_filtering(tmp_path, monkeypatch):
    # Setup temporary paths
    monkeypatch.setattr(msc, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(msc, "DB_PATH", str(tmp_path / "maskphone_monitor.db"))
    monkeypatch.setattr(msc, "CONFIG_PATH", str(tmp_path / "merchant_summary_check_config.json"))

    # Config with specific store_ids under payload
    config_data = {
        "root_x_merchant": "root_merch_123",
        "token_profile": "default",
        "payload": {
            "storeIds": ["store_match_1"]
        }
    }
    with open(msc.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f)

    # Mock get_login_token
    monkeypatch.setattr(msc, "get_login_token", lambda profile: "mock_token_abc")

    # Yesterday's date string
    yesterday = msc.yesterday_str()

    # Mock responses for post_json
    # Root response (discovers stores)
    root_resp = {
        "result": [
            {
                "merchantId": "merchant_1",
                "storeId": "store_match_1",
                "storeName": "Matched Store"
            },
            {
                "merchantId": "merchant_2",
                "storeId": "store_skipped_2",
                "storeName": "Skipped Store"
            }
        ]
    }

    # Merchant response containing yesterday's details
    merchant_1_resp = {
        "result": {
            "records": [
                {
                    "merchantId": "merchant_1",
                    "storeId": "store_match_1",
                    "storeName": "Matched Store",
                    "details": [
                        {
                            "dateStr": yesterday + " 12:00:00",
                            "storeReceiveAmtn": "100.00",
                            "subsidyStoreReceiveAmtn": "0.00",
                            "subsidyStoreReceiveAmtnNew": "0.00"
                        }
                    ]
                }
            ]
        }
    }

    # We mock post_json to return root_resp, then merchant_1_resp, and review response
    mock_post_json = MagicMock()
    
    def side_effect(headers, payload, url=None):
        merchant_id = headers.get("x-merchant")
        if url == msc.REVIEW_URL:
            # Review order response
            return {"total": 1, "result": [{"orderId": "order_1"}]}
        if merchant_id == "root_merch_123":
            return root_resp
        elif merchant_id == "merchant_1":
            return merchant_1_resp
        raise ValueError(f"Unexpected merchant_id {merchant_id} in mock")

    mock_post_json.side_effect = side_effect
    monkeypatch.setattr(msc, "post_json", mock_post_json)

    # Run main
    exit_code = msc.main()

    # The matched store has subsidyStoreReceiveAmtn: 0.00, and review_has_orders returns True (has_issue = True)
    # Status should be 'alert' because of the issue, which returns exit code 1
    assert exit_code == 1

    # Verify runs database
    conn = sqlite3.connect(msc.DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT checked_store_count, issue_count, status FROM merchant_summary_runs")
    run = cur.fetchone()
    # It should only check 1 store (store_match_1) since store_skipped_2 is skipped
    assert run[0] == 1  # checked_store_count
    assert run[1] == 1  # issue_count
    assert run[2] == "alert"  # status
    conn.close()


def test_merchant_summary_check_with_merchant_ids_filtering(tmp_path, monkeypatch):
    # Setup temporary paths
    monkeypatch.setattr(msc, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(msc, "DB_PATH", str(tmp_path / "maskphone_monitor.db"))
    monkeypatch.setattr(msc, "CONFIG_PATH", str(tmp_path / "merchant_summary_check_config.json"))

    # Config with specific merchant ID under payload's storeIds (as clarified by the user)
    config_data = {
        "root_x_merchant": "root_merch_123",
        "token_profile": "default",
        "payload": {
            "storeIds": ["merchant_1"]
        }
    }
    with open(msc.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f)

    # Mock get_login_token
    monkeypatch.setattr(msc, "get_login_token", lambda profile: "mock_token_abc")

    # Yesterday's date string
    yesterday = msc.yesterday_str()

    # Mock responses for post_json
    # Root response (discovers stores)
    root_resp = {
        "result": [
            {
                "merchantId": "merchant_1",
                "storeId": "store_match_1",
                "storeName": "Matched Store"
            },
            {
                "merchantId": "merchant_2",
                "storeId": "store_skipped_2",
                "storeName": "Skipped Store"
            }
        ]
    }

    # Merchant response containing yesterday's details
    merchant_1_resp = {
        "result": {
            "records": [
                {
                    "merchantId": "merchant_1",
                    "storeId": "store_match_1",
                    "storeName": "Matched Store",
                    "details": [
                        {
                            "dateStr": yesterday + " 12:00:00",
                            "storeReceiveAmtn": "100.00",
                            "subsidyStoreReceiveAmtn": "0.00",
                            "subsidyStoreReceiveAmtnNew": "0.00"
                        }
                    ]
                }
            ]
        }
    }

    # We mock post_json
    mock_post_json = MagicMock()
    
    def side_effect(headers, payload, url=None):
        merchant_id = headers.get("x-merchant")
        if url == msc.REVIEW_URL:
            # Review order response
            return {"total": 1, "result": [{"orderId": "order_1"}]}
        if merchant_id == "root_merch_123":
            return root_resp
        elif merchant_id == "merchant_1":
            return merchant_1_resp
        raise ValueError(f"Unexpected merchant_id {merchant_id} in mock")

    mock_post_json.side_effect = side_effect
    monkeypatch.setattr(msc, "post_json", mock_post_json)

    # Run main
    exit_code = msc.main()

    assert exit_code == 1

    # Verify runs database
    conn = sqlite3.connect(msc.DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT checked_store_count, issue_count, status FROM merchant_summary_runs")
    run = cur.fetchone()
    # It should check 1 store belonging to merchant_1
    assert run[0] == 1  # checked_store_count
    assert run[1] == 1  # issue_count
    assert run[2] == "alert"  # status
    conn.close()
