"""ETAPE 3 - Construire le graphe de connaissances des traces.

On transforme les tableaux des etapes 1 et 2 en un graphe RDF conforme a
l'ontologie v0.3 (ontologie_v03.ttl) :

  Apprenant <-concerne- Episode -porteSur-> Devoir -mobilise-> Notion
                           |
                        aSession
                           v
                        Session -aExecution-> Execution -aPourTypeErreur-> TypeErreur
                                                  |  suivante
                                                  v
                                              Execution ...

Pourquoi un graphe plutot qu'un tableau ? Chaque alerte pourra pointer vers les
sessions et executions precises qui la justifient, et on pourra ajouter des
notions, un referentiel de competences ou d'autres jeux de donnees sans changer
la structure.

Entrees : keystrokes.csv, due.csv (dossier --donnees) ; episodes.csv et
          executions_detaillees.csv (dossier --resultats, produits par l'etape 2) ;
          notions.csv.
Sortie  : graphe.ttl (le graphe, au format Turtle).

Usage :
    pip install rdflib
    python etape3_graphe.py --donnees donnees/keystroke2021 --resultats resultats --notions notions.csv
"""
import argparse
import os
from datetime import datetime, timezone

import pandas as pd
from rdflib import Graph, Literal, Namespace, RDF, XSD

LT = Namespace("https://example.org/learning-traces#")
PAUSE_SESSION_MIN = 30   # meme valeur qu'a l'etape 2
PAUSE_ACTIVE_MIN = 5


def date(ms):
    """Horodatage Java (ms depuis 1970, UTC) -> xsd:dateTime."""
    return Literal(datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   datatype=XSD.dateTime)


