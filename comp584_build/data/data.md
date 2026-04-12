# NLP Project 数据清单（已按 proposal 需求筛过）

根据 [NLP Project Proposal](/home/rl182/dl/NLP/project/docs/NLP%20Project%20Proposal.pdf) 里的目标，你们的系统不是只做一句话情感分类，而是要做：

- 从电商评论中抽取 `aspect / complaint / evidence`
- 生成面向商家的 actionable insights
- 支持搜索式和对话式问答，例如 “What do customers complain about this laptop?”

所以数据最好分成两层来用：

1. **主评论语料**：量大、评论真实、最好带星级/helpfulness/product id，适合做 insight generation / retrieval / evidence grounding。
2. **辅助标注语料**：哪怕规模不大，但要有 aspect 或更细粒度标签，适合做 ABSA / extraction 模块。

下面这些我优先保留，原因是：

- 我今天实际验证过它们现在还能通过 `datasets` 下载或至少能直接流式读取。
- 都有公开下载入口。
- 和你们 proposal 的任务方向匹配。

---

## 1. 首选主语料：Amazon Reviews 2023

- **链接**
  - 官方说明页: https://amazon-reviews-2023.github.io/
  - Hugging Face: https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023
- **我建议的配置**
  - `raw_review_Electronics`
  - 如果你们想先拿小一点的样本验证流程，可以先用 `raw_review_All_Beauty`
- **为什么适合**
  - 最接近你们最终目标：真实电商评论，大规模，带商品维度，适合做 complaint mining、evidence retrieval、product-level insight aggregation。
  - proposal 里举了 laptop 的例子，`Electronics` 比较对路。
  - 有 `rating`、`title`、`text`、`helpful_vote`、`verified_purchase`、`asin` 等字段，后面做 grounding 和 “按商品聚合问题” 会很好用。
- **已验证**
  - `raw_review_All_Beauty` 我本地已经成功 `load_dataset(...)`
  - `raw_review_Electronics` 我本地已经成功 `streaming=True` 读取首条样本
- **典型字段**
  - `rating`, `title`, `text`, `asin`, `parent_asin`, `helpful_vote`, `verified_purchase`, `timestamp`
- **规模**
  - 官方页写明整个 2023 版共有 `571.54M reviews`
  - `All_Beauty` 官方页给出约 `701.5K` reviews
- **下载建议**
  - 先预览：

```bash
HF_HOME=/scratch/rl182/hf_cache \
python - <<'PY'
from datasets import load_dataset
ds = load_dataset(
    "McAuley-Lab/Amazon-Reviews-2023",
    name="raw_review_Electronics",
    split="full",
    trust_remote_code=True,
    streaming=True,
)
print(next(iter(ds)))
PY
```

  - 真正落盘：

```bash
HF_HOME=/scratch/rl182/hf_cache \
python - <<'PY'
from datasets import load_dataset
ds = load_dataset(
    "McAuley-Lab/Amazon-Reviews-2023",
    name="raw_review_Electronics",
    split="full",
    trust_remote_code=True,
)
print(ds)
PY
```

- **注意**
  - 这个数据集很大，建议先抽样 5k 到 50k 做 pipeline。
  - 如果只想快速跑通系统，不要一开始就下载全量 `Electronics`。

---

## 2. 首选中等规模英文评论集：SetFit/amazon_reviews_multi_en

- **链接**
  - https://huggingface.co/datasets/SetFit/amazon_reviews_multi_en
- **为什么适合**
  - 英文、干净、直接可用，适合先做 baseline。
  - 有 `text + label`，很适合做 review understanding、情感极性打底、prompt/agent 验证。
  - 比 Amazon Reviews 2023 小很多，调试成本低。
- **已验证**
  - 今天本地已成功下载并读取。
- **字段**
  - `id`, `text`, `label`, `label_text`
- **规模**
  - `train=200000`, `validation=5000`, `test=5000`
- **下载命令**

```bash
HF_HOME=/scratch/rl182/hf_cache \
python - <<'PY'
from datasets import load_dataset
ds = load_dataset("SetFit/amazon_reviews_multi_en", split="train")
print(ds)
print(ds[0])
PY
```

- **适合在项目里怎么用**
  - 作为你们最先跑通分类/总结/检索链路的主力数据。
  - 如果最终主系统用 Amazon Reviews 2023，这个数据集很适合先做快速原型。

---

## 3. 首选辅助标注集：SemEval 2014 ABSA

- **链接**
  - https://huggingface.co/datasets/NEUDM/semeval-2014
- **为什么适合**
  - 你们 proposal 里明确提到 aspect extraction；这个正好用来补 ABSA 能力。
  - 虽然不是大规模电商平台评论主语料，但非常适合训练/评估 “aspect + sentiment + opinion” 抽取模块。
  - 尤其适合 laptop 相关场景。
- **已验证**
  - 今天本地已成功下载并读取。
- **字段**
  - `input`, `output`, `dataset`, `task_type` 等
- **规模**
  - `train=2503`, `validation=727`, `test=279`
- **下载命令**

```bash
HF_HOME=/scratch/rl182/hf_cache \
python - <<'PY'
from datasets import load_dataset
ds = load_dataset("NEUDM/semeval-2014", split="train")
print(ds[0])
PY
```

- **适合在项目里怎么用**
  - 用它来做 aspect/opinion/sentiment 抽取器的开发和 sanity check。
  - 然后把抽取器迁移到 Amazon 电商评论大语料上。

