"""ETAPE 4 - Extraire des regles interpretables et les comparer a des modeles opaques.

1. Chaque indicateur de l'etape 2 devient une CONDITION lisible par un enseignant
   ("pas commence 48 h avant l'echeance", "au moins 3 erreurs d'affilee"...).
   La notion du devoir, tiree du graphe, est aussi une condition possible.
2. On cherche les combinaisons de 1 a 3 conditions qui annoncent la difficulte
   (note < 70) nettement plus souvent que la moyenne : ce sont les REGLES.
   Pour chaque regle : support (part des episodes concernes), confiance
   (part en difficulte parmi eux) et lift (confiance / taux moyen).
3. On mesure honnetement ce que valent ces regles, en validation croisee
   GROUPEE PAR ETUDIANT : un meme etudiant n'est jamais a la fois dans
   l'apprentissage et dans le test (sinon on mesurerait qu'on reconnait l'etudiant).
   Comparaison : regles, arbre de decision court, regression logistique
   (interpretables) et foret aleatoire (opaque).
4. Les regles et leurs activations (alertes) sont ajoutees au graphe, avec les
   sessions et executions qui les justifient (lt:justifiePar).

Usage :
    python etape4_regles.py --resultats resultats --notions notions.csv
"""
import argparse
import itertools
import os

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier, export_text

# ---------------------------------------------------------------------------
# CONDITIONS : seuils fixes a la main, lisibles, a discuter avec les enseignants
# ---------------------------------------------------------------------------
CONDITIONS = {
    "pas_commence_a_J-2":        lambda r: not r["commence"],
    "temps_actif<30min":         lambda r: r["temps_actif_min"] < 30,
    "moins_de_10_executions":    lambda r: r["n_executions"] < 10,
    "une_seule_session":         lambda r: r["n_sessions"] <= 1,
    "3_erreurs_d_affilee":       lambda r: r["serie_erreurs_max"] >= 3,
    "2_types_d_erreur_ou_plus":  lambda r: r["n_types_erreur"] >= 2,
    "taux_d_echec>=30%":         lambda r: r["n_executions"] >= 5 and r["taux_echec_exec"] >= 0.30,
    "code_non_compilable>=30%":  lambda r: r["commence"] and r["part_non_compilable"] >= 0.30,
    "5_collages_ou_plus":        lambda r: r["n_collages"] >= 5,
}
ACTIONS = {
    "pas_commence_a_J-2":       "relancer l'etudiant et proposer un point de depart (premiere tache guidee)",
    "temps_actif<30min":        "verifier la charge de travail et proposer un creneau d'accompagnement",
    "moins_de_10_executions":   "encourager a executer et tester le code au fil de l'ecriture",
    "une_seule_session":        "conseiller de repartir le travail sur plusieurs sessions",
    "3_erreurs_d_affilee":      "proposer une aide ciblee sur le message d'erreur qui se repete",
    "2_types_d_erreur_ou_plus": "entretien court pour identifier la confusion de fond",
    "taux_d_echec>=30%":        "montrer une demarche de debogage pas a pas",
    "code_non_compilable>=30%": "rappel sur la syntaxe et sur l'ecriture par petits increments",
    "5_collages_ou_plus":       "verifier la comprehension du code colle (explication orale)",
}
FEATURES = ["commence", "debut_h_avant", "n_sessions", "temps_actif_min", "n_executions", "taux_echec_exec",
            "serie_erreurs_max", "n_types_erreur", "part_non_compilable", "n_collages", "ratio_effacement"]


def transactions(ep, notions):
    """Ensemble des conditions vraies pour chaque episode (+ la notion du devoir)."""
    tx = []
    for r in ep.to_dict("records"):
        t = {nom for nom, cond in CONDITIONS.items() if cond(r)}
        t.add("notion=" + notions[r["AssignmentID"]])
        tx.append(t)
    return tx


