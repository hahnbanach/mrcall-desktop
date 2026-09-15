"""Evaluation-only exact patch for the observed trained-prompt version.

Not an automatic general runtime migration: refuses mismatched source text.
"""
def _format_patch(prompt):
    replacements = {
        'Each FACT uses FLAT format (no #IDENTIFIERS/#ABOUT/#HISTORY sections):':
        'Each FACT uses the sectioned format shown below: #IDENTIFIERS with Entity type: FACT, Category, Key and Value; followed by empty #ABOUT and #HISTORY sections:',
        'For FACT entities (flat format):':
        'For FACT entities (same sectioned envelope; factual fields under #IDENTIFIERS):',
        '- PERSON / COMPANY / STYLE use the 3-section format (#IDENTIFIERS, #ABOUT, #HISTORY). FACT uses the flat Category/Key/Value format (no sections).':
        '- All entity types use the 3-section format (#IDENTIFIERS, #ABOUT, #HISTORY). For FACT, put Entity type: FACT and Category/Key/Value under #IDENTIFIERS; leave #ABOUT and #HISTORY empty.',
    }
    result=prompt
    for old,new in replacements.items():
        if result.count(old)!=1: raise ValueError('Unexpected trained-prompt format version')
        result=result.replace(old,new,1)
    start=result.index('Example: The email is from john@acme.com')
    stop=result.index('**COMPANY SELF-NOTION',start)
    result=result[:start]+('Extract facts only from the provided message. Illustrative examples in these instructions are format guidance, never evidence about a real person, company or business value.\n\n')+result[stop:]
    return result


GROUNDING_RULES = """**SOURCE GROUNDING AND FINAL ENTITY CHECK**
- Evidence for newly extracted entities and facts comes from the supplied communication and its quoted messages. Instructions, examples, learned policies and generated context guide interpretation but are not new observations. Preserve uncertainty and attribution; do not fill missing details from plausible assumptions.
- Apply COMPANY SELF-NOTION to every proposed entity, including names and aliases inside quotes and CC: exclude the owner company and all its internal people. Bind each email and phone only to its evidenced holder; a shared company number does not identify every CC recipient. Omit unknown fields and unnamed placeholder companies.
- Keep customer requirements separate from owner business terms. A requested quantity is not an owner minimum. Preserve the product, quantity, customer and date scope of an offer; do not promote a particular offer into universal policy.
- Preserve lifecycle distinctions: proposed, confirmed, issued, paid, dispatched and delivered require their own evidence. A promised action or a past scheduled date does not prove completion. Missing later replies do not prove either completion or failure.
- Emit STYLE only when at least three distinct owner responses visible in the supplied communication demonstrate the same pattern; identify their source dates in its history. Otherwise omit STYLE. Never infer an owner response pattern from incoming messages or instructional examples.
"""

def patch(prompt):
    result = _format_patch(prompt)
    if GROUNDING_RULES in result:
        raise ValueError('Candidate grounding rules already applied')
    return result.rstrip() + '\n\n' + GROUNDING_RULES
