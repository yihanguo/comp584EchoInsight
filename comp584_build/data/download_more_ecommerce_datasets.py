from pathlib import Path
import re

import pandas as pd
from datasets import load_dataset


DATASETS = [
    {
        "name": "amazon_polarity",
        "split": "train",
        "text_col": "content",
        "label_col": "label",
    },
    {
        "name": "Ha1200/amazon-reviews-sentiment-analysis",
        "split": "train",
        "text_col": "reviewText",
        "label_col": "overall",
    },
    {
        "name": "SetFit/amazon_reviews_multi_en",
        "split": "train",
        "text_col": "text",
        "label_col": "label",
    },
    {
        "name": "juliensimon/amazon-shoe-reviews",
        "split": "train",
        "text_col": "text",
        "label_col": "labels",
    },
    {
        "name": "saattrupdan/womens-clothing-ecommerce-reviews",
        "split": "train",
        "text_col": "review_text",
        "label_col": "rating",
    },
    {
        "name": "m-ric/amazon_product_reviews_datafiniti",
        "split": "train",
        "text_col": "reviews.text",
        "label_col": "reviews.rating",
    },
]


def safe_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name)


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    out_root = base_dir / "ecommerce_candidates"
    out_root.mkdir(parents=True, exist_ok=True)

    summary = []

    for cfg in DATASETS:
        name = cfg["name"]
        split = cfg["split"]
        text_col = cfg["text_col"]
        label_col = cfg["label_col"]

        print(f"\n=== downloading: {name} ({split}) ===")
        ds = load_dataset(name, split=split)

        n = min(10000, len(ds))
        ds = ds.select(range(n))
        df = ds.to_pandas()

        keep_cols = [c for c in [text_col, label_col] if c in df.columns]
        slim = df[keep_cols].copy()
        slim = slim.rename(columns={text_col: "text", label_col: "label"})

        folder = out_root / safe_name(name)
        folder.mkdir(parents=True, exist_ok=True)

        out_csv = folder / "sample_10k.csv"
        slim.to_csv(out_csv, index=False)

        summary.append(
            {
                "dataset": name,
                "rows_saved": len(slim),
                "text_col": text_col,
                "label_col": label_col,
                "output_csv": str(out_csv),
            }
        )

        print(f"saved: {out_csv} | rows={len(slim)}")

    summary_df = pd.DataFrame(summary)
    summary_path = out_root / "summary.csv"
    summary_df.to_csv(summary_path, index=False)
    print(f"\nsummary saved: {summary_path}")


if __name__ == "__main__":
    main()
