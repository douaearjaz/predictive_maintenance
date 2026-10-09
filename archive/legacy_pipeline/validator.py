import json
from collections import defaultdict

# ================================================================
# 1. DÉFINITION DES MAPPINGS DE TYPES
# ================================================================

TYPE_MAPPING = {
    # -> Component
    "Machine": "Component",
    "System": "Component",
    "Equipment": "Component",
    "Device": "Component",
    "components": "Component",
    "Components": "Component",
    "system": "Component",
    "process": "Component",   # à voir selon contexte
    "testbed": "Component",
    "platform": "Component",
    "hardware": "Component",
    "software": "Component",  # pourrait être aussi un outil
    "tool": "Component",
    "algorithm": "Component", # peut-être pas, mais on le met pour l'exemple
    "model": "Component",     # idem
    "data": "Component",      # à ajuster

    # -> Failure Mode
    "failure mode": "Failure Mode",
    "failure modes": "Failure Mode",
    "FailureModes": "Failure Mode",
    "FailureMode": "Failure Mode",
    "Fault": "Failure Mode",
    "fault": "Failure Mode",

    # -> Symptom
    "symptom": "Symptom",
    "symptoms": "Symptom",
    "Symptoms": "Symptom",
    "observable effects": "Symptom",
    "indicator": "Symptom",   # peut-être

    # -> Cause
    "cause": "Cause",
    "causes": "Cause",
    "Causes": "Cause",
    "root cause": "Cause",

    # -> Maintenance Action
    "maintenance action": "Maintenance Action",
    "maintenance actions": "Maintenance Action",
    "MaintenanceAction": "Maintenance Action",
    "Maintenance Actions": "Maintenance Action",
    "action": "Maintenance Action",
    "repair": "Maintenance Action",

    # -> Sensor
    "sensor": "Sensor",
    "sensors": "Sensor",
    "Sensors": "Sensor",

    # -> Measurement
    "measurement": "Measurement",
    "measurements": "Measurement",
    "Measurements": "Measurement",
    "metric": "Measurement",
    "metrics": "Measurement",
    "parameter": "Measurement",
    "Parameters": "Measurement",
    "Measure": "Measurement",
}

# Types autorisés (canoniques)
ALLOWED_TYPES = {
    "Component", "Failure Mode", "Symptom", "Cause",
    "Maintenance Action", "Sensor", "Measurement"
}

# ================================================================
# 2. CHARGEMENT DU GRAPHE BRUT
# ================================================================

with open("knowledge_graph_partial.json", "r", encoding="utf-8") as f:
    raw_kg = json.load(f)

# Extraction de toutes les entités et relations
all_entities_raw = []
all_relations_raw = []
for item in raw_kg:
    all_entities_raw.extend(item.get("entities", []))
    all_relations_raw.extend(item.get("relations", []))

print(f"Entités brutes : {len(all_entities_raw)}")
print(f"Relations brutes : {len(all_relations_raw)}")

# ================================================================
# 3. NORMALISATION DES TYPES ET FILTRAGE
# ================================================================

def normalize_type(raw_type):
    """Applique le mapping et retourne le type canonique, ou None si non reconnu."""
    if not raw_type:
        return None
    # On nettoie un peu
    cleaned = raw_type.strip().lower()
    # Cherche dans le mapping (en ignorant la casse)
    for key, value in TYPE_MAPPING.items():
        if key.lower() == cleaned:
            return value
    # Fallback : si le type est déjà dans ALLOWED_TYPES, le garder
    if raw_type in ALLOWED_TYPES:
        return raw_type
    return None

# Dictionnaire pour stocker les entités uniques (par nom normalisé)
unique_entities = {}
entity_name_to_type = {}  # pour l'index

for e in all_entities_raw:
    name = e.get("name")
    raw_type = e.get("type")
    if not name:
        continue

    canonical_type = normalize_type(raw_type)
    if canonical_type is None:
        continue  # on ignore cette entité

    # Normalisation du nom (minuscules, espaces)
    norm_name = name.strip().lower()
    # Si on a déjà une entité avec ce nom, on garde la première (on pourrait fusionner)
    if norm_name not in unique_entities:
        unique_entities[norm_name] = {
            "name": name,  # on garde la forme originale
            "type": canonical_type
        }
        entity_name_to_type[norm_name] = canonical_type
    # else: déjà présente, on ignore

# Convertir en liste
all_entities = list(unique_entities.values())
print(f"Entités conservées après filtrage : {len(all_entities)}")

# ================================================================
# 4. FILTRAGE DES RELATIONS
# ================================================================

