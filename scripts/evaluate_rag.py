"""Evaluate retrieval quality, rejection quality, and latency on labelled cases."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import median
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from customer_support.rag import PolicyKnowledgeBase, get_policy_knowledge_base  # noqa: E402

DEFAULT_CASES = Path("data/evaluation/rag_cases.json")
DEFAULT_REPORT = Path("data/evaluation/rag_report.json")


def evaluate(
    knowledge_base: PolicyKnowledgeBase,
    cases: list[dict[str, Any]],
    method: str,
) -> dict[str, Any]:
    """Compute positive retrieval, out-of-scope rejection, and latency metrics."""
    # Warm up ONNX/Chroma so the three methods compare steady-state latency.
    knowledge_base.search(cases[0]["question"], top_k=3, method=method)
    hit_at_1 = 0
    hit_at_3 = 0
    reciprocal_rank = 0.0
    rejected = 0
    overall_correct = 0
    latencies_ms: list[float] = []
    details: list[dict[str, Any]] = []

    for case in cases:
        started = time.perf_counter()
        hits = knowledge_base.search(case["question"], top_k=3, method=method)
        latencies_ms.append((time.perf_counter() - started) * 1000)
        predicted = [hit["title"] for hit in hits]
        expected = case["expected_title"]
        if expected is None:
            correct = not predicted
            rejected += correct
        else:
            correct = bool(predicted and predicted[0] == expected)
            hit_at_1 += correct
            hit_at_3 += expected in predicted
            if expected in predicted:
                reciprocal_rank += 1 / (predicted.index(expected) + 1)
        overall_correct += correct
        details.append(
            {
                "question": case["question"],
                "expected": expected,
                "predicted": predicted,
                "case_type": case.get("case_type", "unspecified"),
                "correct": correct,
                "top_hit": hits[0] if hits else None,
            }
        )

    count = len(cases)
    positive_count = sum(case["expected_title"] is not None for case in cases)
    negative_count = count - positive_count
    ordered_latency = sorted(latencies_ms)
    p95_index = max(0, int(len(ordered_latency) * 0.95 + 0.9999) - 1)
    return {
        "method": method,
        "case_count": count,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "hit_at_1": round(hit_at_1 / positive_count, 4),
        "hit_at_3": round(hit_at_3 / positive_count, 4),
        "mrr_at_3": round(reciprocal_rank / positive_count, 4),
        "rejection_accuracy": round(rejected / negative_count, 4),
        "overall_accuracy": round(overall_correct / count, 4),
        "average_latency_ms": round(sum(latencies_ms) / count, 2),
        "p50_latency_ms": round(median(latencies_ms), 2),
        "p95_latency_ms": round(ordered_latency[p95_index], 2),
        "errors": [detail for detail in details if not detail["correct"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    knowledge_base = get_policy_knowledge_base()
    chunk_count = knowledge_base.ensure_index(force_rebuild=args.rebuild)
    print(f"知识库索引完成：{chunk_count} 个切片")

    methods = ["lexical", "dense", "hybrid"]
    if knowledge_base.reranker is not None:
        methods.append("hybrid_rerank")
    reports = [evaluate(knowledge_base, cases, method) for method in methods]
    for report in reports:
        print(
            f"{report['method']:>7} | "
            f"Hit@1={report['hit_at_1']:.0%} | "
            f"Hit@3={report['hit_at_3']:.0%} | "
            f"MRR@3={report['mrr_at_3']:.0%} | "
            f"拒答={report['rejection_accuracy']:.0%} | "
            f"总体={report['overall_accuracy']:.0%} | "
            f"P95={report['p95_latency_ms']:.2f}ms"
        )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"详细误差报告：{args.report}")


if __name__ == "__main__":
    main()
