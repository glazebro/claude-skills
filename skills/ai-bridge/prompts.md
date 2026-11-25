# AI Bridge templates

Prompt templates for the coordinator in [`SKILL.md`](SKILL.md). Fill the `<...>` fields; add nothing else.

## Common header (every analyst prompt)

```
You are an independent analyst on a decision for this project.
Read-only: edit no files, run no git, use no network.
Under docs/ai-bridge/tasks/ open ONLY the files this prompt names. Other analysts'
files there are off limits until a later step hands them to you.

Project rules (copied verbatim, each with its path):
<rules relevant to this question from AGENTS.md, CLAUDE.md, CONTRIBUTING.md or docs
the user named, one block per source>

Default rules, used only when the project has none:
- Put the end user first.
- Never invent data. Name every missing number under missing_information.
- Cite a file path for every claim.
- Mark opinion as opinion.

Task: <objective>
Workflow checklist: <checklist from SKILL.md>
Evidence: read <task dir>/evidence.md. Verify claims against repo files where needed.
Write your full analysis, then end with ONE fenced json block of the shape below.
```

Keep the "Default rules" block only when no project rules were found.

## Analyst (step 2)

Header, then:

```
Shape: {"recommendation": "", "confidence": 0.0, "key_evidence": [], "assumptions": [],
"missing_information": [], "risks": [],
"proposed_actions": [{"type": "", "description": ""}], "would_change_my_mind": []}
Action types: analysis, code_change, production_deploy, release_or_publish, data_change,
spend, pricing_change, financial_commitment, destructive_operation, credential_change,
publish_external, other.
```

## Critique (step 3)

Header, then:

```
Read <own r0 path> (your analysis) and <other r0 path> (an independent analyst's).
Critique the other analysis on evidence, not tone. Say where it is right.
Shape: {"agree": [], "disagree": [{"point": "", "why": ""}], "weak_assumptions": [],
"missing_information": [], "strongest_counterargument": "",
"revised_confidence_in_own_view": 0.0}
```

## Rebuttal (step 4)

Header, then:

```
Read <own r0 path> (your analysis) and <critique path> (the other analyst's critique of it).
Concede what holds, maintain what does not, with reasons.
Shape: {"concede": [], "maintain": [{"point": "", "why": ""}], "final_recommendation": "",
"final_confidence": 0.0, "still_disagree": []}
```

## Report template (step 5)

```
<Single-agent run: Codex unavailable (<reason>)   <- only when it applies>

# <task id>
Project: <slug> | Workflow: <workflow> | Mode: <mode> | Agents: <list>

## Claude's original recommendation (confidence <n>)
<verbatim>
## Codex's original recommendation (confidence <n>)
<verbatim>
## Areas of agreement   (agent-listed agree/concede only, attributed)
## Areas of disagreement   (disagree + still_disagree, attributed)
## Evidence per position   (table: claim | agent | path or number)
## Weak assumptions
## Missing information
## Risks and tradeoffs
## Confidence, initial -> final   (per agent)
## Final positions
## Recommended next action
Agents converged: <...>   OR   Unresolved: user decision required (both options side by side)
## What would change the recommendation
## Proposed actions   (approval id, type, description, state)
## Execution log   (agent | step | attempts | duration | tokens if codex printed usage | timeouts)

Two agreeing models are not proof; check the evidence column.
```
