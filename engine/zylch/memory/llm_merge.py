"""LLM-assisted memory reconsolidation."""

import logging

from zylch.llm import LLMClient, make_llm_client


class LLMMergeService:
    """LLM-assisted memory merge for reconsolidation."""

    def __init__(self, model: str = None):
        self.client: LLMClient = make_llm_client(model=model)
        self.model = self.client.model
        self.MERGE_PROMPT = """Merge these entities into a SINGLE ENTITY:

EXISTING_ENTITY:
{existing}

NEW ENTITY:
{new}

#FIRST RULE
If you think EXISTING_ENTITY and NEW_ENTITY are not about the same entity, JUST PRODUCE ONE WORD: 

INSERT

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

        Uses prompt caching: merge instructions as cached system,
        entity data as user message.

        Args:
            existing: Current blob content
            new: New information to merge

        Returns:
            Merged content string
        """
        logging.info("MERGING CALLED")
        system = [
            {
                "type": "text",
                "text": self.MERGE_PROMPT.split("EXISTING_ENTITY:")[0].strip(),
                "cache_control": {"type": "ephemeral"},
            },
        ]
        user_content = f"EXISTING_ENTITY:\n{existing}\n\n" f"NEW ENTITY:\n{new}"
        response = self.client.create_message_sync(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=[
                {"role": "user", "content": user_content},
            ],
        )
        result = response.content[0].text.strip()
        logging.info(
            f"MERGING ENTITIES:\n" f"existing: {existing}\n" f"new:{new}\n" f"result:{result}\n\n"
        )
        return result
