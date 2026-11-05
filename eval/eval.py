"""F7 检索评测：vector / bm25 / hybrid / hybrid+rerank 四组逐级对比（真实 API）。

用法（在项目根目录、虚拟环境中）：
  python -m eval.eval --dump   灌入 eval/corpus 并打印每个 chunk 的坐标，供标注 questions.json
  python -m eval.eval          跑全量题目四组评测（默认重复 3 轮），结果打印并写 eval/results/YYYY-MM-DD.md
  python -m eval.eval --runs 1 只跑一轮（快速回归）

评测库使用系统临时目录 + 独立 collection（devdocs_eval），与线上 uploads/data 完全隔离，
跑完自动清理。数字全部来自真实运行，严禁手工修改。

题目标注约定（questions.json）：
  relevant_chunks 非空：可答题，计入 Recall@5 / MRR / Precision@5
  relevant_chunks 为空：无答案题，计入"无答案拒答正确率"（has_evidence 应为 False）
"""
import argparse
import asyncio
import contextlib
import gc
import json
import shutil
import statistics
import tempfile
import time
from datetime import date
from pathlib import Path

from app.config import settings
from app.db.bm25_store import BM25Store
from app.db.vector_store import VectorStore
from app.services.chunker import split_text
from app.services.rerank_service import rerank
from app.services.retrieval_service import retrieve

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_DIR = EVAL_DIR / "corpus"
QUESTIONS_FILE = EVAL_DIR / "questions.json"
RESULTS_DIR = EVAL_DIR / "results"

GROUPS = ("vector", "bm25", "hybrid", "hybrid+rerank")
COLLECTION = "devdocs_eval"


def build_indexes(workdir: Path):
    """把 eval/corpus 灌入隔离向量库 + 全新 BM25 内存索引"""
    store = VectorStore(path=workdir / "chroma", collection_name=COLLECTION)
    bm25 = BM25Store()
    for path in sorted(CORPUS_DIR.glob("*.md")):
        chunks = split_text(path.read_text(encoding="utf-8"))
        if not chunks:
            continue
        doc_id = path.stem
        store.add_document(doc_id, chunks, path.name)
        bm25.add_document(doc_id, chunks, path.name)
    return store, bm25


def dump_chunks(store, full: bool = False) -> None:
    """打印 filename / chunk_index / 预览，标注 relevant_chunks 时以此输出为准。

    --full 打印 chunk 全文（多节合并时用于确认内容归属）。
    """
    chunks = store.get_all_chunks()
    current_file = None
    for c in chunks:
        if c["filename"] != current_file:
            current_file = c["filename"]
            print(f"\n=== {current_file} ===")
        if full:
            print(f'\n--- chunk-{c["chunk_index"]} ---')
            print(c["content"])
        else:
            preview = c["content"].replace("\n", " ")[:60]
            print(f'  chunk-{c["chunk_index"]}: {preview}')
    print(f"\n共 {len(chunks)} 个 chunk")


async def _search_group(question: str, group: str, store, bm25):
    """返回 (hits, has_evidence, 耗时秒)。

    hybrid+rerank 组完全复刻生产 chat_service 终态：精排后 top1 低于
    RERANK_THRESHOLD（且 scored=True）视为二次门拒答；fail-open 时沿用粗排门结论。
    """
    mode = "hybrid" if group == "hybrid+rerank" else group
    started = time.perf_counter()
    result = await retrieve(question, mode=mode, vector_store=store, bm25=bm25)
    has_evidence = result.has_evidence
    hits = result.hits
    if group == "hybrid+rerank":
        reranked = await asyncio.to_thread(rerank, question, hits, settings.TOP_K)
        hits = reranked.hits
        if (reranked.scored and (not hits
                or hits[0]["score"] < settings.RERANK_THRESHOLD)):
            has_evidence = False
    return hits[: settings.TOP_K], has_evidence, time.perf_counter() - started


def judge(hits: list[dict], gold: set[tuple]) -> tuple[float, float, float]:
    """单题三指标：Recall@5（命中任一相关块）、MRR 倒数排名、Precision@5"""
    ranked = [(h["filename"], h["chunk_index"]) for h in hits]
    hit_positions = [i + 1 for i, key in enumerate(ranked) if key in gold]
    recall = 1.0 if hit_positions else 0.0
    reciprocal_rank = 1.0 / hit_positions[0] if hit_positions else 0.0
    precision = len(hit_positions) / len(ranked) if ranked else 0.0
    return recall, reciprocal_rank, precision


