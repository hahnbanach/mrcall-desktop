# K3 reasoning in the engine

Selecting `moonshotai/kimi-k3` with a personal OpenRouter key or MrCall credits
uses maximum reasoning through OpenRouter Chat completions, pinned to
DigitalOcean. The engine promotes the request to a combined 8192-token ceiling
before quotation or budget admission. This ceiling includes hidden reasoning;
actual receipt cost, not the reserved ceiling, is settled after completion.
Other configured models retain their existing transport. There is no automatic
model/provider fallback or inference retry.

Use the custom model preset with `OPENROUTER_MODEL=moonshotai/kimi-k3` for BYOK,
or `MRCALL_CREDITS_MODEL=moonshotai/kimi-k3` for credits. Explicit role overrides
still win and must be reviewed when migrating a profile. The credit server must
support adaptive/max controls before activating this engine configuration.

Text, function calls and function results are supported. Unsupported request
features fail before paid admission. Incomplete or malformed completions expose
no actionable content; valid cost receipts still settle. An uncertain receipt
retains its reservation for reconciliation. The timeout is 600 seconds for K3
max (reasoning is slower than the legacy disabled-reasoning transport).

Auxiliary narration, correction learning, compaction and solve helpers follow
the configured model instead of pinning Anthropic. An explicit
`ZYLCH_COMPACTION_MODEL` override is preserved. Reply classification uses K3's
supported default sampling when K3 is selected.

Saved memory extraction prompts receive a final serialization-only instruction:
FACT entities use the same structured sections as other entities. Business
rules and exclusions are retained; malformed flat output is still rejected.
This addresses conflicting instructions, not a measured new quality result.

Quality evidence remains the [reviewed comparison](../../../docs/evaluations/2026-09-16-reviewed-model-comparison.md).
Adoption does not assert general equivalence to Opus. Model configuration does
not enable automatic processing or resume a preparation queue.
