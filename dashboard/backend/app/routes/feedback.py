"""
用户反馈接口，挂载在 /api/v1/feedback 下（登录后可用）。

- POST /suggestions   提一句建议（自动带上是在哪个页面提的；可以同意用注册邮箱联系）
- GET  /useful        已经回答过“有用吗”的功能（页面就不再问）
- POST /useful        第一次出结果后回答“有用吗”；之后可以补一句“哪里可以更好”

注销时的离开原因跟着注销请求一起发（见 auth.py 的 /delete），匿名保存。管理员在 /api/v1/admin/feedback 查看。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..quant import feedback, rate_limit
from ..routes.auth import get_current_user

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])

SUGGESTIONS_PER_HOUR = 10
RATINGS_PER_HOUR = 30


class SuggestionIn(BaseModel):
    text: str = Field(..., max_length=feedback.TEXT_MAX + 50)
    view: str = Field("", max_length=40)
    contact_ok: bool = False
    context: dict[str, Any] = Field(default_factory=dict)


class UsefulIn(BaseModel):
    feature: str = Field(..., max_length=40)
    rating: Literal[1, -1] | None = None
    text: str = Field("", max_length=feedback.TEXT_MAX + 50)
    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/suggestions", status_code=status.HTTP_201_CREATED, summary="提一句建议")
def suggest(body: SuggestionIn, user: dict = Depends(get_current_user)):
    rate_limit.check(f"feedback:{user['id']}", SUGGESTIONS_PER_HOUR, 60 * 60, "建议提得太频繁，请过一会儿再提")
    try:
        feedback_id = feedback.suggest(user["id"], body.text, body.view, body.contact_ok, body.context)
    except feedback.FeedbackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"id": feedback_id}


@router.get("/useful", summary="已经回答过“有用吗”的功能")
def useful_answered(user: dict = Depends(get_current_user)):
    return {"answered": feedback.answered(user["id"]), "features": feedback.USEFUL_FEATURES}


@router.post("/useful", summary="回答“这个结果对你有用吗”")
def useful(body: UsefulIn, user: dict = Depends(get_current_user)):
    rate_limit.check(f"useful:{user['id']}", RATINGS_PER_HOUR, 60 * 60, "操作太频繁")
    try:
        return feedback.rate(user["id"], body.feature, body.rating, body.text, body.context)
    except feedback.FeedbackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
