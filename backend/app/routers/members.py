from __future__ import annotations

import asyncio
import io

from fastapi import APIRouter, Depends, File, UploadFile, status
from PIL import Image, ImageOps
from sqlmodel import Session, select

from app.auth import MIN_PASSWORD_LEN, current_member, hash_password, verify_password
from app.db import get_session
from app.errors import AppError, not_found, reject_nulls
from app.models import Member, free_color
from app.routers.auth import to_member_out
from app.routers.appearance import IMAGE_FORMATS, MAX_PIXELS
from app.schemas import MemberIn, MemberOut
from app.services import ledger

#: 成员这张表进审计时不带的字段：密码哈希不该躺在日志里，头像是一坨二进制
_NOT_AUDITED = ("password_hash", "avatar")

router = APIRouter(prefix="/api/members", tags=["members"])


@router.get("", response_model=list[MemberOut])
def list_members(session: Session = Depends(get_session), _: Member = Depends(current_member)):
    rows = session.exec(select(Member).order_by(Member.display_order, Member.id)).all()
    return [to_member_out(m) for m in rows]


@router.post("", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def create_member(
    body: MemberIn,
    session: Session = Depends(get_session),
    actor: Member = Depends(current_member),
):
    if not body.name:
        raise AppError("name_required", "login name required")
    if session.exec(select(Member).where(Member.name == body.name)).first():
        raise AppError("name_taken", f"login name {body.name} taken", status=409, name=body.name)

    # 不给密码建出来的账号**永远登不进来**：密码只能自己改，而他登不进来就改不了，
    # 别人替他改会被上面那条挡下 —— 谁也解不开。建的时候就要有
    if not body.password:
        raise AppError("member_needs_password", "a new member needs an initial password")
    if len(body.password) < MIN_PASSWORD_LEN:
        raise AppError("password_too_short", "password too short", min=MIN_PASSWORD_LEN)
    data = body.model_dump(exclude_none=True, exclude={"password"})
    data.setdefault("display_name", body.name)
    # 没挑颜色就发一个**还没人用的**。按人数取模的老做法会撞：
    # 删过人、或者有人自己挑过色之后，新来的很可能拿到一个已经在用的颜色 ——
    # 而头像圆点、账单每人行全靠颜色分辨谁是谁
    data.setdefault("color", free_color(m.color for m in session.exec(select(Member))))
    member = Member(**data)
    if body.password:
        member.password_hash = hash_password(body.password)
    session.add(member)
    session.flush()
    ledger.audit_config(session, actor.id, "create", "member", member.id, None, member, drop=_NOT_AUDITED)
    session.commit()
    session.refresh(member)
    return to_member_out(member)


@router.patch("/{member_id}", response_model=MemberOut)
def update_member(
    member_id: int,
    body: MemberIn,
    session: Session = Depends(get_session),
    me: Member = Depends(current_member),
):
    member = session.get(Member, member_id)
    if member is None:
        raise not_found("member")

    # **登录名和密码只能改自己的。** 这屋里三个人是互相信任的，但「信任」不该等于
    # 「谁都能把别人锁在门外」—— 这两样都是**没法自己恢复**的动作：
    # 实测把别人的 name 改掉，他用自己的用户名登录直接 401，而且毫无自救手段。
    #
    # **joined_on / left_on 故意不在此列。** 它们看着也危险（一改那个人就进出
    # 分摊名单），但那是**家务动作不是自助动作**：人搬走之后多半不会再打开这个 app，
    # 只许本人改的话谁也标不掉他，从此每笔账都照样算他一份 —— 比要防的问题更糟。
    # 昵称、颜色、语言、排序同理：改错了当事人自己看得见、也改得回来。
    private = ["name"] if "name" in body.model_fields_set and body.name is not None else []
    if body.password is not None:
        private.append("password")
    if private and member.id != me.id:
        raise AppError(
            "forbidden_self_only", f"self only: {private}", status=403, fields=", ".join(private)
        )
    if body.password is not None and len(body.password) < MIN_PASSWORD_LEN:
        raise AppError("password_too_short", "password too short", min=MIN_PASSWORD_LEN)
    if body.password is not None:
        # 已经设过密码的，得先报出旧的。手机搁桌上没锁屏，别人顺手就能改掉
        if member.password_hash and not verify_password(body.old_password or "", member.password_hash):
            raise AppError("wrong_password", "current password does not match", status=403)

    # exclude_unset 而不是 exclude_none：PATCH 的语义是「我发了什么就改什么」。
    # 用 exclude_none 的话 left_on 一旦填错就再也清不掉 —— null 会被当成「没发」，
    # 于是那个人永远是「已退出」，回不来
    fields = body.model_dump(exclude_unset=True, exclude={"password", "old_password"})
    # 显式传 null 的那几个：数据库上是 NOT NULL，直接 setattr 下去就是 500。
    # left_on 不在里面 —— 它**必须**清得掉，否则填错一次那个人就永远是「已退出」
    reject_nulls(fields, ("name", "display_name", "color", "display_order", "joined_on", "lang"))
    if "name" in fields:
        if not fields["name"]:
            raise AppError("name_required", "login name required")
        clash = session.exec(select(Member).where(Member.name == fields["name"])).first()
        if clash is not None and clash.id != member_id:
            # 这一条原来会撞穿到数据库的唯一约束，返回 500；POST 那边早就是 409 了
            raise AppError("name_taken", "login name taken", status=409, name=fields["name"])
    before = member.model_copy()
    for key, value in fields.items():
        setattr(member, key, value)
    if body.password:
        member.password_hash = hash_password(body.password)
    session.add(member)
    after = member.model_copy()
    ledger.audit_config(session, me.id, "update", "member", member.id, before, after, drop=_NOT_AUDITED)
    if body.password:
        # 改密码只记「改了」，不记任何和密码有关的值
        ledger.audit_config(session, me.id, "password", "member", member.id, None, {"password_changed": True})
    session.commit()
    session.refresh(member)
    return to_member_out(member)


#: 头像上传上限。手机随手拍就是四五 MB，挡在读之前 —— 不能先读进内存再判断
MAX_AVATAR_BYTES = 5 * 1024 * 1024
#: 存下来的边长。界面上最大只用到 40px，三倍屏也就 120px，192 足够清楚了
AVATAR_SIZE = 192


def _compress_avatar(raw: bytes) -> bytes:
    """把上传的图片压成一张小方图。

    做四件事，缺一不可：
      * **按 EXIF 摆正** —— 手机横过来拍的照片，不转的话头像是躺着的
      * **居中裁成正方形** —— 头像是个圆，直接缩放会把人脸压扁
      * 转成 WebP —— 同画质下比 JPEG 小三成左右
      * 丢掉所有元数据 —— EXIF 里有拍摄地点的 GPS
    """
    try:
        img = Image.open(io.BytesIO(raw), formats=IMAGE_FORMATS)
        if img.width * img.height > MAX_PIXELS:
            raise ValueError("too many pixels")
        img = ImageOps.exif_transpose(img) or img
        img = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), method=Image.Resampling.LANCZOS)
        img = img.convert("RGB")
    except Exception as e:  # Pillow 认不出的、或者解压炸弹
        raise AppError("avatar_not_image", "not an image") from e
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=80, method=6)
    return buf.getvalue()


