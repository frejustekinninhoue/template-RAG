from pathlib import Path

from app.config import settings
from app.resilience.retry import llm_retry
from app.services.llm_factory import create_chat_model

_PROMPT = Path("prompts/v1/completeness_judge.txt").read_text()


def _judge_model():
    return create_chat_model(
        settings.COMPLETENESS_JUDGE_PROVIDER,
        settings.COMPLETENESS_JUDGE_MODEL,
        temperature=0,
    )


@llm_retry
async def score_completeness(
    intent: str,
    sub_queries: list[str],
    response: str,
) -> float:
    """
    LLM-as-judge metric: did the response address all sub-queries?
    Returns a float in [0.0, 1.0].
    """
    sub_queries_text = "\n".join(f"- {q}" for q in sub_queries) if sub_queries else "- (single question)"

    prompt = _PROMPT.format(
        intent=intent,
        sub_queries=sub_queries_text,
        response=response,
    )

    result = await _judge_model().ainvoke(prompt)

    try:
        score = float(result.content.strip())
        return max(0.0, min(1.0, score))
    except (ValueError, AttributeError):
        return 0.5  # safe default on parse failure
