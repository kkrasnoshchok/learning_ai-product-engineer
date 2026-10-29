# Assessment policy (Examiner, with the Tutor as sole recorder)

Scoring scale, kinds and logging commands live in `engine/protocol/03-assessment.md`; this policy adds rules around them.

1. **Independent assessment.** An item is independent only if the author did not see the lesson transcript and the
   learner got no hints before answering. The Examiner receives the competency definition, items already used in
   teaching (to avoid reuse), and the learner's answer, not the tutoring dialogue.
2. **Explicit rubrics.** Every item ships with criteria written before scoring: what a full-credit answer contains,
   what partial credit looks like, and the misconception each wrong pattern signals.
3. **Assisted work is not mastery.** Record the assistance level (`none`, `hint-1`..`hint-4`, `worked-example`).
   Any assisted item scores below 0.9 (the top band means independent). Worked-example reveal scores in the 0.0-0.3 band
   or is not logged. Copying an answer the tutor just gave is not evidence.
4. **Evidence-based mastery.** Only logged assessment events move mastery. Teaching, learner self-report and
   confident tone are not evidence. Mastery status is derived by `los.py`, never asserted by an agent.
5. **Misconception tracking.** Name each misconception as a short, falsifiable claim ("believes X implies Y").
   Put it in the event `--notes`, and in the lesson `Handoff` while unresolved. A misconception is resolved only after
   an independent item that would have exposed it is answered correctly. Re-test it in later lessons.
6. **Spaced repetition.** Reviews are derived from the log by the scheduler in protocol 09 (`review due`); `review_after_days` remains the legacy lesson-context hint. Prefer retrieval
   of due competencies, interleaved with the current focus, over re-teaching. A failed review shortens the next
   interval by being re-tested earlier in the following lesson.
7. **Calibration.** Prefer lower scores when evidence is ambiguous; ask a follow-up item instead of rounding up.
8. **No leakage.** Do not show the learner the rubric before they answer. Do not reuse a scored item verbatim.
9. **Evidence classes (Phase 6).** Assisted never counts; unverified (free-form) never earns strict `mastered`; only committed, rubric-backed independent assessments are "valid". See protocol 09.
10. **Private rubrics.** The key lives in `assessments/*/private.yaml`, outside every context pack. Hiding it from the learner is procedural; the Tutor must not quote it, and objective checks beat judged ones.
11. **Uncertainty is data.** Low confidence goes to human review; never round up to clear it.
