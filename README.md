# claw

本地轻量任务面板，项目根目录就是当前这个 `code/` 仓库。

## 启动

```bash
python3 run.py serve
```

默认地址是 `http://127.0.0.1:8765`，默认数据库是 `data/traeclaw.sqlite3`。

## 常用命令

```bash
python3 run.py init-db
python3 run.py import-state
python3 run.py run-task cp.predict
python3 run.py run-task cp.check_result
python3 run.py run-task mfood.order_monitor
python3 -m pytest tests -q
```

## 数据

应用自己的设置、任务运行记录、结构化结果都写入 `data/traeclaw.sqlite3`。启动时会把这些旧 SQLite 导入同一个库：

- `state/cp/doublecolor.db`
- `state/mfdb/maskphone_monitor.db`
- `state/scjk/shence_monitor.db`
- `scripts/tycp/data/dlt_history.sqlite3`

旧脚本本身不会被删除；新面板先把它们作为可见任务注册起来。CP 任务通过 `traeclaw/tasks/cp.py` 包装，运行时使用统一数据库。

## mFood

这三个本地 skill 已迁移成项目代码：

- `traeclaw/mfood/login.py`：mFood manager token 获取/刷新，底层浏览器请求脚本 vendored 在 `traeclaw/mfood/vendor/get_mfood_token.js`
- `traeclaw/mfood/shence.py`：神策查询模块（供订单对账使用）
- `traeclaw/mfood/order_monitor.py`：mFood Sensors 与管理后台完成订单对账

对应配置在网页右侧的 `mFood` 面板填写，保存到统一 SQLite。密钥类字段留空会保留已有值。