def miner(tx, y, min_support=0.05, min_lift=1.3, max_len=3, top=10, avec_notion=True):
    n, base = len(y), y.mean()
    items = sorted(i for i in set().union(*tx) if avec_notion or not i.startswith("notion="))
    regles = []
    for L in range(1, max_len + 1):
        for combo in itertools.combinations(items, L):
            if sum(i.startswith("notion=") for i in combo) > 1:
                continue                                    # une seule notion par regle
            c = set(combo)
            couvre = np.array([c <= t for t in tx])
            if couvre.sum() / n < min_support:
                continue
            conf = y[couvre].mean()
            if base and conf / base >= min_lift:
                regles.append({"si": list(combo), "couvre": frozenset(np.flatnonzero(couvre)),
                               "support": couvre.mean(), "confiance": conf,
                               "lift": conf / base, "n": int(couvre.sum()), "n_difficulte": int(y[couvre].sum())})
    # on garde une regle seulement si elle fait mieux que ses sous-regles deja retenues
    regles.sort(key=lambda r: (-r["confiance"], len(r["si"]), -r["support"]))
    gardees = []
    for r in regles:
        if any(set(g["si"]) <= set(r["si"]) and g["confiance"] >= r["confiance"] - 0.03 for g in gardees):
            continue
        if any(g["couvre"] == r["couvre"] for g in gardees):   # memes episodes : doublon
            continue
        gardees.append(r)
        if len(gardees) == top:
            break
    return gardees, base


def score(regles, tx):
    return np.array([max([r["confiance"] for r in regles if set(r["si"]) <= t] or [0.0]) for t in tx])


def evaluer(X, tx, y, groupes, n_plis=5):
    modeles = {
        "Regles (interpretable)": None,
        "Arbre profondeur 3 (interpretable)": lambda: DecisionTreeClassifier(max_depth=3, min_samples_leaf=8,
                                                                            class_weight="balanced", random_state=0),
        "Regression logistique (interpretable)": lambda: make_pipeline(StandardScaler(),
                                                                       LogisticRegression(class_weight="balanced", max_iter=1000)),
        "Foret aleatoire (opaque)": lambda: RandomForestClassifier(n_estimators=400, min_samples_leaf=3,
                                                                   class_weight="balanced", random_state=0),
    }
    pred = {m: np.zeros(len(y)) for m in modeles}
    for tr, te in GroupKFold(n_splits=n_plis).split(X, y, groupes):
        regles, _ = miner([tx[i] for i in tr], y[tr])
        pred["Regles (interpretable)"][te] = score(regles, [tx[i] for i in te])
        for m, fab in modeles.items():
            if fab:
                pred[m][te] = fab().fit(X.iloc[tr], y[tr]).predict_proba(X.iloc[te])[:, 1]
    base = y.mean()
    res = []
    for m, p in pred.items():
        alerte = p > (base if m.startswith("Regles") else 0.5)   # regle : alerte si une regle s'active
        res.append({"Modele": m, "AUC": roc_auc_score(y, p), "Precision_alertes": precision_score(y, alerte, zero_division=0),
                    "Rappel": recall_score(y, alerte), "F1": f1_score(y, alerte), "Alertes": int(alerte.sum())})
    return pd.DataFrame(res)


