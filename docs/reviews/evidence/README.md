# Evidence behind the 50% viewer-delivery review

Two small programs, kept because the review refers to them and because a
finding nobody can re-run is a finding nobody can check. Neither is production
code and neither belongs in an implementation branch as it stands.

## `viewer_test_review_evidence.py`

Two legacy folder shapes that composed a picture in ZMART Viewer 0.2.0
(`9ff10b0`) and refuse to compose after `d243736`. Copy it into a checkout of
the Viewer as `tests/test_review_evidence.py` and run it:

```
python3 -m pytest tests/test_review_evidence.py -q
```

It passes at `9ff10b0` and fails at `d243736`. When the legacy reconciliation is
fixed so that a disagreement means "no declared window" rather than a refusal,
both cases should pass again — at which point these are worth keeping as
permanent tests rather than as evidence.

## `check_the_two_validators_agree.py`

The acquisition display description is validated independently in two
repositories, and the two must accept and refuse exactly the same documents.
This puts twenty-four adversarial documents through both and compares the
verdict and the canonical output: unknown fields at three levels, booleans
where numbers belong, `NaN` and `Infinity`, repeated keys and indices, shuffled
and non-zero-based indices, malformed colours, a degenerate range, a display
window with no range, and a few more.

Fill in the two paths at the top, then:

```
python3 check_the_two_validators_agree.py
```

At `ca8e176d` and `d243736` it reports twenty-four cases and no disagreements.

This is a check run by hand, which is the weakness the review names: it will not
notice the day somebody edits one validator and not the other. The lasting form
is a shared fixture directory — the documents and their expected verdicts as
plain JSON, vendored into both repositories and asserted by a test in each. This
script is a good place to take that list from.
