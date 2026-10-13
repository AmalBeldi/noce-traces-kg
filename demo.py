"""DEMO - Interroger le graphe en direct et expliquer une alerte.

Une seule commande, pour le seminaire :
    python demo.py
    python demo.py --pas-a-pas            (Entree entre chaque etape)
    python demo.py --apprenant Student12 --devoir Assign9
    python demo.py --lister               (toutes les alertes du graphe)

Le script charge resultats/graphe_avec_regles.ttl (produit par les etapes 1 a 4),
puis tout ce qu'il affiche vient de requetes SPARQL sur ce graphe :
  1. la requete elle-meme ;
  2. l'alerte et la regle qui l'a declenchee ;
  3. le pourquoi : les conditions, avec les valeurs observees ;
  4. les preuves : sessions et executions avant l'alerte, avec leurs identifiants d'origine ;
  5. l'action proposee, puis, a part, la note reelle pour evaluer l'alerte.
"""
import argparse
import os
import sys
import time

from rdflib import Graph

from etape4_regles import ACTIONS
from etape5_explications import (P, Q_ALERTES, Q_PREUVES_EXEC, Q_PREUVES_SESSIONS,
                                 court, natif, phrase_condition)

# accents et symboles corrects dans le terminal Windows
for flux in (sys.stdout, sys.stderr):
    try:
        flux.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
if os.name == "nt":
    os.system("")  # active les couleurs ANSI dans les consoles Windows

C = {"titre": "\033[1;34m", "or": "\033[1;33m", "rouge": "\033[1;31m", "vert": "\033[32m",
     "gris": "\033[90m", "gras": "\033[1m", "fin": "\033[0m"}

Q_AFFICHEE = """PREFIX lt: <https://example.org/learning-traces#>
SELECT ?regle ?confiance ?preuve WHERE {
  ?alerte a lt:Activation ;
          lt:surEpisode  lt:ep_%s_%s ;
          lt:regle       ?regle ;
          lt:justifiePar ?preuve .
  ?regle  lt:confiance   ?confiance .
}"""


def coul(txt, c):
    return f"{C[c]}{txt}{C['fin']}"


def etape(n, titre, pas_a_pas):
    if pas_a_pas:
        input(coul("\n   [Entree pour continuer]", "gris"))
    print("\n" + coul(f"{n}. {titre}", "titre"))
    print(coul("-" * 60, "gris"))


