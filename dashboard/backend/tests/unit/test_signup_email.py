"""注册要先验证邮箱；同一个邮箱（不同写法算同一个）只送一次注册积分，注销后再注册也不送；163 邮箱用 SSL 端口发信。"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database, security
from app.quant import mailer, points, rate_limit
from app.routes import admin, auth

PASSWORD = "correct horse 1"


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "app.db"))
    database.init_db()
    for name in ("FELLOWQUANT_INVITE_CODES", "FELLOWQUANT_REGISTRATION", "SMTP_HOST", "SMTP_FROM", "SMTP_PORT", "SMTP_USERNAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FELLOWQUANT_SIGNUP_EMAIL_CODE", "on")
    monkeypatch.setenv("FELLOWQUANT_POINTS_SIGNUP", "100")
    auth._SIGNUP_CODES.clear()
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(admin.router)
    yield TestClient(app)
    auth._SIGNUP_CODES.clear()


def mail_on(monkeypatch, port="465"):
    monkeypatch.setenv("SMTP_HOST", "smtp.163.com")
    monkeypatch.setenv("SMTP_PORT", port)
    monkeypatch.setenv("SMTP_FROM", "prismind@163.example.test")


def sign_up(client, email, code="", **extra):
    return client.post("/api/v1/auth/register", json={"name": "试用", "email": email, "password": PASSWORD, "email_code": code, **extra})


def code_for(client, email):
    with patch.object(mailer.smtplib, "SMTP_SSL") as smtp:
        sent = client.post("/api/v1/auth/register/code", json={"email": email})
    assert sent.status_code == 200, sent.text
    mail = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
    code = auth._SIGNUP_CODES[email.strip().lower()][0]
    assert mail["To"] == email.strip().lower() and code in mail.get_content() and code not in sent.text
    return code


def balance(email):
    with database.get_conn() as conn:
        uid = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]
        return points.balance(conn, uid), uid


def test_without_a_mail_service_open_sign_up_waits_but_invite_codes_still_work(site, monkeypatch):
    status = site.get("/api/v1/auth/registration").json()
    assert status["available"] is False and "邮件服务" in status["reason"] and status["email_code"] is False
    refused = sign_up(site, "a@example.test")
    assert refused.status_code == 503 and "邮件服务" in refused.json()["detail"]
    assert site.post("/api/v1/auth/register/code", json={"email": "a@example.test"}).status_code == 503
    monkeypatch.setenv("FELLOWQUANT_INVITE_CODES", "FRIENDS")
    assert site.get("/api/v1/auth/registration").json()["available"] is True
    assert sign_up(site, "a@example.test", invite_code="friends").status_code == 201      # 邀请码由管理员控制


def test_the_code_sent_to_the_mailbox_is_needed_to_sign_up(site, monkeypatch):
    mail_on(monkeypatch)
    status = site.get("/api/v1/auth/registration").json()
    assert status == {"mode": "open", "email_code": True, "available": True, "reason": ""}
    assert sign_up(site, "new@example.test").json()["detail"] == "请先获取邮箱验证码"
    code = code_for(site, " New@Example.test ")
    wrong = sign_up(site, "new@example.test", "000000" if code != "000000" else "111111")
    assert wrong.status_code == 400 and wrong.json()["detail"] == "验证码错误"
    made = sign_up(site, "NEW@example.test", code)
    assert made.status_code == 201 and made.json()["email"] == "new@example.test"
    assert sign_up(site, "other@example.test", code).status_code == 400                    # 验证码只对那个邮箱有效
    again = site.post("/api/v1/auth/register/code", json={"email": "new@example.test"})
    assert again.status_code == 409 and "已被注册" in again.json()["detail"]
    assert "new@example.test" not in auth._SIGNUP_CODES                                     # 用过就作废


def test_five_wrong_codes_and_the_code_is_gone(site, monkeypatch):
    mail_on(monkeypatch)
    code = code_for(site, "a@example.test")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert sign_up(site, "a@example.test", wrong).json()["detail"] == "验证码错误"
    assert "次数过多" in sign_up(site, "a@example.test", code).json()["detail"]


def test_sending_codes_is_limited_so_nobody_can_flood_a_mailbox(site, monkeypatch):
    mail_on(monkeypatch)
    monkeypatch.setenv("FELLOWQUANT_RATE_LIMITS", "on")
    rate_limit.reset()
    code_for(site, "a@example.test")
    with patch.object(mailer.smtplib, "SMTP_SSL"):
        assert site.post("/api/v1/auth/register/code", json={"email": "a@example.test"}).status_code == 429   # 一分钟内，不算次数
        auth._SIGNUP_CODES.clear()
        assert site.post("/api/v1/auth/register/code", json={"email": "a@example.test"}).status_code == 200
        auth._SIGNUP_CODES.clear()
        assert site.post("/api/v1/auth/register/code", json={"email": "a@example.test"}).status_code == 200
        auth._SIGNUP_CODES.clear()
        limited = site.post("/api/v1/auth/register/code", json={"email": "a@example.test"})
    assert limited.status_code == 429 and "太频繁" in limited.json()["detail"]
    rate_limit.reset()


def test_a_failed_mail_gives_no_code(site, monkeypatch):
    mail_on(monkeypatch)
    with patch.object(mailer.smtplib, "SMTP_SSL", side_effect=OSError("secret details")):
        failed = site.post("/api/v1/auth/register/code", json={"email": "a@example.test"})
    assert failed.status_code == 503 and "secret details" not in failed.text and not auth._SIGNUP_CODES


def test_ports_465_and_994_use_ssl_and_587_uses_starttls(monkeypatch):
    mail_on(monkeypatch, "994")
    with patch.object(mailer.smtplib, "SMTP_SSL") as ssl, patch.object(mailer.smtplib, "SMTP") as plain:
        mailer.send_mail("a@example.test", "s", "b")
    assert ssl.call_args.args[:2] == ("smtp.163.com", 994) and not plain.called
    assert not ssl.return_value.__enter__.return_value.starttls.called
    mail_on(monkeypatch, "587")
    with patch.object(mailer.smtplib, "SMTP_SSL") as ssl, patch.object(mailer.smtplib, "SMTP") as plain:
        mailer.send_mail("a@example.test", "s", "b")
    assert plain.return_value.__enter__.return_value.starttls.called and not ssl.called


def test_other_spellings_of_one_address_are_the_same_mailbox():
    same = ["Ab.C+promo@Gmail.com", "abc@googlemail.com", "a.b.c@gmail.com"]
    assert {security.canonical_email(e) for e in same} == {"abc@gmail.com"}
    assert security.canonical_email("Li.Lei+x@163.com") == "li.lei@163.com"                # 别的邮箱的点要保留
    assert security.email_key("A@163.com") == security.email_key("a+1@163.com") != security.email_key("b@163.com")
    assert "163" not in security.email_key("a@163.com")                                     # 看不出原来的邮箱


def test_the_sign_up_gift_is_given_once_per_mailbox_even_after_deleting_the_account(site, monkeypatch):
    assert sign_up(site, "a@example.test").status_code == 503                               # 还没配邮件服务
    monkeypatch.setenv("FELLOWQUANT_SIGNUP_EMAIL_CODE", "off")                              # 只看积分：不用验证码
    assert sign_up(site, "a@example.test").status_code == 201
    assert balance("a@example.test")[0] == 100
    token = site.post("/api/v1/auth/login", json={"email": "a@example.test", "password": PASSWORD}).json()["token"]
    assert site.post("/api/v1/auth/delete", json={"password": PASSWORD}, headers={"Authorization": f"Bearer {token}"}).status_code == 200
    with database.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM signup_emails").fetchone()[0] == 1       # 注销后指纹还在
    assert sign_up(site, "a@example.test").status_code == 201                              # 可以重新注册
    assert balance("a@example.test")[0] == 0                                               # 但不再送积分
    assert sign_up(site, "a+2@example.test").status_code == 201
    assert balance("a+2@example.test")[0] == 0                                             # 换个写法也一样
    assert sign_up(site, "b@example.test").status_code == 201
    assert balance("b@example.test")[0] == 100


def test_accounts_from_before_are_remembered_when_the_site_starts(site):
    with database.get_conn() as conn:
        conn.execute("INSERT INTO users (id, name, email, password_hash, salt, created_at) VALUES (5, 'u', 'old@example.test', 'h', 's', 'now')")
        points.ensure_signup(conn, 5)
        conn.execute("DELETE FROM signup_emails")                                           # 像是这张表出现以前领的
    database.init_db()
    with database.get_conn() as conn:
        keys = [row["email_key"] for row in conn.execute("SELECT email_key FROM signup_emails")]
    assert keys == [security.email_key("old@example.test")]
