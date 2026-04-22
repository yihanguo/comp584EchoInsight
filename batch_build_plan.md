# Batch Build Plan

## Scope

Build Volcengine Ark batch inference for the current phase-1 `ClassifyAgent` flow.

Hard project limit:

```text
max_reviews <= 100
max_features <= 40
max_classify_rows = 100 * 40 = 4000
```

We should design for 4000 rows, not for massive production scale.

## Safety Defaults

Use conservative settings first:

```text
batch_max_tasks_per_file = 500
batch_max_active_jobs = 1
batch_poll_interval_seconds = 60
completion_window = 1d
batch_dry_run_first = true
```

Largest expected run:

```text
4000 classify rows -> 8 shards at 500 rows/shard
```

Do not run more than one active batch job until:

- dry run works
- one real shard works
- output parser works
- resume from existing job id works

## Build Tasks

### Task 1: Keep `infor_tt.md` as runtime credential file

Current local file:

```text
api/infor_tt.md
```

Existing required fields:

```text
apikey = ...
model = glm-4-7-251222
base_url = https://ark.cn-beijing.volces.com/api/v3
```

Batch needs extra fields later:

```text
project_name = default
region = cn-beijing
openapi_host = open.volcengineapi.com
tos_bucket = ...
tos_input_prefix = batch-inference-job/dataset/
tos_output_prefix = batch-inference-job/output/
foundation_model_name = glm-4-7-251222
foundation_model_version = ...
completion_window = 1d
batch_max_tasks_per_file = 500
batch_max_active_jobs = 1
batch_poll_interval_seconds = 60
batch_dry_run_first = true
```

If this makes `infor_tt.md` too crowded, use a separate ignored file:

```text
api/infor_tt_batch.md
```

### Task 2: Extract prompt builder from `ClassifyAgent`

File:

```text
src/echoinsight/classify_agent.py
```

Add:

```python
def build_classify_one_prompt(self, review: dict, feature: dict) -> str:
    ...
```

Then `classify_one()` should call the helper.

Reason:

- online mode and batch mode must use identical prompts
- prompt changes should happen in one place

### Task 3: Build local batch JSONL

Create:

```text
src/echoinsight/batch_inference.py
```

Functions:

```python
def build_classify_tasks(reviews: list[dict], features: list[dict]) -> list[dict]:
    ...

def write_batch_input_jsonl(tasks: list[dict], path: Path) -> None:
    ...

def shard_tasks(tasks: list[dict], max_tasks_per_file: int = 500) -> list[list[dict]]:
    ...
```

Each task must include:

```json
{
  "custom_id": "review_id=0|feature=noise_cancellation",
  "review_id": "0",
  "feature": "noise_cancellation"
}
```

The JSONL request body should use the same prompt as `classify_one()`.

### Task 4: Parse fake batch output first

Before real Volcengine submission, create a parser that can read a fake output JSONL and produce the same internal schema as online mode.

Function:

```python
def parse_batch_output_jsonl(path: Path, task_map: dict) -> list[dict]:
    ...
```

Parser must handle:

- output rows not in input order
- missing rows
- invalid JSON
- API error rows
- model output that is JSON inside `choices[0].message.content`
- feature name mismatch

### Task 5: Add batch output integration to pipeline

File:

```text
src/echoinsight/v2_pipeline.py
```

Add a batch path that returns the same review records as online `_process_review()`.

The final output files should remain unchanged:

- `feature_map.csv`
- `feature_scores_detail.json`
- `review_level_diagnostics.jsonl`
- `v2_summary.json`
- `report.md`

### Task 6: Add CLI switch

File:

```text
run_v2.py
```

Add:

```text
--classify-mode online|batch
--batch-max-tasks-per-file 500
--batch-dry-run
```

Default:

```text
--classify-mode online
```

### Task 7: Add Volcengine OpenAPI client

Create:

```text
src/echoinsight/volcengine_batch.py
```

Implement later, after local JSONL and parser are stable:

```python
def create_batch_inference_job(...):
    ...

def get_batch_inference_job(...):
    ...
```

Must support:

- `DryRun=true`
- idempotency reuse when duplicate active job exists
- saving job id to `results_v2/<run_name>/batch_job.json`

### Task 8: Add TOS upload/download

Only after task parsing works locally.

Need confirm:

- TOS credentials source
- bucket name
- region
- object key prefix
- whether existing Ark key is enough or separate AK/SK is required

## Test Plan

### Test 1: Local no-network JSONL build

Command target:

```text
1 review, 2 features
```

Expected:

- `batch_input_part000.jsonl`
- `batch_task_map.json`
- valid unique `custom_id`

### Test 2: Fake output parser

Use hand-written output rows.

Expected:

- produces feature results
- handles one invalid row
- writes parse error

### Test 3: DryRun

Submit only one tiny shard:

```text
1 review * 2 features = 2 rows
DryRun=true
```

Expected:

- Fire CreateBatchInferenceJob validation
- Treat `DryRunOperation` as success
- No real inference cost

### Test 4: Real smoke batch

```text
1 review * 5 features = 5 rows
active jobs = 1
```

Expected:

- one job id
- output JSONL downloaded
- existing feature output files generated

### Test 5: Max planned run

Only after previous tests pass:

```text
100 reviews * up to 40 features = up to 4000 rows
500 rows/shard
active jobs = 1
```

Expected:

- up to 8 shards
- run shards sequentially
- all outputs generated

## Stop Conditions

Stop and inspect manually if:

- dry run fails
- output schema is different from expected
- more than 5% rows fail parsing
- duplicate active job id cannot be reused
- any shard cost/latency looks abnormal
- TOS output is missing or incomplete

## Open Questions

Need verify in official docs/API Explorer:

- exact batch JSONL schema for chat completions
- exact query API for batch job status
- exact output JSONL shape
- valid `FoundationModel.Name` and `ModelVersion`
- TOS authentication method