def main():
    ap = argparse.ArgumentParser(description="Demo : expliquer une alerte depuis le graphe")
    ap.add_argument("--graphe", default=os.path.join("resultats", "graphe_avec_regles.ttl"))
    ap.add_argument("--apprenant", default="Student7")
    ap.add_argument("--devoir", default="Assign13")
    ap.add_argument("--lister", action="store_true", help="lister toutes les alertes et s'arreter")
    ap.add_argument("--pas-a-pas", action="store_true", help="attendre Entree entre les etapes")
    a = ap.parse_args()

    if not os.path.exists(a.graphe):
        sys.exit(f"Graphe introuvable : {a.graphe}\n"
                 "Lancez d'abord les etapes 1 a 4 (voir README), ou indiquez --graphe <fichier>.")

    print(coul("Des traces aux explications : demonstration", "gras"))
    t0 = time.time()
    g = Graph()
    g.parse(a.graphe, format="turtle")
    print(coul(f"Graphe charge : {len(g):,} triplets en {time.time() - t0:.1f} s".replace(",", " "), "gris"))

    lignes = []
    for row in g.query(Q_ALERTES):
        r = {k: natif(v) for k, v in zip(map(str, row.labels), row)}
        r["app"], r["dev"] = court(r["app"]), court(r["dev"])
        r["notion"] = court(r["notion"]).removeprefix("notion_")
        lignes.append(r)
    # la regle la plus forte par episode
    top = {}
    for r in sorted(lignes, key=lambda r: -float(r["conf"])):
        top.setdefault(str(r["e"]), r)

    if a.lister:
        n_ok = sum(bool(r["diff"]) for r in top.values())
        print(f"\n{len(top)} episodes alertes, dont {n_ok} reellement en difficulte.\n")
        for r in sorted(top.values(), key=lambda r: (r["app"], r["dev"])):
            verdict = coul("justifiee", "vert") if r["diff"] else coul("fausse alerte", "rouge")
            print(f"  {r['app']:<10} {r['dev']:<9} confiance {float(r['conf']):.0%}  note {float(r['note']):>3.0f}  {verdict}")
        return

    cible = [r for r in top.values() if r["app"] == a.apprenant and r["dev"] == a.devoir]
    if not cible:
        sys.exit(f"Aucune alerte pour {a.apprenant} sur {a.devoir}. Essayez : python demo.py --lister")
    r = cible[0]
    e = r["e"]

    etape(1, "La question posee au graphe (SPARQL)", a.pas_a_pas)
    print(coul(Q_AFFICHEE % (a.apprenant, a.devoir), "gris"))
    t1 = time.time()
    rep = list(g.query(P + Q_AFFICHEE.split("\n", 1)[1] % (a.apprenant, a.devoir)))
    print(coul(f"-> {len(rep)} reponses en {time.time() - t1:.2f} s", "gris"))

    etape(2, "L'alerte", a.pas_a_pas)
    print(f"{coul(r['app'], 'gras')}, devoir {coul(r['dev'], 'gras')} (notion : {r['notion']}), "
          f"echeance {r['ech']:%d/%m/%Y %H:%M}")
    print(coul("Alerte 48 h avant l'echeance : risque de note inferieure a 70.", "rouge"))
    print(f"Regle : {coul(r['cond'], 'or')}")
    print(f"Dans les donnees, {float(r['conf']):.0%} des episodes qui verifient cette regle etaient "
          f"en difficulte (taux moyen 21 %, lift {float(r['lift']):.1f}).")

    etape(3, "Pourquoi", a.pas_a_pas)
    conds = r["cond"].split(" ET ")
    for c in conds:
        print(f"  - {phrase_condition(c, r)}")

    etape(4, "Les preuves, reliees a l'alerte dans le graphe", a.pas_a_pas)
    sessions = [tuple(natif(v) for v in x) for x in g.query(Q_PREUVES_SESSIONS % e)]
    execs = [tuple(natif(v) for v in x) for x in g.query(Q_PREUVES_EXEC % e)]
    if sessions:
        for i, (_, d, f, m) in enumerate(sessions, 1):
            print(f"  Session {i} : {d:%d/%m %H:%M} -> {f:%H:%M}, {float(m):.1f} min actives")
    else:
        print("  Aucune session avant l'alerte (absence d'activite).")
    MAXI = 10
    for _, d, res, typ, i_d in execs[:MAXI]:
        etat = {"ok": coul("ok", "vert"), "erreur": coul("erreur", "rouge")}.get(str(res), str(res))
        detail = f" ({court(typ).removeprefix('err_')})" if typ is not None else ""
        print(f"    execution n°{i_d:<8} {d:%d/%m %H:%M}  {etat}{detail}")
    if len(execs) > MAXI:
        print(coul(f"    ... {len(execs) - MAXI} autres executions", "gris"))
    if execs:
        n_err = sum(str(x[2]) == "erreur" for x in execs)
        print(coul(f"  {len(execs)} executions, dont {n_err} en erreur. Chaque numero renvoie "
                   "a l'evenement d'origine dans les traces ProgSnap2.", "gris"))

    etape(5, "Action proposee a l'enseignant·e", a.pas_a_pas)
    for c in conds:
        if c in ACTIONS:
            print(f"  - {ACTIONS[c]}")
    print(coul("  L'enseignant·e decide ; la regle et ses preuves peuvent etre contestees.", "gris"))

    if a.pas_a_pas:
        input(coul("\n   [Entree pour l'evaluation apres coup]", "gris"))
    print("\n" + coul("Evaluation apres coup (jamais utilisee par la regle)", "gris"))
    verdict = "alerte justifiee." if r["diff"] else "fausse alerte : l'etudiant a reussi."
    print(f"  Note obtenue : {float(r['note']):.0f} -> {verdict}")


if __name__ == "__main__":
    main()
