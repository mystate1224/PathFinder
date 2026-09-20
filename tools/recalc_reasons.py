# -*- coding: utf-8 -*-
"""recalc_reasons.py —— 把库里已落地的画像「判定理由」按当前规则重写一遍。

用途：分层理由的**文案**改了以后，已经存在的画像不会自己更新（只有上传材料或改自评时才重算），
于是页面上会同时出现新旧两种说法。这个脚本用同一套规则把理由刷新 —— 判定结果本身不变。

安全边界：
* 只改 ``student_profiles.reason`` 一个字段，**不动**主标签 / 层次 / 能力 / 倾向值；
* 重算出的主标签若与库里不一致，会明确报出来并跳过该行（说明历史数据不是规则口径，人工确认）。

用法：
    python tools/recalc_reasons.py            # 预演：只打印会改哪些
    python tools/recalc_reasons.py --apply    # 真正写入
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
from services import stratify  # noqa: E402


def main(apply: bool) -> int:
    rows = db.query(
        "SELECT user_id, track, gpa, research_intent, job_intent, interests, reason "
        "FROM student_profiles ORDER BY user_id"
    )
    if not rows:
        print("student_profiles 为空，无需处理")
        return 0

    changed = 0
    skipped = 0
    for r in rows:
        interests = db.jload(r.get("interests"), []) or []
        fresh = stratify.rule_stratify(
            r.get("gpa") or 0,
            r.get("research_intent") or 3.0,
            r.get("job_intent") or 3.0,
            interests,
        )
        if fresh.get("track") != r.get("track"):
            skipped += 1
            print(f"  [跳过] user_id={r['user_id']} 库里是{r.get('track')}，规则重算为{fresh.get('track')}")
            continue
        reason = str(fresh.get("reason") or "")
        # 资源申请行为会在理由尾部追加一句提示（resources._nudge_intent），
        # 那是**行为事实**不是规则产物，重写理由时必须原样接回去，不能吞掉。
        tail = "（近期有资源申请行为，倾向信号已微调。）"
        if tail in str(r.get("reason") or "") and tail not in reason:
            reason += tail
        if reason == r.get("reason"):
            continue
        changed += 1
        print(f"  [改写] user_id={r['user_id']} {r.get('track')}")
        print(f"         旧：{r.get('reason')}")
        print(f"         新：{reason}")
        if apply:
            db.execute(
                "UPDATE student_profiles SET reason=? WHERE user_id=?",
                (reason, r["user_id"]),
            )

    verb = "已写入" if apply else "预演（未写入）"
    print(f"\n{verb}：共 {len(rows)} 条画像，需改写 {changed} 条，跳过 {skipped} 条")
    if not apply and changed:
        print("确认无误后加 --apply 真正写入")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
