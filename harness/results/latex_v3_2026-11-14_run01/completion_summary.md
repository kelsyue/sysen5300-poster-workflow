# Poster generation and checkpoint recovery

Generated: 2026-11-14T19:45:56+00:00

- Posters: 12
- Finished on first attempt: 8
- Finished after recovery: 4
- Still failed: 0
- Recovery attempts: 4
- Posters using checkpoints: 1
- First-attempt tokens: 213,875
- Additional recovery tokens: 96,261
- Combined tokens: 310,136
- Combined generation cost (USD): 2.120922

| Paper | Model | Outcome | Completion attempts | Checkpoint used | Total tokens |
|---|---|---|---:|---|---:|
| P01 | meta.llama-4-maverick-17b-instruct | Finished on attempt 2 | 2 | no | 13,808 |
| P01 | claude-opus-5 | Finished on attempt 2 | 2 | no | 38,893 |
| P01 | gpt-5.6-sol | Finished on attempt 2 | 2 | no | 33,068 |
| P01 | qwen.qwen3-vl-235b-a22b | Finished on attempt 1 | 1 | no | 13,579 |
| P02 | gpt-5.6-sol | Finished on attempt 1 | 1 | no | 21,596 |
| P02 | claude-opus-5 | Finished on attempt 1 | 1 | no | 40,823 |
| P02 | qwen.qwen3-vl-235b-a22b | Finished on attempt 2 | 2 | yes | 22,292 |
| P02 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 12,622 |
| P03 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 15,397 |
| P03 | claude-opus-5 | Finished on attempt 1 | 1 | no | 57,829 |
| P03 | gpt-5.6-sol | Finished on attempt 1 | 1 | no | 22,126 |
| P03 | qwen.qwen3-vl-235b-a22b | Finished on attempt 1 | 1 | no | 18,103 |

Detailed failure reasons, checkpoint run IDs and all per-poster totals: [completion_by_poster.csv](completion_by_poster.csv).

Recorded tokens only; recovery rows contain increments, not reused historical tokens. Interrupted requests without provider usage can be undercounted. Workflow success covers automatic checks; human visual review is separate.
