"""生成随机分摊用例，落盘给前后端一起验 —— SPEC §7.3。

分工：
    split_cases.json         手写的 27 条，**保证 Python 实现本身是对的**
    split_cases_random.json  这里生成的 500 条，**保证 TS 不跟 Python 漂**

固定随机种子，所以重跑的结果一模一样；改了算法才会 diff，一眼能看出来。

    .venv/bin/python -m tools.gen_random_cases
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from app.core.split import split

OUT = Path(__file__).parents[2] / "tests" / "fixtures" / "split_cases_random.json"
SEED = 20260921
COUNT = 500


def generate() -> dict:
    rng = random.Random(SEED)
    cases = []
    while len(cases) < COUNT:
        n = rng.randint(1, 5)
        order = [str(i + 1) for i in range(n)]
        weights = {m: rng.randint(0, 5) for m in order}
        if sum(weights.values()) == 0:
            weights[rng.choice(order)] = rng.randint(1, 5)
        adjustments = {m: rng.randint(-10_000, 10_000) for m in order if rng.random() < 0.4}
        adjustments = {k: v for k, v in adjustments.items() if v}
        case = {
            "mode": "ratio",
            "amount": rng.randint(-1_000_000, 1_000_000),
            "order": order,
            "weights": weights,
            "remainder_to": rng.choice(["payer", "order", "rotate"]),
            "payer": rng.choice(order),
            "rotate_seed": rng.randint(0, 100),
        }
        if adjustments:
            case["adjustments"] = adjustments
        if case["amount"] == 0:
            continue
        rule = {"mode": "ratio", "weights": weights, "remainder_to": case["remainder_to"]}
        if adjustments:
            rule["adjustments"] = adjustments
        case["expected"] = split(
            rule, case["amount"], order=order, payer=case["payer"], rotate_seed=case["rotate_seed"]
        )
        cases.append(case)
    return {
        "_readme": [
            "自动生成，**不要手改**。由 backend/tools/gen_random_cases.py 产出。",
            f"随机种子 {SEED}，{COUNT} 条。期望值来自 Python 实现。",
            "作用：锁住前端 TS 实现不跟后端漂。Python 自身的正确性由手写的",
            "split_cases.json 保证。改了算法就重跑这个脚本，diff 一看便知。",
        ],
        "seed": SEED,
        "cases": cases,
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(generate(), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写入 {OUT}（{COUNT} 条）")