valid_relations = []
for rel in all_relations_raw:
    subj = rel.get("subject")
    pred = rel.get("predicate")
    obj = rel.get("object")
    if not subj or not pred or not obj:
        continue
    # Normaliser les noms pour retrouver les types
    subj_norm = subj.strip().lower()
    obj_norm = obj.strip().lower()
    subj_type = entity_name_to_type.get(subj_norm)
    obj_type = entity_name_to_type.get(obj_norm)
    if not subj_type or not obj_type:
        continue  # relation dont une entité a été supprimée

    # On garde la relation avec les noms originaux (on pourrait les remplacer par les noms canoniques)
    valid_relations.append({
        "subject": subj,
        "predicate": pred,
        "object": obj,
        "subject_type": subj_type,
        "object_type": obj_type
    })

print(f"Relations conservées : {len(valid_relations)}")

# ================================================================
# 5. VALIDATION PAR RÈGLES (sur les types normalisés)
# ================================================================

TYPE_RULES = {
    "hasFailureMode": ("Component", "Failure Mode"),
    "causes": (("Cause", "Failure Mode"), ("Failure Mode", "Failure Mode")),
    "indicates": ("Measurement", "Failure Mode"),
    "measuredBy": (("Failure Mode", "Sensor"), ("Measurement", "Sensor")),
    "requiresMaintenance": ("Component", "Maintenance Action"),
    "partOf": ("Component", "Component"),
    "detectedBy": ("Failure Mode", "Sensor")
}

def validate_relation(rel):
    subj_type = rel["subject_type"]
    pred = rel["predicate"]
    obj_type = rel["object_type"]

    if pred not in TYPE_RULES:
        return False, f"Unknown predicate: {pred}"

    allowed = TYPE_RULES[pred]
    # Gérer les combinaisons uniques ou multiples
    if isinstance(allowed, tuple) and len(allowed) == 2 and not isinstance(allowed[0], tuple):
        if subj_type == allowed[0] and obj_type == allowed[1]:
            return True, "OK"
        else:
            return False, f"Type mismatch: expected {allowed[0]}-{allowed[1]}"
    else:
        for subj_allowed, obj_allowed in allowed:
            if subj_type == subj_allowed and obj_type == obj_allowed:
                return True, "OK"
        return False, "Type mismatch"

validated_rels = []
rejected_rels = []

for rel in valid_relations:
    is_valid, reason = validate_relation(rel)
    if is_valid:
        validated_rels.append(rel)
    else:
        rejected_rels.append(rel)

print(f"Relations valides : {len(validated_rels)}")
print(f"Relations rejetées : {len(rejected_rels)}")

# ================================================================
# 6. SAUVEGARDE DU GRAPHE FINAL
# ================================================================
# ================================================================
# 6. FILTRAGE PAR DOMAINE (exclure les concepts académiques/ML)
# ================================================================

FORBIDDEN_TERMS = {
    "markov", "autoregressive", "rocket", "training data", "validation data",
    "dataset", "algorithm", "classifier", "machine learning", "deep learning",
    "neural network", "random forest", "svm", "xgboost", "lstm", "cnn",
    "paper", "research", "conference", "journal", "author", "university",
    "publication", "thesis", "student", "professor"
}

def is_domain_relation(rel):
    subject = rel["subject"].lower()
    obj = rel["object"].lower()
    # Vérifier si un terme interdit apparaît dans le sujet ou l'objet
    for term in FORBIDDEN_TERMS:
        if term in subject or term in obj:
            return False
    return True

# Appliquer le filtre sur les relations déjà validées
filtered_relations = [rel for rel in validated_rels if is_domain_relation(rel)]

print(f"Relations après filtrage de domaine : {len(filtered_relations)}")
print(f"Relations rejetées par le domaine : {len(validated_rels) - len(filtered_relations)}")

# ================================================================
# 7. SAUVEGARDE FINALE
# ================================================================

final_kg = {
    "entities": all_entities,
    "relations": filtered_relations
}

with open("knowledge_graph_validated.json", "w", encoding="utf-8") as f:
    json.dump(final_kg, f, indent=2, ensure_ascii=False)

# Sauvegarder également les rejets (validation + domaine) pour analyse
with open("rejected_relations_final.json", "w", encoding="utf-8") as f:
    json.dump(rejected_rels, f, indent=2, ensure_ascii=False)

print("\n✅ Validation terminée.")
print(f"Entités : {len(all_entities)}")
print(f"Relations valides (après domaine) : {len(filtered_relations)}")
print(f"Fichier final : knowledge_graph_validated.json")