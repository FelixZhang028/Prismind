"""用户反馈：随时提的建议、第一次出结果后“有用吗”、注销时匿名的离开原因。

三种都存在 ``feedback`` 表里，用 ``kind`` 区分：
- suggestion：一句话建议，自动记下是在哪个页面提的；用户可以勾选“可以用注册邮箱联系我”；
- useful：事件研究、策略回测、AI 个股分析第一次出结果后问一次，每人每个功能只有一条（可以补一句“哪里可以更好”）；
- leave：注销账户时选的原因，不记是谁（user_id 为空），账户删了以后还能统计。

管理员在后台看列表、标记已读或已处理、写备注，并看汇总：未读建议、各功能“有用”的比例、离开原因的分布。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ..database import get_conn

KINDS = {"suggestion": "建议", "useful": "有用吗", "leave": "离开原因"}
STATUSES = {"new": "新的", "read": "已读", "done": "已处理"}
# 第一次出结果后问“有用吗”的功能（页面 key -> 名字）
USEFUL_FEATURES = {"event-study": "事件研究", "backtest-review": "策略回测", "agent-lab": "AI 个股分析"}
LEAVE_REASONS = {"unused": "用不上", "hard": "太难用", "data": "数据不够", "trust": "结果不可信", "other": "其他"}
TEXT_MAX = 500
LEAVE_TEXT_MAX = 200
NOTE_MAX = 300
CONTEXT_MAX = 1000          # 序列化以后的字符数
SUMMARY_DAYS = 30
_VIEW = re.compile(r"^[a-z][a-z-]{0,39}$")


class FeedbackError(ValueError):
    """用户或管理员能改正的错误，原话显示在页面上。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _view(view: str) -> str:
    view = str(view or "").strip()
    if view and not _VIEW.match(view):
        raise FeedbackError("页面名称不正确")
    return view


def _context(context: dict[str, Any] | None) -> str:
    """补充信息（例如是哪一次回测），只收简单的值，太长就不要了。"""

    clean = {str(k)[:40]: v for k, v in (context or {}).items() if isinstance(v, (str, int, float, bool)) or v is None}
    text = json.dumps(clean, ensure_ascii=False)
    return text if len(text) <= CONTEXT_MAX else "{}"


def _text(text: str, limit: int, required: bool) -> str:
    text = str(text or "").strip()
    if required and not text:
        raise FeedbackError("请写一句建议")
    if len(text) > limit:
        raise FeedbackError(f"最多 {limit} 个字")
    return text


def suggest(user_id: int, text: str, view: str = "", contact_ok: bool = False, context: dict | None = None) -> int:
    text = _text(text, TEXT_MAX, required=True)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO feedback (kind, user_id, view, context, text, contact_ok, created_at) VALUES ('suggestion', ?, ?, ?, ?, ?, ?)",
            (user_id, _view(view), _context(context), text, 1 if contact_ok else 0, _now()))
        return int(cur.lastrowid)


def rate(user_id: int, feature: str, rating: int | None = None, text: str = "", context: dict | None = None) -> dict:
    """“有用吗”：第一次点有用或没用时记一条；之后补的“哪里可以更好”写进同一条。每人每个功能只有一条。"""

    if feature not in USEFUL_FEATURES:
        raise FeedbackError("这个功能不问“有用吗”")
    text = _text(text, TEXT_MAX, required=False)
    with get_conn() as conn:
        row = conn.execute("SELECT id, rating FROM feedback WHERE kind = 'useful' AND user_id = ? AND view = ?",
                           (user_id, feature)).fetchone()
        if row is None:
            if rating not in (1, -1):
                raise FeedbackError("请先选有用或没用")
            conn.execute(
                "INSERT INTO feedback (kind, user_id, view, context, rating, text, created_at) VALUES ('useful', ?, ?, ?, ?, ?, ?)",
                (user_id, feature, _context(context), rating, text, _now()))
            return {"feature": feature, "rating": rating}
        if text:   # 补一句：已经处理过的重新变成“新的”，免得管理员漏看
            conn.execute("UPDATE feedback SET text = ?, status = 'new' WHERE id = ?", (text, row["id"]))
        return {"feature": feature, "rating": row["rating"]}


def answered(user_id: int) -> list[str]:
    """这个用户已经回答过“有用吗”的功能，页面就不再问。"""

    with get_conn() as conn:
        rows = conn.execute("SELECT view FROM feedback WHERE kind = 'useful' AND user_id = ?", (user_id,)).fetchall()
    return sorted(row["view"] for row in rows)


