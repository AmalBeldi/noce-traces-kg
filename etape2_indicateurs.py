"""ETAPE 2 - Calculer des indicateurs interpretables par episode (etudiant x devoir).

Idee : se placer au moment ou l'enseignant pourrait agir (par defaut 48 h avant
l'echeance), ne regarder QUE ce qui s'est passe avant ce moment, et resumer
l'activite de chaque etudiant sur chaque devoir en quelques indicateurs lisibles.
La "difficulte" (note < 70 par defaut) n'est connue qu'apres : c'est ce qu'on
cherchera a anticiper a l'etape 4.

Entrees (dossier --donnees) :
  keystrokes.csv  - evenements ProgSnap2 (frappes, editions, executions...)
  executions.csv  - produit par l'etape 1 (type d'erreur de chaque execution)
  students.csv    - notes des devoirs
  due.csv         - echeances
Sorties (dossier --sortie) :
  episodes.csv    - une ligne par episode : indicateurs + note + difficulte
  executions_detaillees.csv - une ligne par execution, avec son resultat ;
                    servira de preuve (sous-graphe justificatif) aux etapes 3 et 5

Usage :
    python etape2_indicateurs.py --donnees donnees/keystroke2021 --sortie resultats
"""
import argparse
import os

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# PARAMETRES : ce sont des choix pedagogiques, a justifier au seminaire
# ---------------------------------------------------------------------------
SEUIL_NOTE = 70          # difficulte = note du devoir strictement inferieure
HEURES_AVANT = 48        # moment de l'alerte : 48 h avant l'echeance
PAUSE_SESSION_MIN = 30   # au-dela de 30 min sans evenement, nouvelle session
PAUSE_ACTIVE_MIN = 5     # un ecart < 5 min compte comme du temps de travail

# Codes de sortie d'une execution Python dans PyCharm
CODE_OK = {"0"}
CODE_ERREUR = {"1"}                                         # exception non rattrapee
CODE_INTERROMPU = {"130", "-1", "137", "-1073741510", "-805306369"}  # arret manuel, boucle infinie...


def resultat_execution(code):
    if code in CODE_OK:
        return "ok"
    if code in CODE_ERREUR:
        return "erreur"
    if code in CODE_INTERROMPU:
        return "interrompue"
    return "inconnu"


def plus_longue_serie(valeurs, cible):
    best = cur = 0
    for v in valeurs:
        cur = cur + 1 if v == cible else 0
        best = max(best, cur)
    return best


# ---------------------------------------------------------------------------
# 1. Chargement
# ---------------------------------------------------------------------------
def charger(dossier):
    k = pd.read_csv(os.path.join(dossier, "keystrokes.csv"), low_memory=False,
                    usecols=["EventID", "SubjectID", "AssignmentID", "CodeStateSection", "EventType",
                             "X-Metadata", "ClientTimestamp", "X-Compilable"])
    due = pd.read_csv(os.path.join(dossier, "due.csv")).set_index("AssignmentID")["Timestamp"]
    notes = pd.read_csv(os.path.join(dossier, "students.csv"), index_col=0)
    devoirs = list(due.index)
    notes = notes.melt(id_vars="SubjectID", value_vars=devoirs, var_name="AssignmentID", value_name="note")
    execs = pd.read_csv(os.path.join(dossier, "executions.csv")).dropna(subset=["Timestamp"])
    execs["Timestamp"] = execs["Timestamp"].astype("int64")
    return k, due, notes, execs


# ---------------------------------------------------------------------------
# 2. Une ligne par execution : debut (Start) + fin (code de sortie) + type d'erreur
# ---------------------------------------------------------------------------
def table_executions(k, execs):
    rp = k[k["EventType"] == "Run.Program"].sort_values(["SubjectID", "AssignmentID", "ClientTimestamp", "EventID"])
    lignes = []
    for (s, a), g in rp.groupby(["SubjectID", "AssignmentID"], sort=False):
        debut = None
        for ev in g.itertuples(index=False):
            if ev[5] == "Start":                      # colonne X-Metadata
                debut = ev
            elif debut is not None:                   # fin de l'execution ouverte
                lignes.append({"SubjectID": s, "AssignmentID": a, "Fichier": debut.CodeStateSection,
                               "EventID_debut": debut.EventID, "EventID_fin": ev.EventID,
                               "t_debut": debut.ClientTimestamp, "t_fin": ev.ClientTimestamp,
                               "CodeSortie": str(ev[5]), "Resultat": resultat_execution(str(ev[5]))})
                debut = None
    ex = pd.DataFrame(lignes).sort_values("t_debut")
    # type d'erreur (etape 1) : rapprochement par etudiant, devoir et heure de debut (tolerance 5 s)
    e = execs.sort_values("Timestamp")[["SubjectID", "AssignmentID", "Timestamp", "ErrorType"]]
    ex = pd.merge_asof(ex, e, left_on="t_debut", right_on="Timestamp", by=["SubjectID", "AssignmentID"],
                       direction="nearest", tolerance=5000).drop(columns="Timestamp")
    ex.loc[ex["Resultat"] != "erreur", "ErrorType"] = np.nan   # on ne garde le type que pour les erreurs
    return ex


