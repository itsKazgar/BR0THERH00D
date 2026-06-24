"""
PERSONA EVOLUTION — small, compounding, permanent lessons
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Per the user's explicit design choices:
  - "Small compound" — each lesson is ONE short sentence, lessons ACCUMULATE
    (don't replace each other), capped so a persona's prompt can't grow
    into an incoherent essay.
  - "Once learned, always remembered" — no decay, no expiration. A lesson
    earned from a real pattern stays forever once added.
  - Fair and disciplined — a lesson is only written when there's an actual,
    statistically real pattern in the seat's WRONG calls (not "REAPER was
    wrong once"), and the lesson text describes the literal pattern found,
    never an invented or generic-sounding insight.

This module deliberately does NOT touch a persona's CORE identity (the
"You are REAPER — the collective's rug detector..." block in
agent_personas.py stays untouched forever). Lessons are appended as a
separate, clearly-marked block, so the persona's foundational voice never
gets overwritten — it only ever gains additional, earned context.
"""
import json
from collections import Counter
from core import brain

MAX_LESSONS_PER_SEAT = 6          # hard cap — oldest lesson drops when exceeded
MIN_WRONG_CALLS_FOR_PATTERN = 5    # need at least this many wrong calls to even look for a pattern
MIN_PATTERN_SHARE = 0.6            # the trait must appear in 60%+ of wrong calls to count as a real pattern

# Which context fields we look for patterns in, and how we bucket them into
# human-readable categories. Buckets matter: "mcap was exactly 743201" isn't
# a pattern, "mcap was in the 500k-2M range" can be.
_BUCKETS = {
    "mcap": [
        (0, 100_000, "very low mcap (<$100K)"),
        (100_000, 1_000_000, "low mcap ($100K-$1M)"),
        (1_000_000, 50_000_000, "mid mcap ($1M-$50M)"),
        (50_000_000, float("inf"), "high mcap (>$50M)"),
    ],
    "age_hrs": [
        (0, 1, "very new (<1h old)"),
        (1, 6, "fresh (1-6h old)"),
        (6, 48, "established (6-48h old)"),
        (48, float("inf"), "old (>48h)"),
    ],
    "liquidity": [
        (0, 15_000, "thin liquidity (<$15K)"),
        (15_000, 50_000, "moderate liquidity ($15K-$50K)"),
        (50_000, float("inf"), "deep liquidity (>$50K)"),
    ],
}


def _bucket(field: str, value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    for lo, hi, label in _BUCKETS.get(field, []):
        if lo <= v < hi:
            return label
    return None


def find_real_pattern(seat: str) -> dict:
    """
    Looks at this seat's actual WRONG, resolved votes and checks whether
    one bucket (e.g. "high mcap") shows up in MIN_PATTERN_SHARE or more of
    them. Returns {"found": False} if there's not enough data or no real
    pattern — this function refuses to invent a lesson from noise.
    """
    with brain._conn() as c:
        wrong = c.execute(
            "SELECT context FROM seat_votes WHERE seat=? AND outcome='wrong'",
            (seat,)
        ).fetchall()

    if len(wrong) < MIN_WRONG_CALLS_FOR_PATTERN:
        return {"found": False, "reason": f"only {len(wrong)} wrong calls, need {MIN_WRONG_CALLS_FOR_PATTERN}+"}

    bucket_counts = Counter()
    for row in wrong:
        try:
            ctx = json.loads(row["context"] or "{}")
        except Exception:
            continue
        for field in _BUCKETS:
            if field in ctx:
                b = _bucket(field, ctx[field])
                if b:
                    bucket_counts[b] += 1

    if not bucket_counts:
        return {"found": False, "reason": "no usable context recorded on these votes"}

    top_bucket, top_count = bucket_counts.most_common(1)[0]
    share = top_count / len(wrong)

    if share < MIN_PATTERN_SHARE:
        return {"found": False, "reason": f"no bucket exceeds {MIN_PATTERN_SHARE:.0%} of wrong calls "
                                            f"(best: {top_bucket} at {share:.0%})"}

    return {
        "found": True,
        "trait": top_bucket,
        "share": round(share, 2),
        "sample_size": len(wrong),
    }


def existing_lessons(seat: str) -> list:
    state = brain.load_state(f"persona_lessons_{seat}")
    return state.get("lessons", [])


def maybe_add_lesson(seat: str) -> dict:
    """
    Checks for a real pattern in this seat's wrong calls. If found AND it's
    not already a recorded lesson (avoid duplicate/near-duplicate lessons
    for the same trait), appends ONE new short sentence to this seat's
    lesson list. Lessons are permanent (no decay) and capped at
    MAX_LESSONS_PER_SEAT — oldest drops off if a new one is added past cap,
    keeping the persona's evolved voice bounded and readable.

    Returns {"added": bool, "lesson": str|None, "reason": str}
    """
    pattern = find_real_pattern(seat)
    if not pattern["found"]:
        return {"added": False, "lesson": None, "reason": pattern["reason"]}

    trait = pattern["trait"]
    lessons = existing_lessons(seat)

    if any(trait in l for l in lessons):
        return {"added": False, "lesson": None,
                "reason": f"already have a lesson about '{trait}'"}

    lesson = (f"You have been wrong {pattern['share']:.0%} of the time "
              f"(over {pattern['sample_size']} resolved wrong calls) specifically on "
              f"tokens with {trait} — weigh that history when you see another one.")

    lessons.append(lesson)
    if len(lessons) > MAX_LESSONS_PER_SEAT:
        lessons = lessons[-MAX_LESSONS_PER_SEAT:]  # drop oldest, keep most recent N

    brain.save_state(f"persona_lessons_{seat}", {"lessons": lessons})
    brain.remember("persona_evolution", f"{seat} learned: {lesson}",
        type="lesson", tags=f"{seat.lower()},evolution")

    return {"added": True, "lesson": lesson, "reason": "new pattern found and recorded"}


def get_evolved_system_prompt(seat: str, base_system_prompt: str) -> str:
    """
    Returns the seat's base prompt (UNCHANGED — the persona's core identity
    is never edited) plus an appended block of earned lessons, if any. This
    is the function the AI-calling code should use instead of the raw
    persona['system'] string, once a seat has any history.
    """
    lessons = existing_lessons(seat)
    if not lessons:
        return base_system_prompt

    lesson_block = "\n\nLESSONS FROM YOUR OWN TRACK RECORD (earned, not assumed):\n" + \
                   "\n".join(f"- {l}" for l in lessons)
    return base_system_prompt + lesson_block