async def _run_once(questions: list[dict], store, bm25) -> dict:
    """跑完整一轮题目，返回该轮的分组统计。"""
    stats: dict[str, dict] = {
        g: {"recall": [], "rr": [], "precision": [], "seconds": 0.0} for g in GROUPS
    }
    reject: dict[str, dict] = {g: {"correct": 0, "total": 0} for g in GROUPS}
    misses: dict[str, list[str]] = {g: [] for g in GROUPS}

    for q in questions:
        gold = {tuple(x) for x in q["relevant_chunks"]}
        for group in GROUPS:
            hits, has_evidence, elapsed = await _search_group(
                q["question"], group, store, bm25
            )
            stats[group]["seconds"] += elapsed
            if not gold:
                # 无答案题：证据门应当拦住
                reject[group]["total"] += 1
                if not has_evidence:
                    reject[group]["correct"] += 1
                continue
            recall, rr, precision = judge(hits, gold)
            stats[group]["recall"].append(recall)
            stats[group]["rr"].append(rr)
            stats[group]["precision"].append(precision)
            if recall == 0.0:
                misses[group].append(str(q["id"]))

    return {"stats": stats, "reject": reject, "misses": misses}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _mean_std(values: list[float]) -> tuple[float, float]:
    """样本均值与样本标准差；单次运行标准差记 0。"""
    mean = _mean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return mean, std


