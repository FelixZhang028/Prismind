"""管理后台：最近 30 天注册的新用户，多久跑出第一个结果。"""

from datetime import datetime, timezone

from app import database
from app.routes import admin

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def test_new_users_and_their_first_result(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "app.db"))
    database.init_db()
    with database.get_conn() as conn:
        users = [  # (id, 注册时间, 是不是管理员)
            (1, "2026-10-29T10:00:00+00:00", 0),   # 10 分钟后跑了事件研究，后来又回测
            (2, "2026-10-29T10:00:00+00:00", 0),   # 3 小时后才有一次完成的回测；失败的那次不算
            (3, "2026-10-29T10:00:00+00:00", 0),   # 什么都没做
            (4, "2026-08-01T10:00:00+00:00", 0),   # 30 天以前注册，不算
            (5, "2026-10-29T10:00:00+00:00", 1),   # 管理员不算
            (6, "2026-10-29T10:00:00+00:00", 0),   # 30 分钟后用了 AI 研究员
        ]
        for uid, joined, is_admin in users:
            conn.execute("INSERT INTO users (id, name, email, password_hash, salt, created_at, is_admin) VALUES (?, 'u', ?, 'h', 's', ?, ?)",
                         (uid, f"u{uid}@example.test", joined, is_admin))
        conn.execute("INSERT INTO user_milestones (user_id, kind, at) VALUES (1, 'event_study', '2026-10-29T10:10:00+00:00')")
        conn.execute("INSERT INTO user_milestones (user_id, kind, at) VALUES (5, 'event_study', '2026-10-29T10:01:00+00:00')")
        for uid, status, at in ((1, '完成', '2026-10-29T11:00:00+00:00'), (2, '失败', '2026-10-29T10:05:00+00:00'),
                                (2, '完成', '2026-10-29T13:00:00+00:00'), (4, '完成', '2026-10-29T10:00:00+00:00')):
            conn.execute("INSERT INTO backtests (user_id, strategy, market, from_date, to_date, status, result, created_at) "
                         "VALUES (?, 's', 'A股', '2025-01-01', '2025-12-31', ?, '{}', ?)", (uid, status, at))
        conn.execute("INSERT INTO stock_briefs (id, user_id, symbol, name, trade_date, facts, created_at) "
                     "VALUES ('b1', 6, '600000.SH', 'x', '2026-10-28', '{}', '2026-10-29T10:30:00+00:00')")
        stats = admin._first_results(conn, now=NOW)
    # 新用户 1、2、3、6；跑出结果的 1（10 分钟）、2（180 分钟）、6（30 分钟）
    assert stats == {"days": 30, "new_users": 4, "with_result": 3, "within_hour": 2, "median_minutes": 30.0}


def test_no_new_users(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "app.db"))
    database.init_db()
    with database.get_conn() as conn:
        assert admin._first_results(conn, now=NOW) == {"days": 30, "new_users": 0, "with_result": 0,
                                                       "within_hour": 0, "median_minutes": None}
