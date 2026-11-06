BASE_SCOPES = frozenset({'operator.read', 'email.read', 'draft.read'})
INSTRUCTION_SCOPE = 'instructions.read'
INSTRUCTION_SOURCE = 'instructions'
DRAFT_SCOPE = 'draft.prepare'
PROPOSAL_SCOPE = 'instructions.propose'
RULE_WRITE_SCOPE = 'instructions.write'
PRICING_SCOPE = 'pricing.use'
PRICING_SOURCE = 'pricing'
PROJECT_READ_SCOPE = 'projects.read'
PROJECT_WRITE_SCOPE = 'projects.write'
PROJECT_SOURCE = 'projects'
FULL_SCOPE = 'operator.use'
SCOPES = BASE_SCOPES | {INSTRUCTION_SCOPE, DRAFT_SCOPE, PROPOSAL_SCOPE, RULE_WRITE_SCOPE, PRICING_SCOPE, PROJECT_READ_SCOPE, PROJECT_WRITE_SCOPE, FULL_SCOPE}
SCOPE_ORDER = ('operator.read', 'email.read', 'draft.read', INSTRUCTION_SCOPE, DRAFT_SCOPE, PROPOSAL_SCOPE, RULE_WRITE_SCOPE, PRICING_SCOPE, PROJECT_READ_SCOPE, PROJECT_WRITE_SCOPE, FULL_SCOPE)


def enabled_scopes(*, instructions_enabled=False, draft_enabled=False, proposals_enabled=False, rules_write_enabled=False, pricing_enabled=False, projects_enabled=False, operator_enabled=False):
    flags = (instructions_enabled, draft_enabled, proposals_enabled, rules_write_enabled, pricing_enabled, projects_enabled, operator_enabled)
    if any(type(flag) is not bool for flag in flags):
        raise ValueError('invalid_authorization_configuration')
    if operator_enabled:
        return SCOPES
    if (draft_enabled or proposals_enabled or rules_write_enabled) and not instructions_enabled:
        raise ValueError('instructions_required')
    return (BASE_SCOPES | ({INSTRUCTION_SCOPE} if instructions_enabled else set())
            | ({DRAFT_SCOPE} if draft_enabled else set())
            | ({PROPOSAL_SCOPE} if proposals_enabled else set())
            | ({RULE_WRITE_SCOPE} if rules_write_enabled else set())
            | ({PRICING_SCOPE} if pricing_enabled else set())
            | ({PROJECT_READ_SCOPE, PROJECT_WRITE_SCOPE} if projects_enabled else set()))


def dependencies_satisfied(scopes):
    return (('draft.read' not in scopes or 'email.read' in scopes)
            and (INSTRUCTION_SCOPE not in scopes or 'email.read' in scopes)
            and (DRAFT_SCOPE not in scopes or {'email.read', 'draft.read', INSTRUCTION_SCOPE} <= set(scopes))
            and (PROPOSAL_SCOPE not in scopes or INSTRUCTION_SCOPE in scopes)
            and (RULE_WRITE_SCOPE not in scopes or INSTRUCTION_SCOPE in scopes)
            and (PRICING_SCOPE not in scopes or 'operator.read' in scopes)
            and (PROJECT_READ_SCOPE not in scopes or 'operator.read' in scopes)
            and (PROJECT_WRITE_SCOPE not in scopes or PROJECT_READ_SCOPE in scopes))
