# Training review at 912aefc93b9bd9c1cebf297a10728c69c827e266

Repository was read-only. Synthetic SQLite and knowledge fixtures were created in temporary directories, not the repository. The knowledge authority fixture explicitly identifies itself as synthetic software-only permission, not real scientific review.

## Confirmed fixes

Targeted existing regressions: 20 passed in 59.68s. Files: tests/training/test_review_training_repairs.py, tests/integration/test_review_training_ui.py, tests/integration/test_review_candidate_flow.py. Results: regressions.log and regressions.xml.

R04 now binds the loaded form revision and submits dirty fields; R07 current_targets feeds explicit group targets to candidates and saved templates; R08 completed/aborted sessions have history feedback controls; R09 endpoint changes rederive adjacent rest and retain audit history. Their direct prior reproductions are covered by the passing tests.

## Remaining findings

### P1: Current-session adverse performance is excluded from numerical candidates

- Code: src/healthzip/ui/recommendation_page.py:61-63 (unconditionally excludes current session), then 78-82 evaluates without those facts.
- Trigger: previous comparable reference is 50 kg x 12, RIR 2, acceptable. Today the same task has already ended at 4 repetitions with pain_flag=true and quality_status=technique_limited. Select another explicit group target 6-8/RIR2 and generate double progression.
- Actual: UI freezes double_progression_candidate, 52.5 kg, with only user_plan_candidate_not_guaranteed_success_or_optimal_prescription. The current adverse set is absent from source_record_ids.
- Expected: Historical baseline and pre-cutoff current observations must be separate inputs, with the current evidence surfaced and used for the specified task review; it must not silently present the same harder candidate that would be generated without the adverse set.
- Acceptance: run this sequence through AppTest and verify current adverse record provenance and a non-escalating task-review result. Retain the earlier frozen candidate separately if it was created before the adverse record; no rewriting history.

### P1: STR-26 generates a harder numerical task from a pain/technique-limited reference

- Code: src/healthzip/science/strength.py:351-370 (protocol/repetitions/unit/step gates but no reference quality or symptom eligibility), called by recommendation_page.py:77-82.
- Trigger: prior predeclared, comparable reference is 50 kg x 12, stop_reason=pain, pain_flag=true, quality_status=technique_limited; select heavier_lower_reps, target 6-8/RIR2 and available 50/52.5/55 kg.
- Actual: real UI freezes heavier_lower_reps at 52.5 kg x 6, with only trial_not_causal_effect_estimate.
- Expected: Preserve the reference as a reported fact, but do not treat a pain/technique-limited observation as an eligible basis for this numerical escalation; return specific reasons and task review.
- Acceptance: add UI-driven cases for pain, technique-limited and unknown-quality references plus a clean reference positive control; cases must inspect frozen candidate load and reason codes, not merely metric dictionaries.

### P2: Saving an old custom-action session silently upgrades its measurement definition

- Code: src/healthzip/training/service.py:1674-1682 omits definition_version; _items at 553-555 consequently resolves the latest definition rather than the session's version.
- Trigger: record a custom v1 repetitions action with targets 6-8/RIR2. Change its catalog measurement definition to v2 duration. Save the original session as a template.
- Actual: saved template and started session use definition 2 / duration, but retain repetitions targets 6-8; the original session was definition 1 / repetitions.
- Expected: Save the selected session's exact definition version and measurement condition, or require an explicit migration with mode-specific target conversion; no silent upgrade.
- Acceptance: reproduce repetition->duration and load-basis changes; assert old definition/condition preserved in saved template and new session, while new catalog uses stay at v2.

### P2: Starting another workout leaves recording attached to the earlier unfinished workout

- Code: src/healthzip/ui/training_page.py:716 sets active_training, but 732-735 uses the persistent resume_training selection without selecting that new ID.
- Trigger: leave workout 1 unfinished; enter a new title and click Start training to create workout 2.
- Actual: database creates new_id=2 and active_training_state=2, but selected_id remains 1 and the displayed session is Old unfinished session. No UI error. Subsequent add exercise/set actions target workout 1.
- Expected: successful Start training must select and render the newly created session; old unfinished session remains available for explicit resume.
- Acceptance: AppTest starts two workouts, then adds a distinct exercise/set after the second start; assert that it belongs to workout 2 and workout 1 is unchanged.

## Independent reproduction artifacts

- candidate_counterexamples.py / candidate_counterexamples.log: the first three findings, with real AppTest candidate generation and real service persistence.
- active_session_counterexample.py / active_session_counterexample.log: the fourth finding.
- regressions.log / regressions.xml: 20 passing existing targeted regressions.
