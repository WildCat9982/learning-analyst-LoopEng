# LoopEng Learning Loop capstone

## Purpose
Use the supplied app. The learner builds an analyst that studies past reviews and recommends changes to the task agent's instructions, or explains why to keep them. Do not rebuild the app or complete learner activities during setup.

## Start the app
Use Python 3.11+. Create or repair .venv if its Python executable is missing. Install requirements.txt, run the relevant checks, then use `.venv/bin/python scripts/server.py start` and verify health on port 4000. Keep saved data and learner code.

The task agent, verifier and analyst use the existing Live GPT-5.6 Luna integration. Keep the design, models and review limits unchanged. There are no customization questions. Do not generate activity or make paid calls during setup. Report the checks completed and any provider check skipped.

After startup say: "Setup is complete. Open App Preview and build your analyst in Step 1."

## Learner implementation

### Inputs
Leave app/learning_agent.py unfinished until the learner asks for help building it. Implement only `review(instructions, saved_runs, model)`.

- instructions: the original task-agent instructions.
- saved_runs: five baseline histories with actual tools, first evaluations, later corrections and allowed_evidence references.
- model: the supplied bounded model.

### Output
Return a dictionary or Pydantic structured result:
- decision="propose", explanation, an existing section, a short change and evidence_ids; or
- decision="keep", explanation and evidence_ids.

Section names may differ in case or Markdown heading markers, but must identify one existing heading unambiguously.

### Evidence
At least two different reports must support the analysis. One failure plus a comparison is valid; one failure is not a proven recurring pattern. A proposed change needs an actual failed first evaluation. Use real quotes and references. Learners may use their own prompts and supported content issue; do not force sample wording, a fixed failure count or a predetermined outcome.

### Testing
Check the analyst with temporary records and controlled responses. Keep the learner's saved work unchanged. Do not alter app/capstone.py, app/capstone_evidence.py, the verifier, fixture documents, original instructions or grading rules to improve a score. Do not write the learner's decision or outcome explanation.

The app runs and resumes reviews, saves the analyst source/input/result, validates recommendations, requests approval, triggers evaluation and calculates first-draft quality.

## Workflow
Run analysis → inspect evidence → accept or keep the instructions → automatic evaluation → explain the comparison.

Five practice requirements are used. Older new-input fixtures support regression checks. No separate Tracker, Wiki, diagnosis, reflection questionnaire or transfer exercise is required.

Compare the first evaluation of each frozen draft before and after. Later revisions never replace it. Resume a technical verification error against the same report bytes. Keep/reject uses the original instructions. A new instruction version needs a revised analyst and genuinely different instruction bytes; preserve the baseline and earlier results.

## Scoring
- Analyst: 30 points.
- Decision and explanation: 20 points.
- First-draft quality: 50 points, calculated from saved evaluations.

Pass at 70 only with an executed, supported analyst, decision and evaluation event, complete comparable evaluations, both explanations and a qualifying result. A qualifying result passes at least 12/15 checks or three more checks than before, with no criterion total declining. Keeping/rejecting qualifies only when the baseline already reaches 12/15 and performance is maintained.

A qualifying result earns 50 quality points; otherwise quality points are 50 times passed after-checks divided by 15. Missing evaluations are Not evaluated. Partial work remains submittable, with the total capped at 69 until the requirements are met.
