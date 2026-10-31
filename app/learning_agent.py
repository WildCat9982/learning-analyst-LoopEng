"""Build the analyst here; the app supplies five saved practice histories.

review(instructions, saved_runs, model) returns either:
 {"decision":"propose", "explanation":"...", "section":"### Ambiguities",
  "change":"...", "evidence_ids":["run-id:depth", "other-run:depth"]}
or {"decision":"keep", "explanation":"...", "evidence_ids":[...]}

Study the actual first evaluations and traces across different requirements.
Use allowed_evidence IDs. A proposed change needs a real failure plus another
report for comparison. One failure is an observation, not a repeated pattern.
Recommend keeping the instructions if the evidence does not justify a change.
Use the supplied model via invoke() or with_structured_output().invoke().
Never write reports, change the verifier, apply changes, or invent results.
The trusted workflow handles baseline execution, approval and evaluation.
"""

import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field


class AnalystResult(BaseModel):
    decision: Literal['propose', 'keep']
    explanation: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    section: str | None = None
    change: str | None = None

def review(instructions, saved_runs, model):
    evidence = []
    for run in saved_runs:
        first = (run.get('grading') or [{}])[0]
        for item in run.get('allowed_evidence', []):
            evidence.append({
                'id': item.get('id'),
                'report': run.get('doc_name') or run.get('id'),
                'criterion': item.get('criterion'),
                'passed': item.get('passed'),
                'quote': item.get('quote', ''),
                'first_result': first.get('result'),
            })

    headings = [line for line in instructions.splitlines() if line.startswith('#')]
    prompt = {
        'instructions': instructions,
        'existing_headings': headings,
        'quality_targets': {
            'clarity': 'Questions must name the missing decision and relevant clause, ask for a concrete choice or measurable boundary, and identify who or what can resolve each ambiguity.',
            'depth': 'Confirmed Facts must contain only stated requirement facts. Put proposed numbers, policies, formats, and implementations in questions or assumptions. Each ambiguity must include a concrete boundary or failure scenario.',
        },
        'saved_first_evaluations': evidence,
    }
    system = (
        'You are an analyst improving task-agent instructions. Study only the supplied saved '
        'first evaluations and evidence. Cite evidence_ids exactly as supplied, and cite at least '
        'two different reports. A proposal requires at least one failed criterion and a second '
        'report that supports comparison; do not treat one failure as a recurring pattern. If the '
        'evidence does not justify a safe recurring improvement, choose keep. For propose, select '
        'one exact existing heading and write a short instruction addition that addresses the '
        'supported issue. Prefer guidance that makes every question name its missing decision, '
        'relevant clause, concrete choice or measurable boundary, and resolver. Require each '
        'ambiguity to include a concrete boundary or failure scenario. Tell the task agent to '
        'keep requirement facts separate from proposed policies, numbers, formats, and '
        'implementations by putting those in questions or assumptions. Do not use vague advice '
        'such as ask what is reasonable, common, or secure. Do not invent report details or '
        'evidence IDs. Return only the structured result.'
    )
    result = model.with_structured_output(AnalystResult, method='function_calling').invoke([
        SystemMessage(content=system),
        HumanMessage(content=json.dumps(prompt)),
    ])
    return result
