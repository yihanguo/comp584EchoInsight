# LLM-driven Workspace

EchoInsight V2 — LLM-driven feature extraction and scoring pipeline.

- `api/` — API connectivity checks and credential files
- `config/` — feature catalog, model registry
- `data/` — input CSV datasets
- `src/echoinsight/` — pipeline implementation
- `results_v2/` — run outputs (one subdirectory per `--run-name`)

---

## Quick Start

```bash
# 查看可用模型 alias
python run_v2.py --list-models

# API 连通性检查
python api/check_volcengine_api.py          # Volcengine GLM
python api/check_modelscope_qwen_api.py     # ModelScope
```

---

## run_v2.py 使用方法

### 最小运行（smoke test）

```bash
python run_v2.py
```

使用默认值：`data/smoke_input.csv`，5 条评论，registry 默认模型。

### 指定数据集和模型

```bash
python run_v2.py \
  --csv data/airpods_pipeline_input.csv \
  --info api/info_volcengine.md \
  --model glm-4.7-volcengine \
  --run-name airpods_glm_50 \
  --max-reviews 50 \
  --sample-size 20
```

### 切换模型（ModelScope 限流时换 GLM）

```bash
# ModelScope 路线
python run_v2.py \
  --csv data/airpods_pipeline_input.csv \
  --model deepseek-v3 \
  --run-name airpods_ds_50 \
  --max-reviews 50 \
  --sample-size 20

# GLM Volcengine 路线（限流更宽松，rpm=60）
python run_v2.py \
  --csv data/airpods_pipeline_input.csv \
  --info api/info_volcengine.md \
  --model glm-4.7-volcengine \
  --run-name airpods_glm_50 \
  --max-reviews 50 \
  --sample-size 20
```

### 常用批量运行示例

```bash
# AirPods 80 条
python run_v2.py \
  --csv data/airpods_pipeline_input.csv \
  --info api/info_volcengine.md \
  --model glm-4.7-volcengine \
  --run-name airpods_80 \
  --max-reviews 80 \
  --sample-size 20

# iPad 100 条
python run_v2.py \
  --csv data/ipad_pipeline_input.csv \
  --info api/info_volcengine.md \
  --model glm-4.7-volcengine \
  --run-name ipad_100 \
  --max-reviews 100 \
  --sample-size 10
```

```bash
python run_v2.py --csv data/ipad_pipeline_input_500.csv --info api/info_volcengine.md --model glm-4.7-volcengine --run-name ipad_glm_30 --max-reviews 20 --sample-size 5 --max-features 40 --chunk-max-reviews 4 --chunk-max-chars 6000
```

---

## 全部参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--csv` | `data/smoke_input.csv` | 输入评论 CSV |
| `--info` | `../info.md` | API 凭据文件（含 apikey / model / base_url） |
| `--model` | registry default | 模型 alias，用 `--list-models` 查看 |
| `--run-name` | `smoke` | 输出子目录名（写入 `results_v2/<run-name>/`） |
| `--max-reviews` | `5` | 处理评论数量上限 |
| `--sample-size` | `10` | init 阶段随机采样数量，用于初始化 feature corpus |
| `--max-iters` | `2` | 动态 feature 扩展最大迭代次数 |
| `--min-score` | `0.5` | 保留动态 feature 的最低分数阈值 |
| `--list-models` | — | 打印所有可用模型 alias 后退出 |

---

## 模型路线

`config/model_registry.json` 定义两条路线：

**ModelScope**（免费额度，rpm 较低约 10-20）

| alias | 模型 |
|-------|------|
| `qwen3.5-35b` | Qwen/Qwen3.5-35B-A3B |
| `qwen3-32b` | Qwen/Qwen3-32B |
| `deepseek-v3` | deepseek-ai/DeepSeek-V3.2 |
| `glm-4.7-flash` | ZhipuAI/GLM-4.7-Flash |
| `deepseek-r1-7b` | DeepSeek-R1-Distill-Qwen-7B（**默认**） |

**GLM**（速度更快，rpm 更高）

| alias | 端点 | 凭据文件 |
|-------|------|---------|
| `glm-4.7-volcengine` | Volcengine Ark，rpm=60 | `api/info_volcengine.md` |
| `glm-bigmodel` | BigModel.cn，rpm=30 | 自定义 `--info` |

---

## 输出文件

每次运行写入 `results_v2/<run-name>/`：

| 文件 | 内容 |
|------|------|
| `feature_map.csv` | 每条评论的 feature 打分矩阵 |
| `feature_scores_detail.json` | 各 feature 详细评分 |
| `initialized_feature_corpus.json` | init 阶段确定的 feature corpus |
| `review_level_diagnostics.json` | 每条评论处理细节（pass/fail、迭代次数） |
| `v2_run_log.json` | 完整运行日志 |
| `v2_summary.json` | 汇总统计（pass rate、avg iters、耗时） |
| `report.md` | 可读性报告 |