# ---------------------------------------------------------------------------
# Ajout au graphe : regles, activations et preuves
# ---------------------------------------------------------------------------
def ajouter_au_graphe(chemin_graphe, sortie, ep, tx, regles, ex):
    from rdflib import Graph, Literal, Namespace, RDF, XSD
    LT = Namespace("https://example.org/learning-traces#")
    g = Graph()
    g.parse(chemin_graphe, format="turtle")
    avant = ex[ex["avant_alerte"]]
    n_act = 0
    for j, r in enumerate(regles):
        R = LT[f"regle_{j}"]
        g.add((R, RDF.type, LT.Regle))
        g.add((R, LT.condition, Literal(" ET ".join(r["si"]))))
        for p, v in (("confiance", r["confiance"]), ("support", r["support"]), ("lift", r["lift"])):
            g.add((R, LT[p], Literal(round(float(v), 3), datatype=XSD.decimal)))
    for i, (row, t) in enumerate(zip(ep.to_dict("records"), tx)):
        e = LT[f"ep_{row['SubjectID']}_{row['AssignmentID']}"]
        runs = avant[(avant["SubjectID"] == row["SubjectID"]) & (avant["AssignmentID"] == row["AssignmentID"])]
        for j, r in enumerate(regles):
            if not set(r["si"]) <= t:
                continue
            A = LT[f"alerte_{row['SubjectID']}_{row['AssignmentID']}_{j}"]
            g.add((A, RDF.type, LT.Activation))
            g.add((A, LT.regle, LT[f"regle_{j}"]))
            g.add((A, LT.surEpisode, e))
            preuves = set()
            for c in r["si"]:
                if c in ("3_erreurs_d_affilee", "2_types_d_erreur_ou_plus", "taux_d_echec>=30%"):
                    preuves |= set(runs.loc[runs["Resultat"] == "erreur", "EventID_debut"].astype(int))
                elif c == "moins_de_10_executions":
                    preuves |= set(runs["EventID_debut"].astype(int))
            for p in sorted(preuves):
                g.add((A, LT.justifiePar, LT[f"exec_{p}"]))
            if any(c in ("temps_actif<30min", "une_seule_session", "pas_commence_a_J-2", "code_non_compilable>=30%",
                         "5_collages_ou_plus") for c in r["si"]):
                for sess in g.objects(e, LT.aSession):               # sessions avant l'alerte
                    if (sess, LT.avantAlerte, Literal(True, datatype=XSD.boolean)) in g:
                        g.add((A, LT.justifiePar, sess))
                g.add((A, LT.justifiePar, LT[row["AssignmentID"]]))   # le devoir et son echeance
            n_act += 1
    g.serialize(sortie, format="turtle")
    return n_act, len(g)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resultats", default="resultats")
    ap.add_argument("--notions", default="notions.csv")
    ap.add_argument("--sans-graphe", action="store_true", help="ne pas ecrire les regles dans le graphe")
    a = ap.parse_args()

    ep = pd.read_csv(os.path.join(a.resultats, "episodes.csv"))
    notions = pd.read_csv(a.notions).set_index("AssignmentID")["Notion"]
    y = ep["difficulte"].astype(int).to_numpy()
    tx = transactions(ep, notions)
    X = ep[FEATURES].astype(float).fillna(-1)       # debut_h_avant absent = pas commence

    regles, base = miner(tx, y)
    regles_comp, _ = miner(tx, y, avec_notion=False)          # comportement seul, sans la notion
    perf = evaluer(X, tx, y, ep["SubjectID"])
    arbre = DecisionTreeClassifier(max_depth=3, min_samples_leaf=8, class_weight="balanced", random_state=0).fit(X, y)

    with open(os.path.join(a.resultats, "regles.md"), "w", encoding="utf-8") as f:
        f.write(f"# Regles extraites\n\n{len(ep)} episodes ; taux de difficulte (note < 70) : {base:.0%}.\n"
                "Indicateurs calcules 48 h avant l'echeance.\n\n")
        f.write("| # | Si | Episodes | Dont en difficulte | Confiance | Lift |\n| --- | --- | --- | --- | --- | --- |\n")
        for j, r in enumerate(regles):
            f.write(f"| {j} | {' ET '.join(r['si'])} | {r['n']} ({r['support']:.0%}) | {r['n_difficulte']} | "
                    f"{r['confiance']:.0%} | {r['lift']:.2f} |\n")
        f.write("\n## Regles sur le comportement seul (sans la notion du devoir)\n\n"
                "| # | Si | Episodes | Dont en difficulte | Confiance | Lift |\n| --- | --- | --- | --- | --- | --- |\n")
        for j, r in enumerate(regles_comp):
            f.write(f"| C{j} | {' ET '.join(r['si'])} | {r['n']} ({r['support']:.0%}) | {r['n_difficulte']} | "
                    f"{r['confiance']:.0%} | {r['lift']:.2f} |\n")
        f.write("\n## Comparaison (validation croisee en 5 plis, groupee par etudiant)\n\n")
        f.write(perf.to_markdown(index=False, floatfmt=".2f") + "\n")
        f.write("\n## Arbre de decision (profondeur 3, appris sur tout le jeu)\n\n```\n"
                + export_text(arbre, feature_names=FEATURES) + "```\n")
    perf.to_csv(os.path.join(a.resultats, "comparaison.csv"), index=False)

    print(f"{len(ep)} episodes, taux de difficulte {base:.0%}\n")
    for j, r in enumerate(regles):
        print(f"R{j}: SI {' ET '.join(r['si'])}\n    -> {r['n_difficulte']}/{r['n']} en difficulte "
              f"(confiance {r['confiance']:.0%}, lift {r['lift']:.2f})")
    print("\nComportement seul (sans la notion) :")
    for j, r in enumerate(regles_comp):
        print(f"C{j}: SI {' ET '.join(r['si'])} -> {r['n_difficulte']}/{r['n']} "
              f"(confiance {r['confiance']:.0%}, lift {r['lift']:.2f})")
    print("\n" + perf.round(2).to_string(index=False))

    if not a.sans_graphe:
        ex = pd.read_csv(os.path.join(a.resultats, "executions_detaillees.csv"))
        n_act, n_tr = ajouter_au_graphe(os.path.join(a.resultats, "graphe.ttl"),
                                        os.path.join(a.resultats, "graphe_avec_regles.ttl"), ep, tx, regles, ex)
        print(f"\n{len(regles)} regles et {n_act} activations ajoutees au graphe ({n_tr} triplets) "
              "-> resultats/graphe_avec_regles.ttl")


if __name__ == "__main__":
    main()
