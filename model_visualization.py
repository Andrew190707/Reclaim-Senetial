import json
from pathlib import Path

import matplotlib.pyplot as plt

RESULTS_FILE = Path("comparison_results.json")


def load_results():
    with RESULTS_FILE.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return list(raw.values())


def model_label(name):
    return "Random Forest" if name.startswith("RandomForest") else name


def save_bar_chart(results, metric, title, filename):
    labels = [model_label(r["model"]) for r in results]
    values = [r[metric] for r in results]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(labels, values)
    ax.set_title(title)
    ax.set_ylabel(metric.replace("_", " ").upper())
    ax.set_ylim(0, 1)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(filename, dpi=180, bbox_inches="tight")
    plt.close(fig)


def save_generalization_chart(results):
    labels = [model_label(r["model"]) for r in results]
    val = [r["val_pr_auc"] for r in results]
    temporal = [r["temporal_pr_auc"] for r in results]
    cold = [r["cold_pr_auc"] for r in results]

    x = list(range(len(labels)))
    width = 0.24

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.bar([i - width for i in x], val, width, label="Validation")
    ax.bar(x, temporal, width, label="Temporal")
    ax.bar([i + width for i in x], cold, width, label="Cold entity")
    ax.set_title("Model Generalization: PR-AUC")
    ax.set_ylabel("PR-AUC")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1)
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig("model_generalization_pr_auc.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main():
    results = load_results()

    save_bar_chart(
        results,
        "val_pr_auc",
        "Validation PR-AUC: Model Comparison",
        "model_validation_pr_auc.png",
    )

    save_bar_chart(
        results,
        "val_roc_auc",
        "Validation ROC-AUC: Model Comparison",
        "model_validation_roc_auc.png",
    )

    save_generalization_chart(results)

    print("Generated:")
    print("  model_validation_pr_auc.png")
    print("  model_validation_roc_auc.png")
    print("  model_generalization_pr_auc.png")


if __name__ == "__main__":
    main()
