from pathlib import Path
import re
from collections import Counter

import matplotlib.pyplot as plt
import pandas as pd


def print_samples(df: pd.DataFrame, sample_n: int = 5) -> None:
    print("=" * 80)
    print("Dataset preview (first rows)")
    print("=" * 80)
    print(df.head(sample_n).to_string(index=False, max_colwidth=80))

    print("\n" + "=" * 80)
    print("Random samples")
    print("=" * 80)
    random_rows = df.sample(n=sample_n, random_state=42)
    for i, row in enumerate(random_rows.itertuples(index=False), 1):
        content_preview = str(row.content).replace("\n", " ")[:180]
        print(f"[{i}] label={row.label} | title={str(row.title)[:80]}")
        print(f"    content={content_preview}...")


def plot_label_distribution(df: pd.DataFrame, output_path: Path) -> None:
    label_names = {0: "Negative", 1: "Positive"}
    counts = df["label"].value_counts().sort_index()
    labels = [label_names.get(x, str(x)) for x in counts.index]

    plt.figure(figsize=(8, 5))
    bars = plt.bar(labels, counts.values)
    plt.title("Amazon Polarity Label Distribution (train_10k)")
    plt.xlabel("Label")
    plt.ylabel("Count")

    for bar, val in zip(bars, counts.values):
        plt.text(bar.get_x() + bar.get_width() / 2, val, str(val), ha="center", va="bottom")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()


def plot_content_length(df: pd.DataFrame, output_path: Path) -> None:
    lengths = df["content"].fillna("").str.len()

    plt.figure(figsize=(8, 5))
    plt.hist(lengths, bins=40)
    plt.title("Content Length Distribution (Characters)")
    plt.xlabel("Characters")
    plt.ylabel("Frequency")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()


def print_top_words(df: pd.DataFrame, top_k: int = 12) -> None:
    stopwords = {
        "the", "a", "an", "and", "or", "is", "are", "to", "of", "in", "for", "it", "this",
        "that", "on", "with", "as", "was", "were", "be", "have", "has", "had", "i", "you",
        "my", "we", "they", "he", "she", "at", "from", "but", "not", "so", "if", "very",
    }

    def tokenize(text: str):
        return [w for w in re.findall(r"[a-zA-Z']+", text.lower()) if w not in stopwords and len(w) > 2]

    print("\n" + "=" * 80)
    print("Top words by label (quick lexical signal check)")
    print("=" * 80)

    for label in sorted(df["label"].unique()):
        text = " ".join(df.loc[df["label"] == label, "content"].fillna("").astype(str).tolist())
        freq = Counter(tokenize(text)).most_common(top_k)
        pretty = ", ".join([f"{w}:{c}" for w, c in freq])
        label_name = "Positive" if label == 1 else "Negative"
        print(f"label={label} ({label_name}): {pretty}")


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    train_path = base_dir / "amazon_polarity_small" / "train_10k.csv"
    out_dir = base_dir / "analysis_outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not train_path.exists():
        raise FileNotFoundError(f"Could not find dataset file: {train_path}")

    df = pd.read_csv(train_path)

    print(f"Loaded: {train_path}")
    print(f"Rows: {len(df)}")
    print(f"Columns: {list(df.columns)}")

    print_samples(df, sample_n=5)

    print("\n" + "=" * 80)
    print("Basic stats")
    print("=" * 80)
    print(df["label"].value_counts().sort_index().to_string())
    print("Average content length:", round(df["content"].fillna("").str.len().mean(), 2))

    label_plot = out_dir / "label_distribution.png"
    length_plot = out_dir / "content_length_distribution.png"

    plot_label_distribution(df, label_plot)
    plot_content_length(df, length_plot)
    print_top_words(df, top_k=12)

    print("\nSaved plots:")
    print(f"- {label_plot}")
    print(f"- {length_plot}")


if __name__ == "__main__":
    main()
