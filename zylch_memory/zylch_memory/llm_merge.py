"""LLM-assisted memory reconsolidation."""
import logging

import anthropic
from typing import Optional


class LLMMergeService:
    """LLM-assisted memory merge for reconsolidation."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.MERGE_PROMPT = """Merge these entities into a SINGLE ENTITY:

EXISTING_ENTITY:
{existing}

NEW ENTITY:
{new}

#FIRST RULE
If you think EXISTING_ENTITY and NEW_ENTITY are not about the same entity, JUST PRODUCE ONE WORD: 

SKIP

#OTHER Rules:
1. There must be **1** entity in the resulting entity: the resulting #IDENTIFIERS section must describe **1** entity. 
2. There must be **1** entity in the resulting entity: the resulting #ABOUT section must describe **1** entity
3. #IDENTIFIERS: if the NEW ENTITY adds new IDENTIFIERS, add them. **But they must be about the same entity (IF NOT JUST RETURN "SKIP")
5. #ABOUT: keep as ONE sentence and update it only if NEW_ENTITY adds more information
6. #HISTORY: append new events chronologically, keep concise

OUTPUT FORMAT (required):
#IDENTIFIERS
Entity type: [person/company/project]
Name: [name]
[other identifiers as available: Email, Phone, Company, Website, etc.]
**REMEMBER** These must be the identifiers of just **1** entity!!

#ABOUT
[One sentence describing what/who this entity is]
**REMEMBER** These must describe just **1** entity!!

#HISTORY
[Chronological narrative of events and interactions]

Output ONLY the merged entity in this exact format, nothing else."""


    def merge(self, existing: str, new: str) -> str:
        """Merge two memory contents using LLM.

        Args:
            existing: Current blob content
            new: New information to merge

        Returns:
            Merged content string
        """
        logging.info("MERGING CALLED")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": self.MERGE_PROMPT.format(existing=existing, new=new)
            }]
        )
        logging.info(f"MERGING ENTITIES:\nexisting: {existing}\nnew:{new}\nresult:{response.content[0].text.strip()}\n\n")
        return response.content[0].text.strip()
