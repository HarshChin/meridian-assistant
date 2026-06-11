"""Dev/demo tool: show what the hybrid retriever returns for a query.

Prints the retrieval confidence band and, for each retrieved chunk, its citation token (the same
``[doc vX.Y §Section]`` that appears as a source in an answer), its fused RRF score and best dense
cosine, and the full chunk text. Runs keyless — embeddings are a local ONNX model.

Usage::

    python scripts/show_retrieval.py "Is there a surcharge for a Sunday appointment?"
    python scripts/show_retrieval.py "no-show fee" --k 3 --chars 200
"""

from __future__ import annotations

import argparse
import io
import sys

from meridian.retrieval.retriever import HybridRetriever


def main(argv: list[str] | None = None) -> int:
    """Parse args, run one retrieval, and print each chunk's citation, scores, and text."""
    if isinstance(sys.stdout, io.TextIOWrapper):  # render § / – cleanly on any console
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="What the retriever returns for a query.")
    parser.add_argument("query", help="the question to retrieve for")
    parser.add_argument("--k", type=int, default=None, help="top-k chunks (default: configured)")
    parser.add_argument(
        "--chars", type=int, default=0, help="truncate each chunk's text to N chars (0 = full)"
    )
    args = parser.parse_args(argv)

    retriever = HybridRetriever.load()
    hits, confidence = retriever.search(args.query, k=args.k)

    print(f'query: "{args.query}"')
    print(f"retrieval confidence: {confidence}  ({len(hits)} chunks)\n")
    for i, hit in enumerate(hits, 1):
        text = hit.chunk.text
        if args.chars and len(text) > args.chars:
            text = text[: args.chars].rstrip() + " …"
        print(f"{i}. {hit.chunk.citation()}   [RRF {hit.score:.4f} | cos {hit.dense_cosine:.3f}]")
        print(f"{text}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
