"""Runtime serialization contract for saved extraction prompts of any vintage."""

SERIALIZATION_CONTRACT = """

OUTPUT SERIALIZATION CONTRACT (format only):
Keep all preceding business rules, evidence requirements, exclusions and SKIP
rules. If nothing qualifies, output SKIP. Otherwise EVERY entity, including
FACT, must contain #IDENTIFIERS, #ABOUT and #HISTORY sections. Separate entities
with ---ENTITY---. This format overrides any earlier flat FACT example; it does
not authorize extracting additional information or relaxing any business rule.
For a FACT use this structure, filling only supported information:
#IDENTIFIERS
Entity type: FACT
Category: <category>
Key: <key>
#ABOUT
Value: <supported value>
#HISTORY
<source and date supported by the input>
Do not output unsectioned Category/Key/Value records or explanatory prose outside
an entity. Other entity types retain their existing identity fields.
"""