- **注意**
  - 这不是你们最终 insight system 的唯一数据源，应该把它当 **辅助监督数据**，不是主业务语料。

---

## 4. 好用的垂直领域集：Women's Clothing E-Commerce Reviews

- **链接**
  - https://huggingface.co/datasets/saattrupdan/womens-clothing-ecommerce-reviews
- **为什么适合**
  - 是真正的电商评论数据，而且结构化信息比普通 sentiment 数据多。
  - 除了评论文本，还有 `rating`、`recommended_ind`、品类字段，适合做 “哪类商品最常被抱怨什么问题” 这种 insight。
  - 规模不大，适合课程项目。
- **已验证**
  - 今天本地已成功下载并读取。
- **字段**
  - `review_text`, `rating`, `recommended_ind`, `division_name`, `department_name`, `class_name`
- **规模**
  - `train=20641`, `test=1000`, `val=1000`
- **下载命令**

```bash
HF_HOME=/scratch/rl182/hf_cache \
python - <<'PY'
from datasets import load_dataset
ds = load_dataset("saattrupdan/womens-clothing-ecommerce-reviews", split="train")
print(ds[0])
PY
```

- **适合在项目里怎么用**
  - 如果你们希望 final demo 更稳、更容易讲故事，我其实很推荐拿这个做一个垂直 demo。
  - 因为类别更集中，insight 更容易做得像产品。

---

## 5. 小而快的原型数据：Datafiniti Product Reviews

- **链接**
  - https://huggingface.co/datasets/m-ric/amazon_product_reviews_datafiniti
- **为什么适合**
  - 很小，启动成本非常低。
  - 有 `brand`、`primaryCategories`、`reviews.rating`、`reviews.text`，足够你们先验证整个 pipeline。
  - 适合做第一版 end-to-end demo。
- **已验证**
  - 今天本地已成功下载并读取。
- **字段**
  - `brand`, `primaryCategories`, `reviews.numHelpful`, `reviews.rating`, `reviews.text`
- **规模**
  - `train=6000`, `test=2000`
- **下载命令**

```bash
HF_HOME=/scratch/rl182/hf_cache \
python - <<'PY'
from datasets import load_dataset
ds = load_dataset("m-ric/amazon_product_reviews_datafiniti", split="train")
print(ds[0])
PY
```

- **适合在项目里怎么用**
  - 非常适合最早期 pipeline 打样。
  - 不建议把它当 final 主数据，因为规模偏小。

---

## 6. 可选的大规模情感基线：amazon_polarity

- **链接**
  - `datasets` 官方数据名：`amazon_polarity`
- **为什么适合**
  - 如果你们想要一个很强的情感分类 baseline，它很合适。
  - 可用于训练一个评论 polarity 模块，再把结果送给 agent 层做聚合。
- **已验证**
  - 今天本地已成功读取到 builder 信息。
- **字段**
  - `label`, `title`, `content`
- **规模**
  - `train=3600000`, `test=400000`
- **下载命令**

```bash
HF_HOME=/scratch/rl182/hf_cache \
python - <<'PY'
from datasets import load_dataset
ds = load_dataset("amazon_polarity", split="train[:10000]")
print(ds[0])
PY
```

- **注意**
  - 它更偏 **情感分类**，不够支持细粒度 aspect / complaint extraction。
  - 所以它适合做 baseline，不适合单独承担整个 proposal。

---

## 我建议你们的组合

如果你们想做得 **稳**，我建议：

1. **主语料**：`McAuley-Lab/Amazon-Reviews-2023` 的 `raw_review_Electronics`
2. **快速原型 / baseline**：`SetFit/amazon_reviews_multi_en`
3. **aspect 抽取辅助监督**：`NEUDM/semeval-2014`

这个组合最贴近 proposal。

如果你们想做得 **更容易出 demo**，我建议：

1. **主语料**：`saattrupdan/womens-clothing-ecommerce-reviews`
2. **补一个更大评论集**：`SetFit/amazon_reviews_multi_en`
3. **aspect 抽取辅助监督**：`NEUDM/semeval-2014`

这个组合更轻，更适合课程项目时间线。

---

## 我自己的优先级排序

1. `McAuley-Lab/Amazon-Reviews-2023` (`raw_review_Electronics`)
2. `SetFit/amazon_reviews_multi_en`
3. `NEUDM/semeval-2014`
4. `saattrupdan/womens-clothing-ecommerce-reviews`
5. `m-ric/amazon_product_reviews_datafiniti`
6. `amazon_polarity`

---

## 额外提醒

- Hugging Face 默认缓存会写到家目录，我这边测试时碰到过 quota 问题，建议统一加：

```bash
export HF_HOME=/scratch/rl182/hf_cache
export HUGGINGFACE_HUB_CACHE=/scratch/rl182/hf_cache/hub
export HF_DATASETS_CACHE=/scratch/rl182/hf_cache/datasets
```

- 真正做项目时，先不要追求“最大的数据”，先把下面这条链跑通：
  - review cleaning
  - aspect / complaint extraction
  - evidence sentence selection
  - product/category-level aggregation
  - LLM insight generation

- 从 proposal 来看，你们最缺的不是纯 sentiment 数据，而是：
  - **可做 product-level 聚合的评论语料**
  - **可做 aspect extraction 的辅助标注**

这也是为什么我把 `Amazon Reviews 2023 + SemEval 2014` 放在最前面。
