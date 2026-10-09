# Measurement-to-ontology bridge

The ontology stays unchanged. `mapping.json` defines how external measurements
refer to existing concepts. `example_observation.json` is a real feature row mapped
by the small `src/reliable/map_cwru.py` function.

The four feature values are observations about `equipment_bearing` (Motor bearing),
not new ontology facts. Their exact meanings—RMS magnitude, amplitude range,
kurtosis and crest factor—remain outside the ontology, with provenance to the
recording/channel/sample interval. No generic vibration-symptom concept exists in
the current accepted graph, so none has been invented or equated with a feature.

A future diagnosed inner-race, ball or outer-race defect can retrieve information
related to the existing `damaged bearing` concept. This is a broader contextual
association, not identity: that concept's source is general Timken bearing guidance.
It does not automatically apply every repair action to the CWRU test motor.

The proposed flow is:

```text
CWRU channel -> four numerical observations about Motor bearing
             -> separately validated bearing-condition inference
             -> damage-related knowledge and source quotations
```

Do not feed the recorded fault label into inference as sensor evidence. The example
therefore omits that label, defect size and race location from its observation
payload. They remain evaluation metadata in the original feature CSV.

The target could eventually be normal/inner-race/ball/outer-race condition. Normal
examples are currently missing, and the evaluation shows poor transfer to unseen
defect configurations. No diagnosis, fuzzy membership or probability is asserted
by this mapper. Do not copy these defect-class probabilities into the motor model's
binary functional-failure variable.

Unsupported deductions include lubrication deficiency, excess heat, misalignment
and complete functional failure. The recordings do not directly label those states.
See ../cwru_evaluation/README.md for measured feature performance and limitations.
