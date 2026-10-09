import networkx as nx
import json

with open("bayesian_structure_dag.json", "r") as f:
    data = json.load(f)

G_dag = nx.DiGraph()
G_dag.add_edges_from([(e["from"], e["to"]) for e in data["edges"]])

print(f"🔢 Nœuds : {G_dag.number_of_nodes()}")
print(f"🔗 Arêtes : {G_dag.number_of_edges()}")
print(f"🌳 Composants connexes : {nx.number_weakly_connected_components(G_dag)}")
print(f"📊 Degré moyen : {sum(dict(G_dag.degree()).values()) / G_dag.number_of_nodes():.2f}")