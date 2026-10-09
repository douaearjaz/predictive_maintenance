import json
import numpy as np
from pgmpy.models import BayesianNetwork
from pgmpy.factors.discrete import TabularCPD
from pgmpy.inference import VariableElimination

# ================================================================
# 1. Charger la structure
# ================================================================
with open("bayesian_structure_dag.json", "r") as f:
    data = json.load(f)

edges = [(e["from"], e["to"]) for e in data["edges"]]
model = BayesianNetwork(edges)

# ================================================================
# 2. Afficher les nœuds et leurs parents
# ================================================================
print("🔍 Nœuds du modèle :")
for node in model.nodes():
    parents = model.get_parents(node)
    print(f"  - {node} (parents : {parents if parents else 'aucun'})")

# ================================================================
# 3. Fonction pour créer une CPT aléatoire (binaire)
# ================================================================
def random_cpd(variable, parents, var_card=2, state_names=None):
    """
    Génère une CPT aléatoire pour une variable binaire.
    Si state_names n'est pas fourni, on utilise ['OK', 'Faulty'] pour toutes.
    """
    if state_names is None:
        state_names = {var: ["OK", "Faulty"] for var in [variable] + list(parents)}
    
    parent_cards = [var_card] * len(parents)
    total_parent_states = np.prod(parent_cards) if parent_cards else 1
    # Dirichlet(alpha=1) pour avoir des distributions uniformes (ou légèrement variables)
    values = np.random.dirichlet(np.ones(var_card), size=total_parent_states).T
    return TabularCPD(
        variable=variable,
        variable_card=var_card,
        values=values,
        evidence=parents,
        evidence_card=parent_cards,
        state_names=state_names
    )

# ================================================================
# 4. Ajouter une CPT pour chaque nœud
# ================================================================
# On garde un dictionnaire pour les state_names si on veut personnaliser
state_names_dict = {}

for node in model.nodes():
    parents = model.get_parents(node)
    # Pour simplifier, on utilise des états binaires "OK" / "Faulty" pour tous
    # Mais on peut adapter selon le type de variable (ex: "High"/"Low" pour les mesures)
    cpd = random_cpd(node, parents, var_card=2)
    model.add_cpds(cpd)
    # On peut stocker les state_names pour le debug
    state_names_dict[node] = ["OK", "Faulty"]

# ================================================================
# 5. Vérifier le modèle
# ================================================================
if model.check_model():
    print("✅ Modèle valide (toutes les CPTs sont cohérentes).")
else:
    print("❌ Problème dans le modèle.")
    # Afficher les erreurs éventuelles
    print(model.get_cpds())

# ================================================================
# 6. Sauvegarder le modèle (optionnel)
# ================================================================
# pgmpy permet de sauvegarder en XMLBIF, mais on peut aussi sauvegarder les CPTs en JSON
model_data = {
    "edges": edges,
    "cpds": [
        {
            "variable": cpd.variable,
            "evidence": cpd.evidence,
            "values": cpd.values.tolist(),
            "state_names": cpd.state_names
        }
        for cpd in model.get_cpds()
    ]
}
with open("bayesian_model_complete.json", "w") as f:
    json.dump(model_data, f, indent=2)

print("📁 Modèle complet sauvegardé dans bayesian_model_complete.json")

# ================================================================
# 7. (Optionnel) Tester une inférence
# ================================================================
infer = VariableElimination(model)

# Exemple : probabilité a priori que "Motor" soit défaillant
if "Motor" in model.nodes():
    prob = infer.query(variables=["Motor"])
    print(f"\n🔮 Probabilité a priori pour Motor :\n{prob}")
else:
    print("\n⚠️ Le nœud 'Motor' n'existe pas dans le modèle.")
    print("   Voici la liste des nœuds disponibles :", sorted(model.nodes()))