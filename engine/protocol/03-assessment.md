# 3. Assessment

Assessment events are the **only** evidence that changes mastery. Teaching alone never does.

## When
- After the learner independently attempts something. Not for explanations you gave.
- Typically 1-3 events per taught competency per lesson.

## Scoring (0.0-1.0)
| Score | Meaning |
|---|---|
| 0.0-0.3 | Could not do it, or wrong with a basic misconception |
| 0.4-0.6 | Partly right; needed substantial hints |
| 0.7-0.8 | Correct with minor errors or one hint |
| 0.9-1.0 | Correct, independent, and able to explain why |

Kinds: `diagnostic`, `practice`, `quiz`, `explain-back`, `project`, `review`.
Hints lower the score; say so in `--notes` (under 500 characters).

## Logging
Log immediately after each scored item:

```bash
python3 scripts/los.py log <program-id> --lesson <n> --competency <id> --kind quiz --score 0.8 --notes "one hint"
```

- Never edit or delete earlier lines. A mistaken entry is corrected by a later, explained event.
- Competency ids must exist in `program.yaml`. If you need a new competency, stop and use program authoring.
- The command refreshes `state/mastery.yaml` for you. Statuses (unseen, learning, proficient, mastered)
  come from the program's `mastery_policy`; you do not set them.