def record_leave(reason: str, text: str = "") -> None:
    """注销账户时的离开原因：匿名保存（不记是谁），什么都没选就不记。"""

    reason = str(reason or "").strip()
    text = _text(text, LEAVE_TEXT_MAX, required=False)
    if not reason and not text:
        return
    if reason and reason not in LEAVE_REASONS:
        raise FeedbackError("离开原因不正确")
    with get_conn() as conn:
        conn.execute("INSERT INTO feedback (kind, user_id, context, text, created_at) VALUES ('leave', NULL, ?, ?, ?)",
                     (json.dumps({"reason": reason or "other"}), text, _now()))


def _row(row) -> dict[str, Any]:
    context = json.loads(row["context"] or "{}")
    item = {
        "id": row["id"], "kind": row["kind"], "view": row["view"], "context": context, "rating": row["rating"],
        "text": row["text"], "status": row["status"], "admin_note": row["admin_note"], "created_at": row["created_at"],
        "user": None,
    }
    if row["user_id"] is not None:
        # 邮箱只在用户同意被联系时给管理员看
        item["user"] = {"id": row["user_id"], "name": row["name"], "email": row["email"] if row["contact_ok"] else None}
    if row["kind"] == "leave":
        item["reason"] = LEAVE_REASONS.get(context.get("reason", ""), "其他")
    return item


def listing(kind: str = "", status: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
    where, args = [], []
    if kind:
        if kind not in KINDS:
            raise FeedbackError("没有这种反馈")
        where.append("f.kind = ?")
        args.append(kind)
    if status:
        if status not in STATUSES:
            raise FeedbackError("没有这个状态")
        where.append("f.status = ?")
        args.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with get_conn() as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM feedback f {clause}", args).fetchone()[0])
        rows = conn.execute(
            f"SELECT f.*, u.name, u.email FROM feedback f LEFT JOIN users u ON u.id = f.user_id {clause} "
            "ORDER BY f.created_at DESC, f.id DESC LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
    return {"total": total, "items": [_row(row) for row in rows]}


def update(feedback_id: int, status: str | None = None, note: str | None = None) -> dict[str, Any]:
    if status is not None and status not in STATUSES:
        raise FeedbackError("没有这个状态")
    if note is not None:
        note = _text(note, NOTE_MAX, required=False)
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM feedback WHERE id = ?", (feedback_id,)).fetchone() is None:
            raise LookupError("没有这条反馈")
        if status is not None:
            conn.execute("UPDATE feedback SET status = ? WHERE id = ?", (status, feedback_id))
        if note is not None:
            conn.execute("UPDATE feedback SET admin_note = ? WHERE id = ?", (note, feedback_id))
        row = conn.execute("SELECT f.*, u.name, u.email FROM feedback f LEFT JOIN users u ON u.id = f.user_id WHERE f.id = ?",
                           (feedback_id,)).fetchone()
    return _row(row)


def summary(now: datetime | None = None) -> dict[str, Any]:
    """后台顶部的三组数字：未读建议；最近 30 天各功能“有用”的比例；最近 30 天离开原因的分布。"""

    since = ((now or datetime.now(timezone.utc)) - timedelta(days=SUMMARY_DAYS)).isoformat()
    with get_conn() as conn:
        unread = int(conn.execute("SELECT COUNT(*) FROM feedback WHERE kind = 'suggestion' AND status = 'new'").fetchone()[0])
        rates = {row["view"]: (int(row["total"]), int(row["good"] or 0)) for row in conn.execute(
            "SELECT view, COUNT(*) AS total, SUM(rating > 0) AS good FROM feedback "
            "WHERE kind = 'useful' AND created_at >= ? GROUP BY view", (since,))}
        reasons: dict[str, int] = {}
        for row in conn.execute("SELECT context FROM feedback WHERE kind = 'leave' AND created_at >= ?", (since,)):
            key = json.loads(row["context"] or "{}").get("reason", "other")
            reasons[key] = reasons.get(key, 0) + 1
    useful = [{"feature": key, "label": label, "total": rates.get(key, (0, 0))[0], "useful": rates.get(key, (0, 0))[1]}
              for key, label in USEFUL_FEATURES.items()]
    leave = [{"reason": key, "label": label, "count": reasons.get(key, 0)} for key, label in LEAVE_REASONS.items()]
    return {"days": SUMMARY_DAYS, "unread": unread, "useful": useful, "leave": leave}
