"""子管理员：管理员可以设为或取消；子管理员能进管理后台管普通用户，但没有积分、注册方式、数据和系统设置的权限，
也不能动管理员和其他子管理员；在功能台里还是普通用户。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database
from app.quant import audit, rate_limit
from app.routes import admin, auth
from app.routes.auth import get_current_user
from app.security import gen_salt, hash_password

ADMIN = {"id": 1, "name": "管理员", "email": "admin@example.test", "is_admin": True, "is_sub_admin": False}
SUB = {"id": 2, "name": "小助手", "email": "sub@example.test", "is_admin": False, "is_sub_admin": True}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "app.db"))
    database.init_db()
    with database.get_conn() as conn:
        conn.execute("INSERT INTO users (id, name, email, password_hash, salt, created_at, is_admin) VALUES (1, '管理员', 'admin@example.test', 'x', 'y', 'now', 1)")
        conn.execute("INSERT INTO users (id, name, email, password_hash, salt, created_at, is_sub_admin) VALUES (2, '小助手', 'sub@example.test', 'x', 'y', 'now', 1)")
        conn.execute("INSERT INTO users (id, name, email, password_hash, salt, created_at) VALUES (3, '用户', 'u@example.test', 'x', 'y', 'now')")
        conn.execute("INSERT INTO users (id, name, email, password_hash, salt, created_at, is_sub_admin) VALUES (4, '另一个', 'sub2@example.test', 'x', 'y', 'now', 1)")
    rate_limit.reset()
    app = FastAPI()
    app.include_router(admin.router)
    current = {"user": ADMIN}
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    yield TestClient(app), current
    rate_limit.reset()


def flags(uid):
    with database.get_conn() as conn:
        row = conn.execute("SELECT is_sub_admin, is_active, name FROM users WHERE id = ?", (uid,)).fetchone()
    return dict(row)


def test_the_admin_sets_and_removes_a_sub_admin(api):
    client, _ = api
    assert client.post("/api/v1/admin/users/3/sub-admin", json={"sub_admin": True}).json() == {"id": 3, "is_sub_admin": True}
    assert flags(3)["is_sub_admin"] == 1
    users = {u["id"]: u for u in client.get("/api/v1/admin/users").json()}
    assert users[3]["is_sub_admin"] is True and users[1]["is_sub_admin"] is False
    assert client.post("/api/v1/admin/users/3/sub-admin", json={"sub_admin": False}).status_code == 200
    assert flags(3)["is_sub_admin"] == 0
    actions = [row["action"] for row in audit.listing("user")]
    assert actions[:2] == ["user.sub_admin_off", "user.sub_admin_on"]
    # 管理员本身不用设；停用的账户要先恢复。
    assert client.post("/api/v1/admin/users/1/sub-admin", json={"sub_admin": True}).status_code == 400
    with database.get_conn() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = 3")
    assert client.post("/api/v1/admin/users/3/sub-admin", json={"sub_admin": True}).status_code == 400
    assert client.post("/api/v1/admin/users/99/sub-admin", json={"sub_admin": True}).status_code == 404


def test_a_sub_admin_manages_plain_users_only(api):
    client, current = api
    current["user"] = SUB
    assert client.get("/api/v1/admin/users").status_code == 200
    assert client.post("/api/v1/admin/users/3/active", json={"active": False}).status_code == 200
    assert flags(3)["is_active"] == 0
    assert client.post("/api/v1/admin/users/3/active", json={"active": True}).status_code == 200
    assert client.post("/api/v1/admin/users/3/name", json={"name": "新名字"}).status_code == 200
    assert flags(3)["name"] == "新名字"
    # 管理员、其他子管理员和自己都不行
    for uid in (1, 2, 4):
        assert client.post(f"/api/v1/admin/users/{uid}/active", json={"active": False}).status_code == 403
        assert client.post(f"/api/v1/admin/users/{uid}/name", json={"name": "改掉"}).status_code == 403
    assert flags(4) == {"is_sub_admin": 1, "is_active": 1, "name": "另一个"}
    # 操作记录里写的是子管理员的邮箱
    assert audit.listing("user")[0]["admin_email"] == "sub@example.test"


def test_a_sub_admin_cannot_use_admin_only_pages(api):
    client, current = api
    current["user"] = SUB
    for method, path, body in [
        ("post", "/api/v1/admin/users/3/sub-admin", {"sub_admin": True}),
        ("post", "/api/v1/admin/users/3/points", {"amount": 10, "note": "x"}),
        ("get", "/api/v1/admin/points", None),
        ("post", "/api/v1/admin/redeem-codes", {"points": 10}),
        ("put", "/api/v1/admin/registration", {"mode": "open"}),
        ("get", "/api/v1/admin/system", None),
        ("post", "/api/v1/admin/backup", None),
        ("get", "/api/v1/admin/settings", None),
        ("put", "/api/v1/admin/settings", {"password": "x"}),
        ("post", "/api/v1/admin/settings/test", {"target": "email"}),
        ("post", "/api/v1/admin/feedback/1", {"status": "read"}),
    ]:
        response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert response.status_code == 403, path
    assert flags(3)["is_sub_admin"] == 0
    # 能看的页面
    for path in ["/api/v1/admin/stats", "/api/v1/admin/registration", "/api/v1/admin/banned-words",
                 "/api/v1/admin/feedback", "/api/v1/admin/audit", "/api/v1/admin/ai-usage"]:
        assert client.get(path).status_code == 200, path
    assert client.post("/api/v1/admin/invites", json={"note": "给朋友"}).status_code == 201


def test_a_sub_admin_rename_still_checks_banned_words(api):
    client, current = api
    current["user"] = SUB
    assert client.post("/api/v1/admin/banned-words", json={"words": "坏词"}).status_code == 201
    assert client.post("/api/v1/admin/users/3/name", json={"name": "坏词用户"}).status_code == 400
    current["user"] = ADMIN
    assert client.post("/api/v1/admin/users/3/name", json={"name": "坏词用户"}).status_code == 200


def test_plain_users_and_removed_sub_admins_are_turned_away(api):
    client, current = api
    current["user"] = {"id": 3, "name": "用户", "email": "u@example.test", "is_admin": False, "is_sub_admin": False}
    assert client.get("/api/v1/admin/users").status_code == 403
    assert client.get("/api/v1/admin/stats").status_code == 403


def test_the_logged_in_user_says_whether_they_are_a_sub_admin(tmp_path, monkeypatch):
    """功能台和管理后台靠 /auth/me 和登录返回的 is_sub_admin 判断；每次请求都从数据库读，取消后立刻生效。"""

    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "app.db"))
    database.init_db()
    salt = gen_salt()
    with database.get_conn() as conn:
        conn.execute("INSERT INTO users (id, name, email, password_hash, salt, created_at, is_sub_admin) VALUES (5, '助手', 'helper@example.test', ?, ?, 'now', 1)",
                     (hash_password("helper-password-123", salt), salt))
    rate_limit.reset()
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(admin.router)
    client = TestClient(app)
    login = client.post("/api/v1/auth/login", json={"email": "helper@example.test", "password": "helper-password-123"}).json()
    assert login["user"]["is_sub_admin"] is True and login["user"]["is_admin"] is False
    headers = {"Authorization": f"Bearer {login['token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).json()["is_sub_admin"] is True
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 200
    with database.get_conn() as conn:
        conn.execute("UPDATE users SET is_sub_admin = 0 WHERE id = 5")
    assert client.get("/api/v1/auth/me", headers=headers).json()["is_sub_admin"] is False
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 403
    rate_limit.reset()