# ---------------------------------------------------------------------------
# 3. Indicateurs d'un episode, calcules sur ce qui precede le moment de l'alerte
# ---------------------------------------------------------------------------
def indicateurs(evts, runs, echeance, coupure):
    f = {"commence": len(evts) > 0}
    if not f["commence"]:
        return {**f, "debut_h_avant": np.nan, "n_sessions": 0, "temps_actif_min": 0.0, "n_executions": 0,
                "taux_echec_exec": 0.0, "n_interrompues": 0, "serie_erreurs_max": 0, "n_types_erreur": 0,
                "part_non_compilable": 0.0, "n_collages": 0, "ratio_effacement": 0.0}
    t = evts["ClientTimestamp"].to_numpy()
    ecarts_min = np.diff(t) / 60000
    termines = runs[runs["Resultat"].isin(["ok", "erreur"])]
    edits = evts[evts["EventType"] == "File.Edit"]
    frappes = (evts["EventType"] == "X-Keystroke").sum()
    effacements = ((evts["EventType"] == "X-Action") & (evts["X-Metadata"] == "Backspace")).sum()
    return {
        **f,
        "debut_h_avant": round((echeance - t.min()) / 3.6e6, 1),
        "n_sessions": int(1 + (ecarts_min > PAUSE_SESSION_MIN).sum()),
        "temps_actif_min": round(float(ecarts_min[ecarts_min < PAUSE_ACTIVE_MIN].sum()), 1),
        "n_executions": int(len(runs)),
        "taux_echec_exec": round(float((termines["Resultat"] == "erreur").mean()), 3) if len(termines) else 0.0,
        "n_interrompues": int((runs["Resultat"] == "interrompue").sum()),
        "serie_erreurs_max": plus_longue_serie(runs["Resultat"].tolist(), "erreur"),
        "n_types_erreur": int(runs["ErrorType"].nunique()),
        "part_non_compilable": round(float((edits["X-Compilable"] == 0).mean()), 3) if len(edits) else 0.0,
        "n_collages": int((evts["EventType"] == "X-Paste").sum()),
        "ratio_effacement": round(float(effacements / frappes), 3) if frappes else 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--donnees", required=True)
    ap.add_argument("--sortie", default="resultats")
    ap.add_argument("--heures-avant", type=float, default=HEURES_AVANT)
    ap.add_argument("--seuil-note", type=float, default=SEUIL_NOTE)
    a = ap.parse_args()
    os.makedirs(a.sortie, exist_ok=True)

    k, due, notes, execs = charger(a.donnees)
    ex = table_executions(k, execs)
    ex["avant_alerte"] = ex["t_debut"] <= ex["AssignmentID"].map(due) - a.heures_avant * 3.6e6
    ex.to_csv(os.path.join(a.sortie, "executions_detaillees.csv"), index=False)

    # episodes = couples (etudiant, devoir) ayant au moins une trace ; les autres sont exclus
    lignes = []
    for (s, dv), g in k.groupby(["SubjectID", "AssignmentID"]):
        echeance = due[dv]
        coupure = echeance - a.heures_avant * 3.6e6
        evts = g[g["ClientTimestamp"] <= coupure].sort_values("ClientTimestamp")
        runs = ex[(ex["SubjectID"] == s) & (ex["AssignmentID"] == dv) & ex["avant_alerte"]]
        lignes.append({"SubjectID": s, "AssignmentID": dv, **indicateurs(evts, runs, echeance, coupure)})
    ep = pd.DataFrame(lignes).merge(notes, on=["SubjectID", "AssignmentID"], how="left")
    ep["difficulte"] = ep["note"] < a.seuil_note
    ep.to_csv(os.path.join(a.sortie, "episodes.csv"), index=False)

    sans_trace = len(notes) - len(ep)
    print(f"Executions : {len(ex)} ({ex['Resultat'].value_counts().to_dict()})")
    print(f"Episodes avec traces : {len(ep)} ; exclus faute de traces : {sans_trace} "
          f"(note moyenne de ces exclus : {notes.merge(ep[['SubjectID','AssignmentID']], how='left', indicator=True).query('_merge==\"left_only\"')['note'].mean():.1f})")
    print(f"Alerte {a.heures_avant:.0f} h avant l'echeance ; difficulte = note < {a.seuil_note:.0f} : "
          f"{ep['difficulte'].mean():.0%} des episodes")
    print(f"Pas encore commence au moment de l'alerte : {(~ep['commence']).mean():.0%} des episodes")
    print("\nIndicateurs moyens selon l'issue :")
    cols = ["commence", "debut_h_avant", "n_sessions", "temps_actif_min", "n_executions", "taux_echec_exec",
            "serie_erreurs_max", "n_types_erreur", "part_non_compilable", "n_collages", "ratio_effacement"]
    print(ep.groupby("difficulte")[cols].mean().round(2).T.rename(columns={False: "note>=seuil", True: "difficulte"}))


if __name__ == "__main__":
    main()
