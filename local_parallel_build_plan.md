
## New Build Tasks

### Task 1: Add `classify_workers` config

In `run_v2.py`:

```text
--classify-workers 1
```

In `EchoInsightV2Pipeline.__init__()`:

```python
classify_workers: int = 1
```

Normalize:

```python
self.classify_workers = max(1, int(classify_workers))
```

### Task 2: Add local parallel feature loop

In `src/echoinsight/v2_pipeline.py`, keep `_process_review()` as the single entry point.

Inside it:

```python
if self.classify_workers <= 1:
    results = self._classify_features_serial(review, feature_catalog)
else:
    results = self._classify_features_parallel(review, feature_catalog)
```

Add helpers:

```python
def _classify_features_serial(self, review: dict, features: list[dict]) -> list[dict]:
    ...

def _classify_features_parallel(self, review: dict, features: list[dict]) -> list[dict]:
    ...
```

### Task 3: Use `ThreadPoolExecutor`

Use threads because API calls are network-bound.

Sketch:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _classify_features_parallel(self, review, features):
    results_by_name = {}
    with ThreadPoolExecutor(max_workers=self.classify_workers) as pool:
        futures = {
            pool.submit(self.classifier.classify_one, review, feature): feature
            for feature in features
        }
        for future in as_completed(futures):
            feature = futures[future]
            name = feature["name"]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "feature": name,
                    "is_relevant": False,
                    "score": 0.0,
                    "evidence_span": "",
                    "reason": f"classify error: {exc}",
                }
            results_by_name[name] = result
    return [results_by_name[f["name"]] for f in features]
```

Return results in catalog order so output stays stable.

### Task 4: Add safe failure behavior

One feature failure should not kill the whole review.

If one future fails:

- record the failed feature as not relevant
- include the error in `reason`
- add the feature to diagnostics:

```text
classify_errors
```

The run can continue, and the user can inspect errors later.

### Task 5: Update timing diagnostics

Current timing should distinguish:

- total review classify time
- number of features
- `classify_workers`
- optional per-feature seconds if cheap to record

Suggested fields:

```json
{
  "agent_timing": {
    "classify_total": 12.4,
    "classify_workers": 3,
    "features_classified": 40
  }
}
```

Do not expect per-feature timings to sum to wall-clock time in parallel mode.

### Task 6: Update summary/report

Add to summary:

```json
{
  "classify_workers": 3,
  "avg_classify_seconds_per_review": 12.4,
  "avg_features_per_review": 40
}
```

Report should mention local parallel workers used.

### Task 7: Update docs

README should show:

```powershell
conda run --no-capture-output -n base python -u run_v2.py `
  --csv data/airpod.csv `
  --info api/infor_tt.md `
  --model glm-4.7-volcengine `
  --run-name airpod_parallel_5 `
  --max-reviews 5 `
  --sample-size 3 `
  --max-features 10 `
  --classify-workers 3
```

Explain:

- `--classify-workers 1` means serial
- `--classify-workers 3` means up to 3 feature classifications in flight per review
- keep workers low for hosted APIs

## Test Plan

### Test 1: Serial baseline

```text
max_reviews = 1
max_features = 5
classify_workers = 1
```

Expected:

- same behavior as current online mode
- output files generated

### Test 2: Parallel smoke

```text
max_reviews = 1
max_features = 5
classify_workers = 3
```

Expected:

- output schema same as serial
- wall-clock classify time lower than serial if provider allows concurrency
- no provider rate-limit failure

### Test 3: Small run

```text
max_reviews = 5
max_features = 10
classify_workers = 3
```

Expected:

- diagnostics include `classify_workers`
- any failed feature calls are recorded, not fatal

### Test 4: Project max run

Only after small run is stable:

```text
max_reviews = 100
max_features <= 40
classify_workers = 3 or 5
```

Do not exceed 5 workers unless the provider limit is confirmed.

## Stop Conditions

Stop increasing workers if:

- HTTP 429 / rate limit appears
- request timeout rate increases
- more than 2% feature calls fail
- average review latency stops improving
- provider returns malformed JSON more often under concurrency

## Final Intended CLI

Serial:

```powershell
conda run --no-capture-output -n base python -u run_v2.py --csv data/airpod.csv --info api/infor_tt.md --model glm-4.7-volcengine --run-name airpod_serial_5 --max-reviews 5 --sample-size 3 --max-features 10 --classify-workers 1
```

Parallel:

```powershell
conda run --no-capture-output -n base python -u run_v2.py --csv data/airpod.csv --info api/infor_tt.md --model glm-4.7-volcengine --run-name airpod_parallel_5 --max-reviews 5 --sample-size 3 --max-features 10 --classify-workers 3
```