async def run_eval(workdir: Path, runs: int = 3) -> str:
    questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    store, bm25 = build_indexes(workdir)
    total_chunks = len(store.get_all_chunks())
    runs = max(1, runs)

    run_results = [await _run_once(questions, store, bm25) for _ in range(runs)]

    answerable = len(run_results[0]["stats"]["vector"]["recall"])
    doc_count = len(list(CORPUS_DIR.glob("*.md")))
    lines = [
        f"# F7 检索评测结果 {date.today().isoformat()}",
        "",
        f"- 语料：`eval/corpus/` {doc_count} 份文档，共 **{total_chunks}** 个 chunk",
        f"- 题数：{len(questions)}（可答题 {answerable} / 无答案题 "
        f"{run_results[0]['reject']['vector']['total']}）",
        f"- 运行次数：**{runs}**（表格展示均值 ± 样本标准差；单次运行不显示标准差）",
        f"- 指标口径：Recall@5=top5 命中任一标注块的题占比；MRR=首个相关块 1/rank 均值；"
        f"Precision@5=top5 中相关块占比",
        f"- hybrid+rerank 组按生产终态判定：精排 top1 < "
        f"{settings.RERANK_THRESHOLD:g}（RERANK_THRESHOLD）记为二次门拒答",
        "",
        "| 系统 | Recall@5 | MRR | Precision@5 | 无答案拒答正确率 | 平均耗时/题(秒) |",
        "|---|---|---|---|---|---|",
    ]

    def cell(mean: float, std: float, digits: int = 3) -> str:
        base = f"{mean:.{digits}f}"
        return f"{base} ± {std:.{digits}f}" if runs > 1 else base

    for group in GROUPS:
        run_recall = [_mean(r["stats"][group]["recall"]) for r in run_results]
        run_rr = [_mean(r["stats"][group]["rr"]) for r in run_results]
        run_precision = [_mean(r["stats"][group]["precision"]) for r in run_results]
        run_seconds = [
            r["stats"][group]["seconds"] / len(questions) for r in run_results
        ]
        run_reject = []
        for r in run_results:
            rj = r["reject"][group]
            run_reject.append(
                rj["correct"] / rj["total"] if rj["total"] else 0.0
            )

        recall_mean, recall_std = _mean_std(run_recall)
        rr_mean, rr_std = _mean_std(run_rr)
        precision_mean, precision_std = _mean_std(run_precision)
        seconds_mean, seconds_std = _mean_std(run_seconds)
        reject_mean, reject_std = _mean_std(run_reject)
        rj = run_results[0]["reject"][group]
        reject_cell = (
            f"{reject_mean * 100:.1f}% ± {reject_std * 100:.1f}"
            if runs > 1
            else f"{rj['correct']}/{rj['total']}"
        )
        seconds_cell = (
            f"{seconds_mean:.2f} ± {seconds_std:.2f}" if runs > 1 else f"{seconds_mean:.2f}"
        )
        lines.append(
            f"| {group} | {cell(recall_mean, recall_std)} | {cell(rr_mean, rr_std)} "
            f"| {cell(precision_mean, precision_std)} | {reject_cell} | {seconds_cell} |"
        )

    lines += ["", "## 各组未命中（Recall@5=0）的题目 id（任一运行未命中即列出）", ""]
    for group in GROUPS:
        union: list[str] = []
        for r in run_results:
            for qid in r["misses"][group]:
                if qid not in union:
                    union.append(qid)
        lines.append(f"- **{group}**：{', '.join(union) if union else '无'}")

    if runs > 1:
        lines += [
            "",
            "## 逐次运行明细",
            "",
            "| 运行 | vector R@5 | bm25 R@5 | hybrid R@5 | rerank R@5 | rerank MRR "
            "| rerank 拒答 | rerank 耗时/题(s) |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for i, r in enumerate(run_results, start=1):
            rj = r["reject"]["hybrid+rerank"]
            values = [
                _mean(r["stats"][g]["recall"]) for g in GROUPS
            ]
            lines.append(
                f"| #{i} | {values[0]:.3f} | {values[1]:.3f} | {values[2]:.3f} "
                f"| {values[3]:.3f} | {_mean(r['stats']['hybrid+rerank']['rr']):.3f} "
                f"| {rj['correct']}/{rj['total']} "
                f"| {r['stats']['hybrid+rerank']['seconds'] / len(questions):.2f} |"
            )

    report = "\n".join(lines)
    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"{date.today().isoformat()}.md"
    out_path.write_text(report, encoding="utf-8")
    return report + f"\n\n（已写入 {out_path.relative_to(EVAL_DIR.parent)}）"


async def detail(workdir: Path) -> None:
    """逐题诊断：打印每题首个相关块在各组的排名（- 表示 top5 未命中），
    无答案题打印各组 has_evidence 与 rerank top1 分数。"""
    questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    store, bm25 = build_indexes(workdir)

    print(f"{'id':<9}{'类型':<6}", end="")
    for g in GROUPS:
        print(f"{g:<16}", end="")
    print()
    for q in questions:
        gold = {tuple(x) for x in q["relevant_chunks"]}
        print(f'{q["id"]:<10}{q["type"]:<6}', end="")
        for group in GROUPS:
            hits, has_evidence, _elapsed = await _search_group(
                q["question"], group, store, bm25
            )
            ranked = [(h["filename"], h["chunk_index"]) for h in hits]
            top1 = hits[0]["score"] if hits else None
            score_txt = f"{top1:.3f}" if top1 is not None else "空"
            if gold:
                positions = [i + 1 for i, k in enumerate(ranked) if k in gold]
                pos_txt = str(positions[0]) if positions else "-"
                # 可答题在 rerank 列附带 top1 分数，便于观测阈值间隔
                cell = f"{pos_txt}/{score_txt}" if group == "hybrid+rerank" else pos_txt
            else:
                cell = f"拒={'是' if not has_evidence else '否'}/{score_txt}"
            print(f"{cell:<16}", end="")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="F7 检索评测")
    parser.add_argument("--dump", action="store_true", help="只打印 chunk 坐标供标注")
    parser.add_argument("--full", action="store_true", help="与 --dump 搭配：打印 chunk 全文")
    parser.add_argument("--dump-file", default=None, help="与 --dump 搭配：把坐标写入指定文件（UTF-8）")
    parser.add_argument("--detail", action="store_true", help="逐题打印首个相关块排名/拒答诊断")
    parser.add_argument("--runs", type=int, default=3, help="完整评测重复次数，默认 3")
    args = parser.parse_args()

    # Windows 上 Chroma 数据文件可能被进程延迟释放，TemporaryDirectory 退出时
    # 会 PermissionError；改用 mkdtemp + 结束后 ignore_errors 清理（与 eval_agent 一致）。
    tmp = tempfile.mkdtemp(prefix="devdocs_eval_")
    store = None
    try:
        workdir = Path(tmp)
        store, _bm25 = build_indexes(workdir)
        if args.dump:
            if args.dump_file:
                out = Path(args.dump_file)
                out.parent.mkdir(parents=True, exist_ok=True)
                with out.open("w", encoding="utf-8") as f, contextlib.redirect_stdout(f):
                    dump_chunks(store, full=args.full)
                print(f"chunk 坐标已写入 {out}")
            else:
                dump_chunks(store, full=args.full)
        elif args.detail:
            asyncio.run(detail(workdir))
        else:
            print(asyncio.run(run_eval(workdir, runs=args.runs)))
    finally:
        del store
        gc.collect()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