def sessions_episode(t_ms):
    """Decoupe une suite d'horodatages (tries) en sessions ; renvoie (debut, fin, n, minutes actives)."""
    res, debut, prec, n, actif = [], t_ms[0], t_ms[0], 0, 0.0
    for t in t_ms:
        ecart = (t - prec) / 60000
        if ecart > PAUSE_SESSION_MIN:
            res.append((debut, prec, n, round(actif, 1)))
            debut, n, actif = t, 0, 0.0
        elif ecart < PAUSE_ACTIVE_MIN:
            actif += ecart
        n += 1
        prec = t
    res.append((debut, prec, n, round(actif, 1)))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--donnees", required=True)
    ap.add_argument("--resultats", default="resultats")
    ap.add_argument("--notions", default="notions.csv")
    ap.add_argument("--heures-avant", type=float, default=48)
    a = ap.parse_args()

    ep = pd.read_csv(os.path.join(a.resultats, "episodes.csv"))
    ex = pd.read_csv(os.path.join(a.resultats, "executions_detaillees.csv"))
    due = pd.read_csv(os.path.join(a.donnees, "due.csv")).set_index("AssignmentID")["Timestamp"]
    notions = pd.read_csv(a.notions).set_index("AssignmentID")["Notion"]
    k = pd.read_csv(os.path.join(a.donnees, "keystrokes.csv"), usecols=["SubjectID", "AssignmentID", "ClientTimestamp"])

    g = Graph()
    g.bind("lt", LT)

    # --- 1. Contexte : devoirs, notions, apprenants ---------------------------
    for dv, ms in due.items():
        g.add((LT[dv], RDF.type, LT.Devoir))
        g.add((LT[dv], LT.echeance, date(ms)))
        g.add((LT[dv], LT.mobilise, LT["notion_" + notions[dv]]))
        g.add((LT["notion_" + notions[dv]], RDF.type, LT.Notion))
    for s in ep["SubjectID"].unique():
        g.add((LT[s], RDF.type, LT.Apprenant))

    # --- 2. Episodes et leurs indicateurs (etape 2) ---------------------------
    props = {"commence": (LT.commenceAvantAlerte, XSD.boolean), "debut_h_avant": (LT.debutHeuresAvant, XSD.decimal),
             "n_sessions": (LT.nbSessions, XSD.integer), "temps_actif_min": (LT.tempsActifMin, XSD.decimal),
             "n_executions": (LT.nbExecutions, XSD.integer), "taux_echec_exec": (LT.tauxEchecExec, XSD.decimal),
             "serie_erreurs_max": (LT.serieErreursMax, XSD.integer), "n_types_erreur": (LT.nbTypesErreur, XSD.integer),
             "part_non_compilable": (LT.partNonCompilable, XSD.decimal), "n_collages": (LT.nbCollages, XSD.integer),
             "ratio_effacement": (LT.ratioEffacement, XSD.decimal), "note": (LT.note, XSD.decimal),
             "difficulte": (LT.enDifficulte, XSD.boolean)}
    for r in ep.itertuples(index=False):
        e = LT[f"ep_{r.SubjectID}_{r.AssignmentID}"]
        g.add((e, RDF.type, LT.Episode))
        g.add((e, LT.concerne, LT[r.SubjectID]))
        g.add((e, LT.porteSur, LT[r.AssignmentID]))
        for col, (p, typ) in props.items():
            v = getattr(r, col)
            if pd.notna(v):
                v = bool(v) if typ == XSD.boolean else int(v) if typ == XSD.integer else float(v)
                g.add((e, p, Literal(v, datatype=typ)))

    # --- 3. Sessions (a partir des frappes) -----------------------------------
    bornes = {}   # episode -> liste de (session, debut, fin)
    for (s, dv), grp in k.groupby(["SubjectID", "AssignmentID"]):
        e = LT[f"ep_{s}_{dv}"]
        coupure = due[dv] - a.heures_avant * 3.6e6
        bornes[(s, dv)] = []
        for i, (d, f, n, actif) in enumerate(sessions_episode(sorted(grp["ClientTimestamp"].tolist()))):
            sess = LT[f"sess_{s}_{dv}_{i}"]
            g.add((sess, RDF.type, LT.Session))
            g.add((e, LT.aSession, sess))
            g.add((sess, LT.debut, date(d)))
            g.add((sess, LT.fin, date(f)))
            g.add((sess, LT.nbEvenements, Literal(n, datatype=XSD.integer)))
            g.add((sess, LT.dureeActiveMin, Literal(actif, datatype=XSD.decimal)))
            g.add((sess, LT.avantAlerte, Literal(bool(d <= coupure), datatype=XSD.boolean)))
            bornes[(s, dv)].append((sess, d, f))

    # --- 4. Executions, erreurs et ordre temporel -----------------------------
    for (s, dv), grp in ex.sort_values("t_debut").groupby(["SubjectID", "AssignmentID"]):
        prec = None
        for r in grp.itertuples(index=False):
            x = LT[f"exec_{int(r.EventID_debut)}"]
            g.add((x, RDF.type, LT.Execution))
            g.add((x, LT.idEvenement, Literal(int(r.EventID_debut), datatype=XSD.integer)))
            g.add((x, LT.debut, date(r.t_debut)))
            g.add((x, LT.fichier, Literal(str(r.Fichier))))
            g.add((x, LT.codeSortie, Literal(str(r.CodeSortie))))
            g.add((x, LT.resultat, Literal(r.Resultat)))
            g.add((x, LT.avantAlerte, Literal(bool(r.avant_alerte), datatype=XSD.boolean)))
            if pd.notna(r.ErrorType):
                g.add((x, LT.aPourTypeErreur, LT["err_" + r.ErrorType]))
                g.add((LT["err_" + r.ErrorType], RDF.type, LT.TypeErreur))
            for sess, d, f in bornes.get((s, dv), []):        # rattacher a la session qui la contient
                if d <= r.t_debut <= f:
                    g.add((sess, LT.aExecution, x))
                    break
            if prec is not None:
                g.add((prec, LT.suivante, x))
            prec = x

    sortie = os.path.join(a.resultats, "graphe.ttl")
    g.serialize(sortie, format="turtle")
    compte = lambda c: len(set(g.subjects(RDF.type, c)))
    print(f"Graphe ecrit dans {sortie} : {len(g)} triplets")
    for c in ["Apprenant", "Devoir", "Notion", "Episode", "Session", "Execution", "TypeErreur"]:
        print(f"  {c:<11} {compte(LT[c])}")


if __name__ == "__main__":
    main()
