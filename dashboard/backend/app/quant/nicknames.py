"""昵称：整理格式，检查违禁词；违禁词表由管理员在后台维护。

登录用邮箱，昵称只是显示的名字，可以重名。违禁词分两部分：:data:`BUILTIN` 写在代码里、删不掉，
防止冒充平台；管理员加的存在 ``nickname_banned_words`` 表里，加了马上生效。

比较之前先把写法统一（:func:`normalize`）：不分大小写、全角半角当成一样、去掉空格和符号，
所以“管 理 员”“Ｐｒｉｓｍｉｎｄ”“官-方”都算。昵称里只要包含某个词就不能用。
以后社区的帖子存到后端时，也可以用 :func:`banned_word` 检查。
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from ..database import get_conn

NAME_MAX = 40
WORD_MAX = 20
WORDS_PER_ADD = 200
BUILTIN = ("管理员", "官方", "客服", "镜思", "Prismind")


class NicknameError(ValueError):
    """昵称或违禁词不能用；内容是给用户看的原因。"""


def normalize(text: str) -> str:
    """比较用的写法：全角转半角、小写，去掉空格、标点、符号和控制字符。"""

    text = unicodedata.normalize("NFKC", str(text)).casefold()
    return "".join(ch for ch in text if unicodedata.category(ch)[0] not in "PSZC")


def clean_name(raw: Any) -> str:
    """去掉前后空格、中间连续的空格合并成一个；不能为空、不能超过 40 个字、不能有控制字符。"""

    name = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not name:
        raise NicknameError("昵称不能为空")
    if len(name) > NAME_MAX:
        raise NicknameError(f"昵称最多 {NAME_MAX} 个字")
    if any(unicodedata.category(ch) in ("Cc", "Cf") for ch in name):
        raise NicknameError("昵称里有不能显示的字符")
    return name


def _custom(conn) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT word, created_by, created_at FROM nickname_banned_words ORDER BY created_at DESC, word").fetchall()
    return [{"word": row["word"], "builtin": False, "created_by": row["created_by"], "created_at": row["created_at"]} for row in rows]


def words() -> list[dict[str, Any]]:
    """全部违禁词：内置的在前，管理员加的按添加时间从新到旧。"""

    with get_conn() as conn:
        custom = _custom(conn)
    return [{"word": word, "builtin": True, "created_by": "", "created_at": ""} for word in BUILTIN] + custom


def matcher():
    """返回一个函数：给昵称，返回它包含的第一个违禁词（没有就是 None）。查一次表，检查很多昵称时用。"""

    keys = [(normalize(item["word"]), item["word"]) for item in words()]
    keys = [(key, word) for key, word in keys if key]

    def find(name: str) -> str | None:
        text = normalize(name)
        return next((word for key, word in keys if key in text), None)

    return find


def banned_word(name: str) -> str | None:
    return matcher()(name)


def check(raw: Any, *, allow_banned: bool = False) -> str:
    """整理好的昵称；有违禁词时 :class:`NicknameError`（``allow_banned`` 给管理员改昵称用）。"""

    name = clean_name(raw)
    if not allow_banned:
        word = banned_word(name)
        if word:
            raise NicknameError(f"昵称里有不能使用的词“{word}”，请换一个")
    return name


def parse_words(text: str) -> list[str]:
    """管理员一次粘贴的很多词：用空格、逗号、顿号、分号或换行分开，去掉重复的（按统一后的写法）。"""

    seen, out = set(), []
    for word in re.split(r"[\s,，、;；]+", str(text or "")):
        word = word.strip()
        if not word:
            continue
        if len(word) > WORD_MAX:
            raise NicknameError(f"“{word[:WORD_MAX]}…”太长了，每个词最多 {WORD_MAX} 个字")
        key = normalize(word)
        if not key:
            raise NicknameError(f"“{word}”只有空格或符号，比较时会被去掉，不能当违禁词")
        if key not in seen:
            seen.add(key)
            out.append(word)
    if not out:
        raise NicknameError("没有要加的词")
    if len(out) > WORDS_PER_ADD:
        raise NicknameError(f"一次最多加 {WORDS_PER_ADD} 个词")
    return out


def add(text: str, admin_email: str) -> dict[str, list[str]]:
    """加词；已经有的（包括内置的，按统一后的写法比较）跳过。返回加上的和跳过的。"""

    wanted = parse_words(text)
    now = datetime.now(timezone.utc).isoformat()
    added, skipped = [], []
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        have = {normalize(word) for word in BUILTIN} | {normalize(item["word"]) for item in _custom(conn)}
        for word in wanted:
            key = normalize(word)
            if key in have:
                skipped.append(word)
                continue
            conn.execute("INSERT INTO nickname_banned_words (word, word_key, created_by, created_at) VALUES (?,?,?,?)",
                         (word, key, admin_email, now))
            have.add(key)
            added.append(word)
    return {"added": added, "skipped": skipped}


def remove(word: str) -> bool:
    """删掉管理员加的词；内置的删不掉（:class:`NicknameError`）。返回有没有删到。"""

    if normalize(word) in {normalize(item) for item in BUILTIN}:
        raise NicknameError(f"“{word}”是内置的词，不能删除")
    with get_conn() as conn:
        return conn.execute("DELETE FROM nickname_banned_words WHERE word = ?", (word,)).rowcount > 0
