import sqlite3
from pathlib import Path

DB_PATH = Path('/home/eric/Documents/workspace/state/tycp/data/dlt_history.sqlite3')
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.executescript('''
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dlt_results (
    draw_num TEXT PRIMARY KEY,
    draw_time TEXT NOT NULL,
    front_1 TEXT NOT NULL,
    front_2 TEXT NOT NULL,
    front_3 TEXT NOT NULL,
    front_4 TEXT NOT NULL,
    front_5 TEXT NOT NULL,
    back_1 TEXT NOT NULL,
    back_2 TEXT NOT NULL,
    raw_result TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dlt_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draw_num TEXT NOT NULL,
    plan_time TEXT NOT NULL,
    budget REAL NOT NULL,
    strategy_model TEXT NOT NULL,
    front_core TEXT,
    front_secondary TEXT,
    back_core TEXT,
    main_ticket_type TEXT,
    main_front TEXT,
    main_back TEXT,
    singles_count INTEGER DEFAULT 0,
    singles_detail TEXT,
    logic_text TEXT,
    version TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(draw_num, plan_time)
);

CREATE TABLE IF NOT EXISTS dlt_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    draw_num TEXT NOT NULL,
    ticket_type TEXT NOT NULL,
    ticket_label TEXT,
    front_1 TEXT NOT NULL,
    front_2 TEXT NOT NULL,
    front_3 TEXT NOT NULL,
    front_4 TEXT NOT NULL,
    front_5 TEXT NOT NULL,
    back_1 TEXT NOT NULL,
    back_2 TEXT NOT NULL,
    is_additional INTEGER DEFAULT 0,
    cost REAL DEFAULT 2,
    hit_front_count INTEGER,
    hit_back_count INTEGER,
    prize_level TEXT,
    prize_amount REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(plan_id) REFERENCES dlt_plans(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dlt_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draw_num TEXT NOT NULL,
    review_time TEXT NOT NULL,
    plan_id INTEGER,
    top_prize_level TEXT,
    prize_amount REAL DEFAULT 0,
    main_hit_summary TEXT,
    ref_hit_summary TEXT,
    comparison_text TEXT,
    miss_reason TEXT,
    fix_direction TEXT,
    review_text TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(plan_id) REFERENCES dlt_plans(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_dlt_results_draw_time ON dlt_results(draw_time);
CREATE INDEX IF NOT EXISTS idx_dlt_plans_draw_num ON dlt_plans(draw_num);
CREATE INDEX IF NOT EXISTS idx_dlt_tickets_plan_id ON dlt_tickets(plan_id);
CREATE INDEX IF NOT EXISTS idx_dlt_tickets_draw_num ON dlt_tickets(draw_num);
CREATE INDEX IF NOT EXISTS idx_dlt_reviews_draw_num ON dlt_reviews(draw_num);
''')

exists = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dlt_history'").fetchone()
if exists:
    cur.execute('''
    INSERT OR IGNORE INTO dlt_results (
        draw_num, draw_time, front_1, front_2, front_3, front_4, front_5, back_1, back_2, raw_result
    )
    SELECT lottery_draw_num, lottery_draw_time, front_1, front_2, front_3, front_4, front_5, back_1, back_2, lottery_draw_result
    FROM dlt_history
    ''')

conn.commit()
for table in ['dlt_results', 'dlt_plans', 'dlt_tickets', 'dlt_reviews']:
    count = cur.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    print(f'{table}: {count}')
conn.close()
print(f'OK: {DB_PATH}')
