# Repository instructions for Codex

- Read `CODEX_GOAL.md` and `DESIGN_SPEC.md` before implementation.
- This repository is a local-only Apple Health ZIP analysis prototype. Do not add HealthKit, iOS, watchOS, accounts, cloud storage, telemetry, or model API calls in the MVP.
- Never commit real Apple Health exports, databases, personal CSV files, reports, logs, or user data. Use synthetic fixtures only.
- Parse Apple XML incrementally from the ZIP stream. Never read the full XML into memory.
- Disable XML DTDs, external entities, and network access. Validate ZIP members and defend against path traversal and ZIP bombs.
- Preserve raw values, units, timestamps, offsets, sources, devices, and metadata. Derived values must carry algorithm versions and provenance.
- Missing data is not zero. Unknown is not false. Do not infer non-wear, no sleep, no food, or no menstrual cycle from an empty sample set.
- Every insight must expose its time window, sample count, quality state, evidence, and limitations.
- No arbitrary weighted health scores, causal percentages, muscle-damage inference from HRV, precise hypertrophy estimates, or diagnostic claims.
- Keep analytics independent from the import source. A future HealthKit adapter must map to the same canonical schema; do not implement it now.
- Prefer the smallest dependency set. Use the stack in `DESIGN_SPEC.md` unless the existing repository provides a sound reason to adapt.
- Run pytest and Ruff before finishing. Do not silence failing tests to claim success.
