"""配置项声明 —— 影响判定结果的东西一律放这里，不写死在代码里。

三层分法（沿用 Auto-rss2qb 的约定）：
    1. .env      只放改了必须重启的结构项（数据库连接、端口）
    2. 这张表    所有影响结果的配置，面板可改、改完即时生效
    3. 代码里    只留算法和兜底默认值

面板会按这里声明的 type / min / max 渲染控件，并把 note 原样显示出来。
"""

from __future__ import annotations

from typing import Any

SETTINGS_SPEC: dict[str, dict[str, Any]] = {
    "settle_due_day": {
        "type": "int_or_null",
        "default": None,
        "min": 1,
        "max": 31,
        "note_zh": "结算日：每月几号之前结清。**只用于账单上那句话**，不影响任何计算。"
                   "留空则账单只写「未结清」。",
        "note_ja": "精算日：毎月何日までに清算するか。**請求書の文言だけ**に使います。"
                   "空欄なら「未精算」とだけ表示します。",
    },
    "default_payer_id": {
        "type": "member_id_or_null",
        "default": None,
        "note_zh": "默认垫付人。记一笔时付款人预先填成他（我们家钱主要从一个人卡上出）。",
        "note_ja": "既定の立替者。記帳時の支払者に自動で入ります。",
    },
    "remainder_to": {
        "type": "enum",
        "default": "payer",
        "options": ["payer", "order", "rotate"],
        "note_zh": "分摊除不尽时，多出来的 1 円归谁。"
                   "payer＝给付款人（默认）／order＝按成员顺序／rotate＝逐笔轮转。",
        "note_ja": "割り切れないときの端数 1 円を誰が負担するか。"
                   "payer＝支払者（既定）／order＝メンバー順／rotate＝持ち回り。",
    },
    "default_rule": {
        "type": "json",
        "default": {"mode": "ratio", "equal_weight": 1},
        "note_zh": "全局默认分摊规则（第 1 层）。equal_weight 表示「所有在籍成员权重相同」，"
                   "这样加人减人都不用回来改。分类可以各自覆盖它。",
        "note_ja": "既定の分担ルール（第 1 層）。equal_weight は「在籍メンバー全員が同じ重み」の意味。"
                   "カテゴリごとに上書きできます。",
    },
    "simplify_debts": {
        "type": "bool",
        "default": True,
        "note_zh": "出账单时是否算「最少转账方案」（3 人最多 2 笔）。"
                   "副作用：可能出现原本没跟你有账的人要给你转钱。关掉则按原始债权逐笔结。",
        "note_ja": "精算時に「最小送金プラン」を計算するか（3 人なら最大 2 件）。"
                   "オフにすると元の債権どおりに清算します。",
    },
    "settlement_methods": {
        "type": "string_list",
        "default": ["現金"],
        "note_zh": "结算方式候选。现在只用现金；以后改用 PayPay 或银行振込，在这里加一行就行。",
        "note_ja": "精算方法の選択肢。追加・削除は自由です。",
    },
    "backup_path": {
        "type": "str",
        "default": "./backups",
        "note_zh": "每日自动备份的存放目录。",
        "note_ja": "毎日の自動バックアップの保存先。",
    },
}


def defaults() -> dict[str, Any]:
    return {k: v["default"] for k, v in SETTINGS_SPEC.items()}
