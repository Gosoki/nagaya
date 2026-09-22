"""建一个成员 / 重置某人的密码。

    .venv/bin/python -m tools.add_member kan Kan          # 建人，密码交互输入
    .venv/bin/python -m tools.add_member --reset kan      # 只重置密码
    .venv/bin/python -m tools.add_member --list

**为什么非得有这个脚本**：全新部署原来进不去门 —— 库里一个成员都没有，
而 `POST /api/members` 要求先登录，登录又要求先有成员，是个闭环死结。
唯一走得通的路是 `tools.seed_dev`，而它建的是三个假室友、还顺手关掉了自动备份。

没做成「第一个人免鉴权」那种自助注册：那扇门要么一直开着（谁摸到地址谁就是房东），
要么得靠「库里有没有人」来开关，而这个判断在恢复备份、批量删人那几天都会出岔子。
房东在服务器上敲一行命令，比那两种都稳，也只需要敲这一次。
"""

from __future__ import annotations

import getpass
import sys

from sqlmodel import Session, select

from app.auth import hash_password
from app.db import engine
from app.init_db import init_db
from app.models import MEMBER_COLORS, Member

#: 和改密码那一屏（ProfileCard 的 `newPw.length < 6`）同一条线。
#: 后端本身不设下限 —— 这里只是别让人在服务器上给自己敲一个 1 位的密码
MIN_PASSWORD = 6


def _ask(prompt: str) -> str:
    """密码问两遍。敲错一个字就等于把自己锁在门外，而这扇门没有第二把钥匙。"""
    first = getpass.getpass(prompt)
    if len(first) < MIN_PASSWORD:
        sys.exit(f"密码至少 {MIN_PASSWORD} 位")
    if first != getpass.getpass("再输一遍："):
        sys.exit("两次不一样")
    return first


def main(argv: list[str]) -> None:
    init_db()                      # 全新库：顺手把表和默认分类建出来
    with Session(engine) as session:
        rows = list(session.exec(select(Member).order_by(Member.display_order, Member.id)))

        if "--list" in argv:
            if not rows:
                print("一个成员都还没有。建第一个：python -m tools.add_member <登录名> <显示名>")
            for m in rows:
                left = f"，{m.left_on} 起已退出" if m.left_on else ""
                print(f"  {m.id}  {m.name}  ({m.display_name}){left}")
            return

        if "--reset" in argv:
            name = next((a for a in argv[1:] if not a.startswith("-")), "")
            who = next((m for m in rows if m.name == name), None)
            if who is None:
                sys.exit(f"没有叫 {name!r} 的成员。--list 看看都有谁")
            who.password_hash = hash_password(_ask(f"{who.display_name} 的新密码："))
            session.add(who)
            session.commit()
            # 改密码会把这个人**所有设备**的登录都踢下去（auth.session_tag 认的是
            # 密码指纹）—— 说出来，免得对方以为是自己手机坏了
            print(f"{who.name} 的密码改好了。他那边所有设备都要重新登录一次。")
            return

        args = [a for a in argv if not a.startswith("-")]
        if len(args) < 2:
            sys.exit(__doc__)
        name, display = args[0], args[1]
        if any(m.name == name for m in rows):
            sys.exit(f"{name!r} 已经有了。要改密码：--reset {name}")
        member = Member(
            name=name,
            display_name=display,
            display_order=len(rows),
            color=MEMBER_COLORS[len(rows) % len(MEMBER_COLORS)],
            password_hash=hash_password(_ask(f"{display} 的密码：")),
        )
        session.add(member)
        session.commit()
        session.refresh(member)
        print(f"建好了：{member.name}（{member.display_name}），id={member.id}")
        if len(rows) == 0:
            print("这是第一个人 —— 现在可以打开网页登录了。")


if __name__ == "__main__":
    main(sys.argv[1:])
