> v1.4范围（2026-11-11）：以 [v1.4执行目标](Apple_v1.4_Codex_Execution_Pack/Codex_Goal_Prompt_v1.4.md) 及随包清单为准，保留 [V1_3_GOAL.md](V1_3_GOAL.md) 的既有能力。实际状态见 IMPLEMENTATION_STATUS.md、docs/v14_delivery.md 和 artifacts/v14/，旧验收工件是历史证据。

# Repository instructions for Codex

- Read `CODEX_GOAL.md` and `DESIGN_SPEC.md` before implementation.
- This is a local Apple Health and training workbench. Do not add HealthKit, native iOS/watchOS, accounts, cloud storage, telemetry, diet tracking or automatic full-plan generation. Public literature acquisition is authorized. Model explanation requires explicit network consent; never put private health data in public knowledge indexes.
- Never commit real Apple Health exports, databases, personal CSV files, reports, logs, or user data. Use synthetic fixtures only.
- Parse Apple XML incrementally from the ZIP stream. Never read the full XML into memory.
- Disable XML DTDs, external entities, and network access. Validate ZIP members and defend against path traversal and ZIP bombs.
- Preserve raw values, units, timestamps, offsets, sources, devices, and metadata. Derived values must carry algorithm versions and provenance.
- Missing data is not zero. Unknown is not false. Do not infer non-wear, no sleep, no food, or no menstrual cycle from an empty sample set.
- Every insight must expose its time window, sample count, quality state, evidence, and limitations.
- Use the v1.3 MetricResult contract for scientific outputs; keep implementation, software verification, corpus acquisition, theory review and scientific validation separate. Synthetic calibration is simulation_only, never real-world validity.
- No arbitrary weighted health scores, causal percentages, muscle-damage inference from HRV, precise hypertrophy estimates, or diagnostic claims.
- Keep analytics independent from the import source. A future HealthKit adapter must map to the same canonical schema; do not implement it now.
- Prefer the smallest dependency set. Use the stack in `DESIGN_SPEC.md` unless the existing repository provides a sound reason to adapt.
- Run pytest and Ruff before finishing. Do not silence failing tests to claim success.
