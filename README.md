# Traeclaw Lite

本地轻量任务面板，代码全部放在 `code/` 下。

## 启动

```bash
python3 code/run.py serve
```

默认地址是 `http://127.0.0.1:8765`，默认数据库是 `code/data/traeclaw.sqlite3`。

## 常用命令

```bash
python3 code/run.py init-db
python3 code/run.py import-state
python3 code/run.py run-task cp.predict
python3 code/run.py run-task cp.check_result
python3 code/run.py run-task mfood.login_token
python3 code/run.py run-task mfood.shence_health
python3 code/run.py run-task mfood.order_monitor
python3 -m pytest code/tests -q
```

## 数据

应用自己的设置、任务运行记录、结构化结果都写入 `code/data/traeclaw.sqlite3`。启动时会把这些旧 SQLite 导入同一个库：

- `state/cp/doublecolor.db`
- `state/mfdb/maskphone_monitor.db`
- `state/scjk/shence_monitor.db`
- `scripts/tycp/data/dlt_history.sqlite3`

旧脚本本身不会被删除；新面板先把它们作为可见任务注册起来。CP 任务通过 `code/traeclaw/tasks/cp.py` 包装，运行时使用统一数据库。

## mFood

这三个本地 skill 已迁移成项目代码：

- `code/traeclaw/mfood/login.py`：mFood manager token 获取/刷新，底层浏览器请求脚本 vendored 在 `code/traeclaw/mfood/vendor/get_mfood_token.js`
- `code/traeclaw/mfood/shence.py`：mFood Sensors SQL 查询
- `code/traeclaw/mfood/order_monitor.py`：mFood Sensors 与管理后台完成订单对账

对应配置在网页右侧的 `mFood` 面板填写，保存到统一 SQLite。密钥类字段留空会保留已有值。
