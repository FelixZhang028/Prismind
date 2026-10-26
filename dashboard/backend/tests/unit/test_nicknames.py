"""昵称：用户自己改、管理员改别人的、违禁词（内置的删不掉，统一写法后再比较）。找回密码只看邮箱。"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database
from app.quant import mailer, nicknames, rate_limit
from app.routes import admin, auth


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "app.db"))
    database.init_db()
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(admin.router)
    with database.get_conn() as conn:
        for uid, name, admin_flag in ((1, "小明", 0), (2, "小红", 0), (9, "管理员", 1)):
            conn.execute("INSERT INTO users (id, name, email, password_hash, salt, created_at, is_admin) VALUES (?, ?, ?, 'h', 's', 'now', ?)",
                         (uid, name, f"u{uid}@example.test", admin_flag))
    current = {"user": None}

    def as_user(uid):
        with database.get_conn() as conn:
            row = conn.execute("SELECT id, name, email, created_at, is_admin FROM users WHERE id = ?", (uid,)).fetchone()
        current["user"] = auth._user_to_out(row)

    app.dependency_overrides[auth.get_current_user] = lambda: current["user"]
    return TestClient(app), as_user


def name_of(uid):
    with database.get_conn() as conn:
        return conn.execute("SELECT name FROM users WHERE id = ?", (uid,)).fetchone()["name"]


def test_the_same_word_written_differently_still_counts():
    assert nicknames.normalize("Ｐｒｉｓ ｍｉｎｄ") == nicknames.normalize("prism-ind!") == "prismind"
    find = nicknames.matcher()
    assert find("我是 管 理 员") == "管理员" and find("官-方小助手") == "官方" and find("PRISMIND粉丝") == "Prismind"
    assert find("小明") is None
    assert nicknames.clean_name("  小   明 ") == "小 明"
    for bad, reason in (("   ", "不能为空"), ("字" * 41, "最多 40"), ("小​明", "不能显示")):
        with pytest.raises(nicknames.NicknameError, match=reason):
            nicknames.clean_name(bad)


def test_people_change_their_own_name_but_not_to_a_banned_word(site, monkeypatch):
    client, as_user = site
    as_user(1)
    changed = client.post("/api/v1/auth/name", json={"name": "  小明  同学 "})
    assert changed.status_code == 200 and changed.json()["name"] == "小明 同学" and name_of(1) == "小明 同学"
    assert client.post("/api/v1/auth/name", json={"name": "小红"}).status_code == 200          # 可以重名
    refused = client.post("/api/v1/auth/name", json={"name": "镜思 官方"})
    assert refused.status_code == 400 and "官方" in refused.json()["detail"] and name_of(1) == "小红"
    assert client.post("/api/v1/auth/name", json={"name": ""}).status_code == 400
    as_user(9)
    assert client.post("/api/v1/auth/name", json={"name": "镜思官方"}).json()["name"] == "镜思官方"   # 管理员可以用


def test_five_changes_a_day(site, monkeypatch):
    client, as_user = site
    monkeypatch.setenv("FELLOWQUANT_RATE_LIMITS", "on")
    rate_limit.reset()
    as_user(1)
    for i in range(5):
        assert client.post("/api/v1/auth/name", json={"name": f"名字{i}"}).status_code == 200
        as_user(1)
    assert client.post("/api/v1/auth/name", json={"name": f"名字4"}).status_code == 200      # 没改：不算一次
    refused = client.post("/api/v1/auth/name", json={"name": "名字5"})
    assert refused.status_code == 429 and "用完" in refused.json()["detail"]
    rate_limit.reset()


def test_registration_checks_the_name_too(site):
    client, _ = site
    data = {"email": "new@example.test", "password": "initial-password"}
    refused = client.post("/api/v1/auth/register", json={**data, "name": "客服小李"})
    assert refused.status_code == 400 and "客服" in refused.json()["detail"]
    made = client.post("/api/v1/auth/register", json={**data, "name": " 新 用户 "})
    assert made.status_code == 201 and made.json()["name"] == "新 用户"


def test_the_administrator_renames_people_and_it_is_recorded(site):
    client, as_user = site
    as_user(1)
    assert client.post("/api/v1/admin/users/2/name", json={"name": "x"}).status_code == 403
    as_user(9)
    renamed = client.post("/api/v1/admin/users/2/name", json={"name": "官方 测试号", "reason": "内部账号"})
    assert renamed.status_code == 200 and name_of(2) == "官方 测试号"                    # 管理员不受违禁词限制
    assert client.post("/api/v1/admin/users/404/name", json={"name": "x"}).status_code == 404
    assert client.post("/api/v1/admin/users/2/name", json={"name": "  "}).status_code == 400
    record = client.get("/api/v1/admin/audit?kind=user").json()["items"][0]
    assert record["action"] == "user.rename" and record["summary"] == "把 u2@example.test 的昵称从“小红”改成“官方 测试号”：内部账号"
    users = {u["id"]: u for u in client.get("/api/v1/admin/users").json()}
    assert users[2]["banned_word"] == "官方" and users[1]["banned_word"] is None
    assert users[9]["banned_word"] is None                                                      # 管理员叫“管理员”不用标


def test_the_administrator_keeps_the_banned_word_list(site):
    client, as_user = site
    as_user(9)
    listed = client.get("/api/v1/admin/banned-words").json()["items"]
    assert [item["word"] for item in listed if item["builtin"]] == list(nicknames.BUILTIN)
    added = client.post("/api/v1/admin/banned-words", json={"words": "傻瓜，骗子、 傻瓜\n官方 ＰＲＩＳＭＩＮＤ 小明"}).json()
    assert added == {"added": ["傻瓜", "骗子", "小明"], "skipped": ["官方", "ＰＲＩＳＭＩＮＤ"]}
    users = {u["id"]: u for u in client.get("/api/v1/admin/users").json()}
    assert users[1]["banned_word"] == "小明"                                                    # 以前的名字只标出来，不自动改
    as_user(2)
    assert client.post("/api/v1/auth/name", json={"name": "大骗 子"}).status_code == 400        # 加了马上生效
    as_user(9)
    assert client.post("/api/v1/admin/banned-words/delete", json={"word": "骗子"}).status_code == 200
    as_user(2)
    assert client.post("/api/v1/auth/name", json={"name": "大骗 子"}).status_code == 200
    as_user(9)
    builtin = client.post("/api/v1/admin/banned-words/delete", json={"word": "镜思"})
    assert builtin.status_code == 400 and "内置" in builtin.json()["detail"]
    assert client.post("/api/v1/admin/banned-words/delete", json={"word": "没有"}).status_code == 404
    for bad in ("", "  ，、", "字" * 21, "!!!"):
        assert client.post("/api/v1/admin/banned-words", json={"words": bad}).status_code == 400
    kinds = [item["action"] for item in client.get("/api/v1/admin/audit?kind=nickname").json()["items"]]
    assert kinds == ["nickname.remove", "nickname.add"]


def test_password_reset_only_needs_the_email_so_a_renamed_person_can_still_reset(site, monkeypatch):
    client, as_user = site
    as_user(9)
    client.post("/api/v1/admin/users/1/name", json={"name": "改过的名字"})
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.test")
    auth._RESET_CODES.clear()
    with patch.object(mailer.smtplib, "SMTP"):
        sent = client.post("/api/v1/auth/forgot/request", json={"email": "U1@example.test"})
    assert sent.status_code == 200 and 1 in auth._RESET_CODES
    code = auth._RESET_CODES[1][0]
    reset = client.post("/api/v1/auth/forgot/reset", json={"email": "u1@example.test", "code": code, "new_password": "changed-password"})
    assert reset.status_code == 200
    with patch.object(mailer.smtplib, "SMTP"):
        unknown = client.post("/api/v1/auth/forgot/request", json={"email": "nobody@example.test"})
    assert unknown.status_code == 200 and unknown.json()["message"] == sent.json()["message"]   # 看不出邮箱有没有注册
    auth._RESET_CODES.clear()
