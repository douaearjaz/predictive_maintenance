"""
chunk_classifier.py

Module central de scoring domaine/bruit, réutilisé à deux niveaux :
    - Phase A/B (document entier) : corpus_audit.py, document_classifier.py
    - Phase C (chunk)             : chunk_filter.py

Une seule liste de termes ici évite que le vocabulaire diverge entre le
niveau document et le niveau chunk au fil des ajustements.
"""

import re
print("LOADING CHUNK_CLASSIFIER")
# Vocabulaire du domaine : maintenance industrielle moteur/roulement
DOMAIN_TERMS = [
    "bearing", "motor", "gearbox", "lubrication", "wear", "vibration", "crack",
    "fault", "failure", "maintenance", "rotor", "stator", "shaft", "seal",
    "gasket", "corrosion", "fatigue", "overheating", "misalignment", "imbalance",
    "friction", "degradation", "sensor", "temperature", "pressure", "inspection",
    "repair", "replace", "lubricant", "alignment", "torque", "coupling", "pump",
    "compressor", "turbine", "winding", "insulation", "short circuit", "load",
    "root cause", "corrective action", "spindle", "backlash",
]

# Vocabulaire "bruit" : jargon ML/recherche qui n'apporte pas de connaissance
# métier exploitable pour l'ontologie (algorithmes, métriques, méthodologie)
NOISE_TERMS = [
    "accuracy", "precision", "recall", "f1-score", "f1 score", "benchmark",
    "dataset", "cnn", "lstm", "transformer", "hyperparameter", "training set",
    "test set", "validation set", "university", "et al", "epoch",
    "gradient descent", "neural network", "deep learning", "state-of-the-art",
    "ablation study", "confusion matrix", "cross-validation", "random forest",
    "xgboost", "learning rate", "batch size", "auc", "roc curve", "embedding",
]


def _count_terms(text_lower: str, terms: list) -> dict:
    """Compte les occurrences de chaque terme (limites de mots, insensible à la casse).
    Retourne {terme: nombre_occurrences} pour les termes réellement trouvés."""
    matches = {}
    for term in terms:
        pattern = r'\b' + re.escape(term) + r'\b'
        count = len(re.findall(pattern, text_lower))
        if count:
            matches[term] = count
    return matches


def score_text(text: str) -> dict:
    """Calcule les scores domaine/bruit pour un texte (document entier ou chunk).

    domain_hits / noise_hits = nombre de termes DISTINCTS trouvés (évite qu'un
    seul terme répété 50 fois domine artificiellement le score).
    domain_score / noise_score = somme des occurrences (poids réel du signal).
    *_rate_per_1000w = normalisé par longueur, pour comparer équitablement
    des textes de tailles différentes (document vs chunk)."""
    text_lower = (text or "").lower()
    word_count = max(len(text_lower.split()), 1)

    domain_matches = _count_terms(text_lower, DOMAIN_TERMS)
    noise_matches = _count_terms(text_lower, NOISE_TERMS)

    domain_score = sum(domain_matches.values())
    noise_score = sum(noise_matches.values())

    return {
        "word_count": word_count,
        "domain_score": domain_score,
        "noise_score": noise_score,
        "domain_hits": len(domain_matches),
        "noise_hits": len(noise_matches),
        "domain_rate_per_1000w": round(domain_score / word_count * 1000, 2),
        "noise_rate_per_1000w": round(noise_score / word_count * 1000, 2),
        "matched_domain_terms": domain_matches,
        "matched_noise_terms": noise_matches,
    }


def classify_score(score: dict, min_domain_hits: int = 2, dominance_ratio: float = 1.0) -> str:
    """Décide 'keep' ou 'reject' à partir d'un score calculé par score_text().

    min_domain_hits : nombre minimum de termes domaine DISTINCTS requis
        (évite de garder un texte qui ne mentionne "bearing" qu'une fois par hasard).
    dominance_ratio : le score domaine doit être >= noise_score * ratio.
        Utiliser un ratio plus bas (ex: 0.5) au niveau document (les papiers
        mélangent légitimement méthodo ML et étude de cas), et un ratio plus
        strict (ex: 1.0+) au niveau chunk (on veut des chunks propres)."""
    if score["domain_hits"] < min_domain_hits:
        return "reject"
    if score["domain_score"] >= score["noise_score"] * dominance_ratio:
        return "keep"
    return "review"

sample = """
The motor bearing vibration increased significantly.
Temperature monitoring detected overheating.
"""

score = score_text(sample)

print(score)
print(classify_score(score))