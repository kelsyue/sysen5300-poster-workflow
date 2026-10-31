# Poster generation and checkpoint recovery

Generated: 2026-10-31T20:01:14+00:00

- Posters: 60
- Finished on first attempt: 22
- Finished after recovery: 25
- Still failed: 13
- Recovery attempts: 39
- Posters using checkpoints: 38
- First-attempt tokens: 1,260,003
- Additional recovery tokens: 130,106
- Combined tokens: 1,390,109
- Combined generation cost (USD): 7.642246

| Paper | Model | Outcome | Completion attempts | Checkpoint used | Total tokens |
|---|---|---|---:|---|---:|
| P01 | claude-opus-5 | Finished on attempt 3 | 3 | yes | 25,768 |
| P01 | gpt-5.6-sol | Finished on attempt 1 | 1 | no | 11,620 |
| P01 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 8,352 |
| P01 | qwen.qwen3-vl-235b-a22b | Failed: E_PIPELINE | 2 | yes | 10,124 |
| P02 | claude-opus-5 | Failed: E_OVERFLOW | 2 | yes | 30,129 |
| P02 | gpt-5.6-sol | Finished on attempt 2 | 2 | yes | 15,883 |
| P02 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 9,125 |
| P02 | qwen.qwen3-vl-235b-a22b | Finished on attempt 2 | 2 | yes | 13,375 |
| P03 | claude-opus-5 | Failed: E_OVERFLOW | 2 | yes | 27,205 |
| P03 | gpt-5.6-sol | Finished on attempt 1 | 1 | no | 14,259 |
| P03 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 9,858 |
| P03 | qwen.qwen3-vl-235b-a22b | Finished on attempt 2 | 2 | yes | 14,417 |
| P04 | claude-opus-5 | Failed: E_OVERFLOW | 2 | yes | 56,798 |
| P04 | gpt-5.6-sol | Failed: E_OVERFLOW | 2 | yes | 31,899 |
| P04 | meta.llama-4-maverick-17b-instruct | Finished on attempt 2 | 2 | yes | 25,736 |
| P04 | qwen.qwen3-vl-235b-a22b | Finished on attempt 2 | 2 | yes | 27,300 |
| P05 | claude-opus-5 | Failed: E_OVERFLOW | 2 | yes | 32,024 |
| P05 | gpt-5.6-sol | Finished on attempt 1 | 1 | no | 14,008 |
| P05 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 11,543 |
| P05 | qwen.qwen3-vl-235b-a22b | Finished on attempt 2 | 2 | yes | 18,521 |
| P06 | claude-opus-5 | Finished on attempt 1 | 1 | no | 28,920 |
| P06 | gpt-5.6-sol | Finished on attempt 1 | 1 | no | 15,196 |
| P06 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 11,834 |
| P06 | qwen.qwen3-vl-235b-a22b | Finished on attempt 2 | 2 | yes | 14,734 |
| P07 | claude-opus-5 | Finished on attempt 2 | 2 | yes | 36,620 |
| P07 | gpt-5.6-sol | Finished on attempt 2 | 2 | yes | 18,409 |
| P07 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 12,092 |
| P07 | qwen.qwen3-vl-235b-a22b | Failed: E_PIPELINE | 2 | yes | 15,362 |
| P08 | claude-opus-5 | Finished on attempt 2 | 2 | yes | 38,905 |
| P08 | gpt-5.6-sol | Finished on attempt 2 | 2 | yes | 24,174 |
| P08 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 13,232 |
| P08 | qwen.qwen3-vl-235b-a22b | Failed: E_PIPELINE | 2 | yes | 16,938 |
| P09 | claude-opus-5 | Failed: E_OVERFLOW | 2 | yes | 48,889 |
| P09 | gpt-5.6-sol | Finished on attempt 2 | 2 | yes | 25,719 |
| P09 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 18,574 |
| P09 | qwen.qwen3-vl-235b-a22b | Failed: E_PIPELINE | 2 | yes | 23,152 |
| P10 | claude-opus-5 | Failed: E_OVERFLOW | 2 | yes | 41,537 |
| P10 | gpt-5.6-sol | Finished on attempt 1 | 1 | no | 20,017 |
| P10 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 17,056 |
| P10 | qwen.qwen3-vl-235b-a22b | Finished on attempt 2 | 2 | yes | 19,872 |
| P11 | claude-opus-5 | Finished on attempt 1 | 1 | no | 23,002 |
| P11 | gpt-5.6-sol | Finished on attempt 2 | 2 | yes | 14,698 |
| P11 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 8,748 |
| P11 | qwen.qwen3-vl-235b-a22b | Finished on attempt 2 | 2 | yes | 11,337 |
| P12 | claude-opus-5 | Failed: E_OVERFLOW | 2 | yes | 29,943 |
| P12 | gpt-5.6-sol | Finished on attempt 1 | 1 | no | 13,053 |
| P12 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 8,582 |
| P12 | qwen.qwen3-vl-235b-a22b | Finished on attempt 2 | 2 | yes | 13,455 |
| P13 | claude-opus-5 | Finished on attempt 2 | 2 | yes | 50,408 |
| P13 | gpt-5.6-sol | Finished on attempt 2 | 2 | yes | 28,593 |
| P13 | meta.llama-4-maverick-17b-instruct | Finished on attempt 2 | 2 | yes | 21,988 |
| P13 | qwen.qwen3-vl-235b-a22b | Finished on attempt 2 | 2 | yes | 26,023 |
| P14 | claude-opus-5 | Finished on attempt 2 | 2 | yes | 41,578 |
| P14 | gpt-5.6-sol | Finished on attempt 1 | 1 | no | 20,046 |
| P14 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 15,385 |
| P14 | qwen.qwen3-vl-235b-a22b | Finished on attempt 2 | 2 | yes | 19,327 |
| P15 | claude-opus-5 | Finished on attempt 2 | 2 | yes | 68,400 |
| P15 | gpt-5.6-sol | Finished on attempt 2 | 2 | yes | 40,494 |
| P15 | meta.llama-4-maverick-17b-instruct | Finished on attempt 1 | 1 | no | 30,430 |
| P15 | qwen.qwen3-vl-235b-a22b | Failed: E_PIPELINE | 2 | yes | 35,443 |

Detailed failure reasons, checkpoint run IDs and all per-poster totals: [completion_by_poster.csv](completion_by_poster.csv).

Recorded tokens only; recovery rows contain increments, not reused historical tokens. Interrupted requests without provider usage can be undercounted. Workflow success covers automatic checks; human visual review is separate.
