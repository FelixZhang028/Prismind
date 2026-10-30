"""用户反馈：建议、“有用吗”、注销时匿名的离开原因，以及管理员的列表和汇总。"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database
from app.quant import accounts as account_data
from app.quant import feedback, rate_limit
from app.routes import admin, agent_lab, auth
from app.routes import feedback as feedback_routes


@pytest.fixture
def site(tmp_path, monkeypatch):
    """用户和管理员都在的一个小网站：返回 (client, 普通用户的请求头, 管理员的请求头, 普通用户 id)。"""

    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "app.db"))
    database.init_db()
    for name in ("FELLOWQUANT_INVITE_CODES", "FELLOWQUANT_REGISTRATION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(agent_lab, "_AGENT_ROOT", tmp_path / "agent_lab")
    app = FastAPI()
    for router in (auth.router, admin.router, feedback_routes.router):
        app.include_router(router)
    client = TestClient(app)

    def join(email):
        client.post("/api/v1/auth/register", json={"name": "试用", "email": email, "password": "correct horse 1"})
        data = client.post("/api/v1/auth/login", json={"email": email, "password": "correct horse 1"}).json()
        return {"Authorization": f"Bearer {data['token']}"}, data["user"]["id"]

    boss, _ = join("boss@example.test")
    with database.get_conn() as conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE email = 'boss@example.test'")
    user, user_id = join("a@example.test")
    return client, user, boss, user_id


def test_a_suggestion_remembers_the_page_and_only_shows_the_email_when_allowed(site):
    client, user, boss, _ = site
    assert client.post("/api/v1/feedback/suggestions", json={"text": "  "}, headers=user).status_code == 400
    assert client.post("/api/v1/feedback/suggestions", json={"text": "长" * 501}, headers=user).status_code == 400
    assert client.post("/api/v1/feedback/suggestions", json={"text": "x", "view": "Bad View"}, headers=user).status_code == 400
    assert client.post("/api/v1/feedback/suggestions", json={"text": "能显示每只股票赚了多少吗", "view": "backtest-review",
                                                             "context": {"run": 8, "nested": {"x": 1}}}, headers=user).status_code == 201
    assert client.post("/api/v1/feedback/suggestions", json={"text": "可以联系我", "contact_ok": True}, headers=user).status_code == 201
    assert client.get("/api/v1/admin/feedback", headers=user).status_code == 403          # 只有管理员能看
    body = client.get("/api/v1/admin/feedback?kind=suggestion", headers=boss).json()
    newest, older = body["items"]
    assert body["total"] == 2 and body["summary"]["unread"] == 2
    assert older["view"] == "backtest-review" and older["context"] == {"run": 8}          # 复杂的值不收
    assert older["user"]["email"] is None and newest["user"]["email"] == "a@example.test"
    assert newest["user"]["name"] == "试用"


def test_useful_is_asked_once_per_feature_and_a_later_comment_joins_the_same_row(site):
    client, user, boss, _ = site
    assert client.get("/api/v1/feedback/useful", headers=user).json()["answered"] == []
    assert client.post("/api/v1/feedback/useful", json={"feature": "factor-lab", "rating": 1}, headers=user).status_code == 400
    assert client.post("/api/v1/feedback/useful", json={"feature": "event-study"}, headers=user).status_code == 400   # 先选有用或没用
    assert client.post("/api/v1/feedback/useful", json={"feature": "event-study", "rating": -1}, headers=user).json()["rating"] == -1
    assert client.post("/api/v1/feedback/useful", json={"feature": "event-study", "rating": 1}, headers=user).json()["rating"] == -1
    row = client.get("/api/v1/admin/feedback?kind=useful", headers=boss).json()["items"][0]
    client.post(f"/api/v1/admin/feedback/{row['id']}", json={"status": "done"}, headers=boss)
    client.post("/api/v1/feedback/useful", json={"feature": "event-study", "text": "想看分行业的结果"}, headers=user)
    body = client.get("/api/v1/admin/feedback?kind=useful", headers=boss).json()
    assert body["total"] == 1
    assert body["items"][0]["text"] == "想看分行业的结果" and body["items"][0]["status"] == "new"     # 补了一句，重新变成新的
    assert client.get("/api/v1/feedback/useful", headers=user).json()["answered"] == ["event-study"]
    useful = {item["feature"]: item for item in body["summary"]["useful"]}
    assert useful["event-study"]["total"] == 1 and useful["event-study"]["useful"] == 0
    assert useful["agent-lab"]["total"] == 0


def test_the_admin_marks_feedback_and_writes_a_note(site):
    client, user, boss, _ = site
    client.post("/api/v1/feedback/suggestions", json={"text": "加个导出"}, headers=user)
    item = client.get("/api/v1/admin/feedback", headers=boss).json()["items"][0]
    done = client.post(f"/api/v1/admin/feedback/{item['id']}", json={"status": "done", "note": "已在 #95 做了"}, headers=boss).json()
    assert done["status"] == "done" and done["admin_note"] == "已在 #95 做了"
    assert client.post(f"/api/v1/admin/feedback/{item['id']}", json={"status": "gone"}, headers=boss).status_code == 422
    assert client.post("/api/v1/admin/feedback/999", json={"status": "read"}, headers=boss).status_code == 404
    assert client.get("/api/v1/admin/feedback?status=new", headers=boss).json()["total"] == 0
    assert client.get("/api/v1/admin/feedback?kind=nope", headers=boss).status_code == 400
    assert client.get("/api/v1/admin/stats", headers=boss).json()["feedback"] == {"unread": 0}


def test_leaving_keeps_an_anonymous_reason_and_deletes_the_rest(site):
    client, user, boss, user_id = site
    client.post("/api/v1/feedback/suggestions", json={"text": "我的建议"}, headers=user)
    client.post("/api/v1/feedback/useful", json={"feature": "agent-lab", "rating": 1}, headers=user)
    exported = account_data.export_account(user_id)["tables"]["feedback"]          # 导出数据时一起导出
    assert sorted(row["kind"] for row in exported) == ["suggestion", "useful"]
    bad = client.post("/api/v1/auth/delete", json={"password": "correct horse 1", "reason": "nope"}, headers=user)
    assert bad.status_code == 400                                                   # 原因不对就不注销
    assert client.post("/api/v1/auth/delete", json={"password": "correct horse 1", "reason": "hard", "reason_text": "找不到入口"},
                       headers=user).status_code == 200
    body = client.get("/api/v1/admin/feedback", headers=boss).json()
    assert [(item["kind"], item["user"], item["reason"], item["text"]) for item in body["items"]] == [("leave", None, "太难用", "找不到入口")]
    leave = {item["reason"]: item["count"] for item in body["summary"]["leave"]}
    assert leave["hard"] == 1 and leave["unused"] == 0


def test_leaving_without_a_reason_records_nothing(site):
    client, user, boss, _ = site
    assert client.post("/api/v1/auth/delete", json={"password": "correct horse 1"}, headers=user).status_code == 200
    assert client.get("/api/v1/admin/feedback", headers=boss).json()["total"] == 0


def test_too_many_suggestions_wait_a_while(site, monkeypatch):
    client, user, _, _ = site
    monkeypatch.setenv("FELLOWQUANT_RATE_LIMITS", "on")
    rate_limit.reset()
    for _ in range(feedback_routes.SUGGESTIONS_PER_HOUR):
        assert client.post("/api/v1/feedback/suggestions", json={"text": "再来一条"}, headers=user).status_code == 201
    assert client.post("/api/v1/feedback/suggestions", json={"text": "又一条"}, headers=user).status_code == 429


def test_the_summary_only_counts_the_last_30_days(site):
    _, _, _, user_id = site
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    with database.get_conn() as conn:
        conn.execute("INSERT INTO feedback (kind, user_id, view, rating, created_at) VALUES ('useful', ?, 'backtest-review', 1, ?)", (user_id, old))
        conn.execute("INSERT INTO feedback (kind, context, created_at) VALUES ('leave', '{\"reason\": \"data\"}', ?)", (old,))
    summary = feedback.summary()
    assert {i["feature"]: i["total"] for i in summary["useful"]}["backtest-review"] == 0
    assert {i["reason"]: i["count"] for i in summary["leave"]}["data"] == 0
