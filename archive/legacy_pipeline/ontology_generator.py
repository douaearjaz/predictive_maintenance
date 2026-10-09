import json
from owlready2 import *

# 1. Créer l'ontologie
onto = get_ontology("http://test.org/pdm_ontology.owl")

with onto:
    # --- Classes ---
    class Component(Thing): pass
    class FailureMode(Thing): pass
    class Cause(Thing): pass
    class Symptom(Thing): pass
    class Sensor(Thing): pass
    class Measurement(Thing): pass
    class MaintenanceAction(Thing): pass

    # --- Propriétés ---
    class hasFailureMode(ObjectProperty): pass
    class causes(ObjectProperty): pass
    class indicates(ObjectProperty): pass
    class measuredBy(ObjectProperty): pass
    class requiresMaintenance(ObjectProperty): pass
    class partOf(ObjectProperty): pass
    class detectedBy(ObjectProperty): pass

# Définir les domaines et ranges APRÈS la création des classes
hasFailureMode.domain = [Component]
hasFailureMode.range = [FailureMode]

causes.domain = [Cause, FailureMode]
causes.range = [FailureMode]

indicates.domain = [Measurement, Symptom]
indicates.range = [FailureMode]

measuredBy.domain = [FailureMode, Measurement]
measuredBy.range = [Sensor]

requiresMaintenance.domain = [Component]
requiresMaintenance.range = [MaintenanceAction]

partOf.domain = [Component]
partOf.range = [Component]

detectedBy.domain = [FailureMode, Symptom, Measurement]
detectedBy.range = [Sensor]

# 2. Charger le graphe validé
with open("knowledge_graph_validated.json", "r", encoding="utf-8") as f:
    kg = json.load(f)

# 3. Mapping des types vers les classes
CLASS_MAP = {
    "Component": Component,
    "Failure Mode": FailureMode,
    "Cause": Cause,
    "Symptom": Symptom,
    "Sensor": Sensor,
    "Measurement": Measurement,
    "Maintenance Action": MaintenanceAction
}

# 4. Création des individus (avec réutilisation des existants)
individuals = {}
used_names = set()

for entity in kg.get("entities", []):
    name = entity.get("name")
    entity_type = entity.get("type")
    if not name or entity_type not in CLASS_MAP:
        continue

    # Nettoyer le nom pour un IRI valide
    safe_name = name.replace(" ", "_").replace("-", "_").replace("/", "_")
    
    # Vérifier si un individu avec cet IRI existe déjà
    existing = onto.search_one(iri=f"*{safe_name}")
    if existing:
        individuals[name] = existing
        used_names.add(safe_name)
        continue

    # Éviter les doublons de noms dans notre construction
    if safe_name in used_names:
        counter = 1
        while f"{safe_name}_{counter}" in used_names:
            counter += 1
        safe_name = f"{safe_name}_{counter}"
    
    cls = CLASS_MAP[entity_type]
    ind = cls(safe_name)
    individuals[name] = ind
    used_names.add(safe_name)

print(f"✅ {len(individuals)} individus créés ou réutilisés.")

# 5. Ajout des relations
PROPERTY_MAP = {
    "hasFailureMode": hasFailureMode,
    "causes": causes,
    "indicates": indicates,
    "measuredBy": measuredBy,
    "requiresMaintenance": requiresMaintenance,
    "partOf": partOf,
    "detectedBy": detectedBy
}

for rel in kg.get("relations", []):
    s = rel.get("subject")
    p = rel.get("predicate")
    o = rel.get("object")
    if not s or not p or not o:
        continue
    if s not in individuals or o not in individuals:
        print(f"⚠️ Sujet ou objet manquant : {s} -> {o}")
        continue
    if p not in PROPERTY_MAP:
        print(f"⚠️ Prédicat inconnu : {p}")
        continue

    prop = PROPERTY_MAP[p]
    prop[individuals[s]].append(individuals[o])

# 6. Sauvegarder l'ontologie
onto.save(file="ontology.owl", format="rdfxml")
print("✅ Ontologie sauvegardée dans ontology.owl")