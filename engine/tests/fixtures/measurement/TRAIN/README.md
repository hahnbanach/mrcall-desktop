# TRAIN — measurement cases

Scope: the synthetic smoke cases, labels and capture harness that measure the
TRAIN role (milestone 10, decision D7: "about five mechanical smokes").
Everything here is invented: the two mailboxes, their contacts and prices.

## What the role decides

TRAIN writes the personalised prompts other roles run on. The desktop's
"Train all" (`agents.train_all`) runs three trainers in
`zylch/agents/trainers/`, each one `create_message` call whose only user turn
is a meta-prompt filled with the user's mail (and, for the memory trainer,
WhatsApp chats; for the task trainer, the memory blobs of the contacts), with
`max_tokens` 4000:

- `MessageMemoryAgentTrainer.build_memory_message_prompt` — the extraction
  prompt: four entity types (PERSON, COMPANY, STYLE, FACT) in the
  `#IDENTIFIERS` / `#ABOUT` / `#HISTORY` format separated by `---ENTITY---`,
  and a section naming the user's own person and company (`USER_PERSON`,
  `USER_COMPANY`) not to extract. The engine reads the `USER_COMPANY:` line
  back to seed the company's self-notion.
- `EmailTaskAgentTrainer.build_task_prompt` — the task-detection prompt:
  `ACTION: urgency | action | reason` or `NO_ACTION: reason`, the four
  urgency levels, and never acting on the user's own messages
  (`{user_email}`).
- `EmailerAgentTrainer.build_emailer_prompt` — the email-writing prompt:
  guidance for its four tools (`write_email`, `search_memory`, `get_email`,
  `respond_text`) and the user's style and language.

## Files

- `cases.json` — five smoke cases.
- `capture.py` — `build_requests(cases)` returns each trainer's meta-prompt
  request as the trainer passed it; `run_case(case, client)` runs the trainer
  with any client and returns what its builder returns.

## How a case drives the builder

The document's `builder` is the trainers' package; `input.builder` is the
dotted path of the case's trainer method. The harness seeds,
in a throwaway profile and under the owner the RPC uses, `input.emails`
(synced email rows), `input.whatsapp` (1-on-1 messages) and `input.memory`
(company memory blobs), then constructs the trainer as `agents_train_all`
does and runs the method. The request carries `model`: the trainers pass the
client's own, recorded as the placeholder `<role model>` that a measurement
replaces with the arm's model.

The task trainer lists its contacts from a set, so the order of the memory
blobs in its meta-prompt can differ between two processes (hash
randomisation); within one process a capture is reproducible. A prompt hash
over the captured request should not depend on that order.

## Label schema and scoring

```json
"label": {"contains": [["---ENTITY---"], ["#IDENTIFIERS"], ..., ["USER_COMPANY"], ["Ferramenta Conti"]],
          "contains_none": ["{from_email}", "{body}"], "min_chars": 1500, "complete": true}
```

Scored on the model's answer, the generated prompt:

- non-empty;
- `contains` — every group matched by one alternative (case-insensitive
  substring): the sections and tokens the meta-prompt requires and the
  engine depends on, and the user's company or language from the samples;
- `contains_none` — none of these substrings (the memory meta-prompt forbids
  `.format()` placeholders);
- `min_chars` — long enough to be the "complete, self-contained prompt" the
  meta-prompt asks for;
- `complete` — the response did not stop at `max_tokens` (a cut prompt is
  stored cut).

No language is scored: the meta-prompts fix none for the prompt they ask for,
and an English prompt over Italian samples is as valid as an Italian one. No
case is critical: a trained prompt is reviewed by running it, and a weak one
is retrained. Every check is a mechanical bar.

## Distribution

| Case | Trainer | Mailbox | Beyond the format |
|---|---|---|---|
| train-01 | memory | Italian, with a WhatsApp chat | `USER_COMPANY` names Ferramenta Conti |
| train-02 | memory | English | `USER_COMPANY` names Northwind Interiors |
| train-03 | task detection | Italian, with contact blobs | the rule on `{user_email}` |
| train-04 | task detection | English, with contact blobs | the rule on `{user_email}` |
| train-05 | emailer | Italian | the user writes in Italian and signs Giulia |
