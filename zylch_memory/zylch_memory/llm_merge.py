"""LLM-assisted memory reconsolidation."""

import anthropic
from typing import Optional

MERGE_PROMPT = """Merge these memories into a single coherent blob:

EXISTING MEMORY:
{existing}

NEW INFORMATION:
{new}

Rules:
1. Preserve ALL facts from both memories
2. Resolve conflicts - new information wins for time-sensitive facts (titles, locations, status)
3. Keep the result concise and well-organized
4. Use natural language prose, not bullet points
5. Maximum 500 words

Output ONLY the merged memory text, nothing else."""

class LLMMergeService:
    """LLM-assisted memory merge for reconsolidation."""

    def __init__(self, api_key: str, model: str = "claude-3-5-haiku-20241022"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def merge(self, existing: str, new: str) -> str:
        """Merge two memory contents using LLM.

        Args:
            existing: Current blob content
            new: New information to merge

        Returns:
            Merged content string
        """
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": MERGE_PROMPT.format(existing=existing, new=new)
            }]
        )
        return response.content[0].text.strip()
