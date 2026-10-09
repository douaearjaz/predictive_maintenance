# Electric-motor Bayesian model — expert review packet

This is a proposed structure, not a calibrated diagnostic tool. It contains 36
binary variables and 28 source-supported dependency candidates. All 324 probability
entries are null. The user selected motor-maintenance expert elicitation; no motor
probabilities have been invented.

The builder retains CAUSES, LEADS_TO and HAS_SYMPTOM claims from the motor semantic
graph. Each dependency keeps its claim ID, qualifier, conditions and quotations.
Equipment/topic links, maintenance actions and diagnostic instrument names are not
converted to Bayesian arrows. This selection is a starting hypothesis: a textual
cause or symptom relationship alone does not validate the complete BN structure.

## What the expert does first

1. Define the motor/bearing population, operating regime, diagnostic or predictive
   purpose, assessment time and cause-exposure windows in `motor_bn.json` scope.
2. Fill `expert_variables.csv`: define present and absent for each variable and
   the measurement or threshold. Missing observations are left unknown, not absent.
3. Review `expert_dependencies.csv`: retain, change or remove each proposed edge.
   Identify missing causes, common causes and dependent symptoms. Resolve whether
   normal wear is an exposure, wear severity or a failure state. Confirm equipment
   applicability across the source manuals.
4. Update the structure and regenerate the worksheets if parents or states change.
   The generator currently overwrites its outputs: save completed expert sheets
   separately before rerunning it. Do not silently remove causes to reduce table size.
5. Only after these decisions, fill `expert_probabilities.csv`.

## How to supply a probability

Each row asks for P(variable = present | all listed parent states), for the agreed
population and time basis. A root has no parents and requires a prior probability.
Enter a number from 0 to 1 in p_present; P(absent) is its complement. Record the
expert, basis and uncertainty. A blank is not zero. Document consensus or disagreement
if several experts contribute. Literature mention counts and extraction confidence
are not probability estimates.

Example question, with no assumed answer: among comparable motors with a failed
bearing, what fraction meets the agreed increased-drag criterion at assessment?
Also estimate the increased-drag probability when the bearing has not failed.

Bearing failure currently has eight proposed parents, producing 256 combinations.
That is most of the 324 rows. Ask the expert to review mechanism detail and feasible
elicitation before filling all rows. A noisy-OR shortcut would require additional
assumptions and is not enabled. Review disconnected mechanisms for shared causes;
semantic grouping under one motor does not justify independent Bayesian components.

## Code and use

Two small Python files, with no added dependency:

- `src/reliable/build_motor_bn.py`: prepares the proposed model and worksheets.
- `src/reliable/bayesian.py`: checks probabilities and calculates exact conditional
  probabilities by enumeration for small queries.

After review, transfer each approved CSV p_present into the corresponding variable's
p_present list at row_index in a separate model copy. Record parameter_source, state
 definitions, completed scope and review status. Parent order matters: two parents
have rows absent/absent, absent/present, present/absent, present/present.

```bash
python3 -m src.reliable.build_motor_bn
# Run only after entering reviewed probabilities in a separate model copy:
python3 -m src.reliable.bayesian analysis/motor_bayesian/motor_bn.expert.json \
  --query bearing_failure --evidence '{"emits_more_heat": true}'
```

The expert model copy does not exist yet. The current blank model deliberately
refuses inference. All probabilities are validated; impossible evidence produces
an error rather than a misleading posterior. Enumeration is limited to 22
unobserved relevant variables; larger combined queries need a more efficient
inference implementation. This is suitable for small mechanism queries, not a
claim of scalable inference for arbitrary queries across the whole motor model.

Five arithmetic/validation tests use synthetic non-motor fixtures. After expert
parameterization, separately validate behavior on agreed diagnostic cases,
sensitivity to uncertain estimates, and calibration where operational data exist.
