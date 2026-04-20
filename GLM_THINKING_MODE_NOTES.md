# GLM Thinking Mode Notes

The GLM API client now disables thinking mode by default to reduce latency.

The request payload includes:

```json
"thinking": {
  "type": "disabled"
}
```

This follows the BigModel/Z.AI GLM thinking-mode documentation for GLM-4.7/GLM-5.

For SGLang/vLLM-compatible serving, the client also supports this optional flag:

```json
"chat_template_kwargs": {
  "enable_thinking": false
}
```

That flag is not sent by default because some hosted OpenAI-compatible APIs reject unknown fields.

## API Check

```bash
cd "/Users/wujinhua/Desktop/COMP584 Final Project"
python3 check_glm_api.py --timeout 100
```

To explicitly keep thinking enabled:

```bash
python3 check_glm_api.py --timeout 100 --enable-thinking
```

To additionally send the SGLang/vLLM-style flag:

```bash
python3 check_glm_api.py --timeout 100 --sglang-disable-thinking
```

## Semantic GLM Smoke Test

```bash
python3 run_semantic_glm_continuation.py \
  --input "data/airpods_pipeline_input.csv" \
  --max-reviews 2 \
  --max-iterations 2 \
  --output-dir "results_airpods_semantic_glm_smoke_2_fast" \
  --request-delay 0.3 \
  --glm-timeout 100
```

The semantic GLM runner disables thinking by default. Use `--enable-thinking` only if you want the slower reasoning mode.
