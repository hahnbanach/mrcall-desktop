"""LLM-assisted memory reconsolidation."""

import anthropic
from typing import Optional

MERGE_PROMPT = """Merge these memories into a single coherent blob:

EXISTING MEMORY:
{existing}

NEW INFORMATION:
{new}

Rules:
1. Use ONLY information explicitly present in the memories above - do NOT add external knowledge
2. Preserve ALL facts from both memories
3. Resolve conflicts - new information wins for time-sensitive facts (titles, locations, status)
4. #Identifiers: merge all unique identifiers
5. #About: keep as ONE sentence (update only if new info changes the definition)
6. #History: append new events chronologically, keep concise
7. Maximum 500 words total

OUTPUT FORMAT (required):
#Identifiers
Entity type: [person/company/topic]
Name: [name]
[other identifiers as available: Email, Phone, Company, Website, etc.]

#About
[One sentence describing what/who this entity is]

#History
[Chronological narrative of events and interactions]

Output ONLY the merged memory in this exact format, nothing else."""

class LLMMergeService:
    """LLM-assisted memory merge for reconsolidation."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
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