@router.post("/{member_id}/avatar", response_model=MemberOut)
async def upload_avatar(
    member_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    me: Member = Depends(current_member),
):
    """换头像。只能换自己的。"""
    member = session.get(Member, member_id)
    if member is None:
        raise not_found("member")
    if member.id != me.id:
        raise AppError("forbidden_self_only", "avatar is self only", status=403, fields="avatar")

    # 多读一个字节：正好等于上限的放过，超一点就拒 —— 不先整个读进内存
    raw = await file.read(MAX_AVATAR_BYTES + 1)
    if len(raw) > MAX_AVATAR_BYTES:
        raise AppError(
            "avatar_too_big", "avatar over the size limit", status=413,
            limit_mb=MAX_AVATAR_BYTES // 1024 // 1024,
        )
    if not raw:
        raise AppError("avatar_empty", "no file received")

    member.avatar = await asyncio.to_thread(_compress_avatar, raw)
    member.avatar_version += 1
    session.add(member)
    session.commit()
    session.refresh(member)
    return to_member_out(member)


@router.delete("/{member_id}/avatar", response_model=MemberOut)
def delete_avatar(
    member_id: int,
    session: Session = Depends(get_session),
    me: Member = Depends(current_member),
):
    """撤掉头像，回到那个带首字的色圆。"""
    member = session.get(Member, member_id)
    if member is None:
        raise not_found("member")
    if member.id != me.id:
        raise AppError("forbidden_self_only", "avatar is self only", status=403, fields="avatar")
    member.avatar = None
    member.avatar_version += 1
    session.add(member)
    session.commit()
    session.refresh(member)
    return to_member_out(member)
