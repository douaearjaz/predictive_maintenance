from owlready2 import *
import json
import networkx as nx
import matplotlib.pyplot as plt
import re

# ================================================================
# 1. Charger l'ontologie
# ================================================================
onto = get_ontology("ontology.owl").load()

# ================================================================
# 2. Fonctions de nettoyage
# ================================================================
def clean_node_name(name):
    # Supprimer les parenthèses et leur contenu
    name = re.sub(r'\([^)]*\)', '', name)
    # Remplacer les underscores par des espaces
    name = name.replace('_', ' ')
    # Supprimer les espaces multiples
    name = re.sub(r'\s+', ' ', name).strip()
    return name.title()  # Mise en forme

# Liste des termes à exclure (génériques / non pertinents)
BLACKLIST = {
    "data", "training data", "validation data", "metric", "threshold",
    "markov models", "autoregressive models", "rocket", "paper",
    "research", "conference", "journal", "author", "university"
}

def is_blacklisted(name):
    return name.lower() in BLACKLIST

# ================================================================
# 3. Extraire les nœuds et les arêtes
# ================================================================
# D'abord, construire un mapping nom original -> nom nettoyé pour chaque individu
cleaned_name_map = {}
node_types = {}  # nom nettoyé -> type OWL
for ind in onto.individuals():
    raw_name = ind.name
    clean_name = clean_node_name(raw_name)
    cleaned_name_map[raw_name] = clean_name
    # Récupérer le type (la première classe qui nous intéresse)
    for cls in ind.is_a:
        if cls.name in ["Component", "FailureMode", "Cause", "Symptom", "Sensor", "Measurement", "MaintenanceAction"]:
            node_types[clean_name] = cls.name
            break
    else:
        node_types[clean_name] = "Other"

# Maintenant, construire les nœuds et arêtes
nodes = set()
edges = []

for prop in onto.object_properties():
    relation_name = prop.name
    for subject, obj in prop.get_relations():
        s_raw = subject.name
        o_raw = obj.name

        # Nettoyer les noms
        s_clean = cleaned_name_map.get(s_raw, clean_node_name(s_raw))
        o_clean = cleaned_name_map.get(o_raw, clean_node_name(o_raw))

        # Ignorer les termes blacklistés
        if is_blacklisted(s_clean) or is_blacklisted(o_clean):
            continue

        # Ajouter les nœuds
        nodes.add(s_clean)
        nodes.add(o_clean)

        # Définir l'orientation selon votre logique
        if relation_name == "causes":
            edges.append((s_clean, o_clean))
        elif relation_name == "hasFailureMode":
            edges.append((o_clean, s_clean))   # FailureMode -> Component
        elif relation_name == "indicates":
            edges.append((o_clean, s_clean))   # FailureMode -> Symptom
        elif relation_name == "detectedBy":
            edges.append((s_clean, o_clean))   # FailureMode -> Sensor
        elif relation_name == "requiresMaintenance":
            edges.append((s_clean, o_clean))   # Component -> MaintenanceAction
        # Ignorer les autres (partOf, measuredBy, etc.)

print(f"✅ Nœuds extraits : {len(nodes)}")
print(f"✅ Arêtes brutes : {len(edges)}")

# ================================================================
# 4. Détection des cycles (avant correction)
# ================================================================
G_raw = nx.DiGraph()
G_raw.add_edges_from(edges)
cycles = list(nx.simple_cycles(G_raw))
print(f"⚠️ Cycles détectés (bruts) : {len(cycles)}")
if cycles:
    print("Exemples de cycles :")
    for c in cycles[:3]:
        print(" → ".join(c))

# ================================================================
# 5. Briser les cycles pour obtenir un DAG
# ================================================================
G_dag = nx.DiGraph()
kept_edges = []
for u, v in edges:
    G_dag.add_edge(u, v)
    if not nx.is_directed_acyclic_graph(G_dag):
        G_dag.remove_edge(u, v)
        print(f"🗑️ Arête supprimée (cycle) : {u} → {v}")
    else:
        kept_edges.append((u, v))

print(f"✅ Arêtes conservées (DAG) : {len(kept_edges)}")
if nx.is_directed_acyclic_graph(G_dag):
    print("✅ Le graphe est acyclique (DAG).")
else:
    print("❌ Erreur : le graphe n'est toujours pas acyclique !")

# ================================================================
# 6. Exporter la structure finale
# ================================================================
bn_structure = {
    "nodes": sorted(list(nodes)),
    "edges": [{"from": u, "to": v} for u, v in kept_edges]
}
with open("bayesian_structure_dag.json", "w", encoding="utf-8") as f:
    json.dump(bn_structure, f, indent=2, ensure_ascii=False)
print(f"📁 Structure sauvegardée dans bayesian_structure_dag.json")

# ================================================================
# 7. Visualisation avec couleurs par type
# ================================================================
color_map = {
    "Component": "lightblue",
    "FailureMode": "salmon",
    "Cause": "orange",
    "Symptom": "lightgreen",
    "Sensor": "yellow",
    "Measurement": "purple",
    "MaintenanceAction": "pink",
    "Other": "gray"
}

plt.figure(figsize=(16, 12))
pos = nx.spring_layout(G_dag, k=1.5, seed=42)
colors = [color_map.get(node_types.get(node, "Other"), "gray") for node in G_dag.nodes()]
nx.draw(G_dag, pos, with_labels=True, node_color=colors, node_size=2000,
        font_size=7, arrows=True, arrowstyle='->', arrowsize=15)
plt.title("Réseau bayésien (DAG) extrait de l'ontologie")
plt.tight_layout()
plt.savefig("bn_graph.png", dpi=300)
plt.show()

print("✅ Visualisation sauvegardée dans bn_graph.png")