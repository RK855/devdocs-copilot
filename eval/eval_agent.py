"""F8 Day 11 Agent 专项评测：真实 run_agent 端到端（检索/精排/Agent LLM 全真实）。

用法（项目根目录、虚拟环境）：
  python -m eval.eval_agent

与 eval.py 共用 eval/corpus 与隔离库（临时目录 + devdocs_eval collection，跑完即删）。
不进 pytest 收集、CI 不跑。数字全部来自单次真实运行，严禁手工修改。
真实模型路径敏感：只判 expected_mode / must_contain 等形状不变量，
不写死步数与工具序列；答案全文落盘供人工抽查。
"""
import asyncio
import gc
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path

from app.services.agent_service import run_agent
from eval.eval import build_indexes

EVAL_DIR = Path(__file__).resolve().parent
QUESTIONS_FILE = EVAL_DIR / "agent_questions.json"
RESULTS_DIR = EVAL_DIR / "results"


def missing_keywords(answer: str, keywords: list[str]) -> list[str]:
    """大小写不敏感子串匹配，返回未命中的关键词列表"""
    lowered = answer.lower()
    return [kw for kw in keywords if kw.lower() not in lowered]


async def run_one(question: dict, store, bm25) -> dict:
    resp = await run_agent(question["question"], store=store, bm25=bm25)
    return {
        "id": question["id"],
        "type": question["type"],
        "expected": question["expected_mode"],
        "mode": resp.mode,
        "degraded": resp.degraded,
        "missing_kw": missing_keywords(
            resp.answer, question.get("must_contain", [])
        ),
        "sources": len(resp.sources),
        "calls": len(resp.steps),
        "rounds": max((s.step for s in resp.steps), default=0),
        "cached": sum(1 for s in resp.steps if s.cached),
        "errors": sum(1 for s in resp.steps if s.status == "error"),
        "seconds": resp.response_time,
        "answer": resp.answer,
        "steps": [s.model_dump() for s in resp.steps],
    }


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def render_report(rows: list[dict], total_chunks: int) -> str:
    answerable = [r for r in rows if r["expected"] == "agent"]
    rejectable = [r for r in rows if r["expected"] == "reject"]

    passed = [
        r for r in answerable
        if r["mode"] == "agent" and r["sources"] > 0 and not r["missing_kw"]
    ]
    rejected_ok = [r for r in rejectable if r["mode"] == "reject"]
    error_rows = [r for r in rows if r["mode"] == "error"]
    total_calls = sum(r["calls"] for r in rows)
    total_cached = sum(r["cached"] for r in rows)

    lines = [
        f"# F8 Agent 专项评测结果 {date.today().isoformat()}",
        "",
        f"- 语料：`eval/corpus/`，隔离库共 **{total_chunks}** 个 chunk（跑完即删）",
        f"- 题数：{len(rows)}（可答 {len(answerable)} / 无答案 {len(rejectable)}）",
        "- 运行：真实 Agnes（混合检索 + bge-reranker + Agent LLM 全真实），"
        "**单次运行，数字未手工修改**",
        "- 口径：可答成功=mode=agent 且 sources 非空 且 must_contain 全中（大小写不敏感）；"
        "真实模型路径敏感，不考核步数与工具序列",
        "",
        "## 总览",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| 可答成功率 | {len(passed)}/{len(answerable)} "
        f"（{len(passed) / len(answerable):.0%}） |",
        f"| 拒答准确率 | {len(rejected_ok)}/{len(rejectable)} "
        f"（{len(rejected_ok) / len(rejectable):.0%}） |",
        f"| error 态题数 | {len(error_rows)}/{len(rows)} |",
        f"| 平均工具调用数/题 | {_avg([r['calls'] for r in rows]):.2f} |",
        f"| 平均轮数/题 | {_avg([r['rounds'] for r in rows]):.2f} |",
        f"| 平均耗时/题（秒） | {_avg([r['seconds'] for r in rows]):.2f} |",
        f"| 缓存命中率（步级） | "
        f"{total_cached}/{total_calls}（{total_cached / total_calls:.0%}） |"
        if total_calls else "| 缓存命中率（步级） | 0/0 |",
        "",
        "## 逐题明细",
        "",
        "| id | 类型 | 期望 | 实际 | degraded | 关键词缺失 | sources | 调用 | 轮数 | 失败步 | 耗时(s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        kw = "、".join(r["missing_kw"]) if r["missing_kw"] else "-"
        lines.append(
            f"| {r['id']} | {r['type']} | {r['expected']} | {r['mode']} "
            f"| {'是' if r['degraded'] else '否'} | {kw} | {r['sources']} "
            f"| {r['calls']} | {r['rounds']} | {r['errors']} "
            f"| {r['seconds']:.2f} |"
        )

    failed = [
        r for r in answerable if r not in passed
    ] + [r for r in rejectable if r not in rejected_ok]
    lines += ["", "## 未通过题", ""]
    if not failed:
        lines.append("无")
    for r in failed:
        reason = []
        if r["mode"] != r["expected"]:
            reason.append(f"mode={r['mode']}")
        if r["expected"] == "agent" and r["sources"] == 0:
            reason.append("sources 为空")
        if r["missing_kw"]:
            reason.append(f"缺关键词：{'、'.join(r['missing_kw'])}")
        lines.append(f"- **{r['id']}**（{r['type']}）：{'; '.join(reason) or '未知原因'}")
    lines += [
        "",
        "## 人工抽查索引",
        "",
        f"每题完整答案与 steps 见 `agent_answers_{date.today().isoformat()}/<id>.md`。",
    ]
    return "\n".join(lines)


def dump_answers(rows: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for r in rows:
        steps_text = json.dumps(r["steps"], ensure_ascii=False, indent=2)
        (out_dir / f"{r['id']}.md").write_text(
            f"# {r['id']}（{r['type']}）\n\n"
            f"- 期望：{r['expected']}；实际：{r['mode']}；degraded：{r['degraded']}\n"
            f"- 耗时：{r['seconds']}s；调用 {r['calls']} 次 / {r['rounds']} 轮；"
            f"失败步 {r['errors']}\n"
            f"- 缺失关键词：{'、'.join(r['missing_kw']) or '无'}\n\n"
            f"## 答案\n\n{r['answer']}\n\n"
            f"## steps\n\n```json\n{steps_text}\n```\n",
            encoding="utf-8",
        )


async def main_async() -> str:
    questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    # Windows 上 Chroma 数据文件可能被进程延迟释放，TemporaryDirectory 退出时
    # 会 PermissionError；改用 mkdtemp + 结果落盘后再 ignore_errors 清理。
    tmp = tempfile.mkdtemp(prefix="devdocs_eval_")
    store = bm25 = None
    try:
        store, bm25 = build_indexes(Path(tmp))
        total_chunks = len(store.get_all_chunks())
        rows = []
        for i, q in enumerate(questions, 1):
            print(f"[{i}/{len(questions)}] {q['id']}：{q['question'][:30]} ...", flush=True)
            rows.append(await run_one(q, store, bm25))
    finally:
        # 先释放索引句柄再清库；仍有锁时容忍残留（系统临时目录，不影响结果）
        del store, bm25
        gc.collect()
        shutil.rmtree(tmp, ignore_errors=True)

    today = date.today().isoformat()
    RESULTS_DIR.mkdir(exist_ok=True)
    answers_dir = RESULTS_DIR / f"agent_answers_{today}"
    dump_answers(rows, answers_dir)
    report = render_report(rows, total_chunks)
    out_path = RESULTS_DIR / f"{today}-agent.md"
    out_path.write_text(report, encoding="utf-8")
    return (
        report
        + f"\n\n（报告：{out_path.relative_to(EVAL_DIR.parent)}；"
        f"答案：{answers_dir.relative_to(EVAL_DIR.parent)}）"
    )


if __name__ == "__main__":
    print(asyncio.run(main_async()))
