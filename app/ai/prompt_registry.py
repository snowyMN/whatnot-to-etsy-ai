from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    name: str
    version: str
    task_type: str
    file_name: str

    @property
    def path(self) -> Path:
        return PROMPTS_DIR / self.file_name


PRODUCT_ANALYSIS_PROMPT = PromptDefinition(
    name="product_analysis",
    version="1.0",
    task_type="PRODUCT_ANALYSIS",
    file_name="product_analysis.txt",
)

MARKETING_STRATEGY_PROMPT = PromptDefinition(
    name="marketing_strategy",
    version="1.0",
    task_type="MARKETING_STRATEGY",
    file_name="marketing_strategy.txt",
)

LISTING_WRITER_PROMPT = PromptDefinition(
    name="listing_writer",
    version="1.0",
    task_type="LISTING_WRITER",
    file_name="listing_writer.txt",
)

LISTING_VALIDATOR_PROMPT = PromptDefinition(
    name="listing_validator",
    version="1.0",
    task_type="LISTING_VALIDATOR",
    file_name="listing_validator.txt",
)

PROMPT_REGISTRY = {
    prompt.name: prompt
    for prompt in (
        PRODUCT_ANALYSIS_PROMPT,
        MARKETING_STRATEGY_PROMPT,
        LISTING_WRITER_PROMPT,
        LISTING_VALIDATOR_PROMPT,
    )
}


@lru_cache(maxsize=None)
def load_prompt_text(file_name: str) -> str:
    return (PROMPTS_DIR / file_name).read_text(encoding="utf-8").strip()


def render_prompt(prompt: PromptDefinition) -> str:
    return load_prompt_text(prompt.file_name)