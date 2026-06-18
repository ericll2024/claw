import json
from traeclaw.runner import _parse_json, summarize_output

def test_parse_json_robust():
    # Plain JSON
    assert _parse_json('{"a": 1}') == {"a": 1}
    # JSON with surrounding whitespace
    assert _parse_json('\n  {"a": 1} \n') == {"a": 1}
    # JSON with leading text/debug logs
    assert _parse_json('some debug logs\n{"a": 1}') == {"a": 1}
    # JSON with trailing text/debug logs
    assert _parse_json('{"a": 1}\nDone.') == {"a": 1}
    # Pretty printed JSON with debug logs
    assert _parse_json('debug\n{\n  "a": 1\n}\ninfo') == {"a": 1}
    # Invalid JSON
    assert _parse_json('{"a": 1') is None

def test_summarize_output_dlt_fetch():
    stdout = '{"inserted": 1, "updated": 2, "db_total": 100, "latest": ["26065 2026-06-17 | 前区 01,02,03,04,05 | 后区 06,07"]}'
    res = summarize_output(stdout, "", "success")
    assert "拉取完成" in res
    assert "新增 1 条" in res
    assert "更新 2 条" in res
    assert "共 100 条" in res
    assert "最新一期: 26065" in res

def test_summarize_output_dlt_recommend():
    stdout = '{"recommendations": [{"front": "01 02 03 04 05", "back": "06 07", "score": 10}]}'
    res = summarize_output(stdout, "", "success")
    assert "推荐方案已生成" in res
    assert "01 02 03 04 05 + 06 07" in res

def test_summarize_output_dlt_prize_check():
    stdout = '{"draw_num": "26065", "prize_level": "一等奖", "prize_amount": 10000000}'
    res = summarize_output(stdout, "", "success")
    assert "第 26065 期中奖检查" in res
    assert "一等奖" in res
    assert "奖金 10000000 元" in res

def test_summarize_output_fallback():
    # Plain text fallback
    assert summarize_output("plain output line 1\nline 2", "", "success") == "line 2"


def test_initialize_chat_titles_bg(tmp_path):
    from unittest.mock import patch, MagicMock
    from traeclaw.db import AppDatabase
    from traeclaw.telegram import initialize_chat_titles_bg
    import time

    db = AppDatabase(tmp_path / "app.sqlite3")
    db.initialize()
    db.set_setting("telegram.bot_token", "test-token")
    db.set_setting("telegram.chat_id", "-10099")

    # Mock urllib.request.urlopen to return mock chat response
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = json.dumps({
        "ok": True,
        "result": {
            "id": -10099,
            "title": "Mock Chat Group",
            "type": "group"
        }
    }).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        initialize_chat_titles_bg(db)
        
        # Wait a short moment for the background thread to finish
        for _ in range(20):
            titles = db.get_latest_chat_titles()
            if "-10099" in titles:
                break
            time.sleep(0.05)
            
        titles = db.get_latest_chat_titles()
        assert "-10099" in titles
        assert titles["-10099"] == "Mock Chat Group"
