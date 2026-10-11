"""ETAPE 5 - Produire des explications "Alerte / Pourquoi / Preuves / Action" a partir du graphe.

Tout vient du graphe (graphe_avec_regles.ttl), par des requetes SPARQL :
  - l'alerte : la regle la plus forte activee sur l'episode (lt:Activation) ;
  - le pourquoi : les conditions de la regle, illustrees par les valeurs des
    indicateurs de l'episode ;
  - les preuves : les sessions et executions reliees par lt:justifiePar,
    avec leurs dates, resultats, types d'erreur et identifiants d'origine ;
  - l'action : une suggestion pedagogique associee a chaque condition.
L'issue reelle (note) n'est affichee qu'a part, pour evaluer l'alerte apres coup.

Sorties (dossier --resultats) :
  explications.md   - exemples lisibles (vrais positifs ET faux positifs, par honnetete)
  explications.csv  - une ligne par episode alerte
  sous_graphe_<episode>.dot/.svg/.png - figure du sous-graphe justificatif d'un episode
  (la figure demande Graphviz : https://graphviz.org ; sinon coller le .dot dans un
   visualiseur en ligne comme https://dreampuf.github.io/GraphvizOnline)

Usage :
    python etape5_explications.py --resultats resultats
"""
import argparse
import os
import shutil
import subprocess

import pandas as pd
from rdflib import Graph

from etape4_regles import ACTIONS

P = """PREFIX lt: <https://example.org/learning-traces#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""

Q_ALERTES = P + """
SELECT ?e ?app ?dev ?notion ?ech ?cond ?conf ?lift ?note ?diff
       ?actif ?nexec ?nsess ?commence ?taux ?ntypes
WHERE {
  ?a a lt:Activation ; lt:surEpisode ?e ; lt:regle ?r .
  ?r lt:condition ?cond ; lt:confiance ?conf ; lt:lift ?lift .
  ?e lt:concerne ?app ; lt:porteSur ?dev ; lt:note ?note ; lt:enDifficulte ?diff ;
     lt:tempsActifMin ?actif ; lt:nbExecutions ?nexec ; lt:nbSessions ?nsess ;
     lt:commenceAvantAlerte ?commence ; lt:tauxEchecExec ?taux ; lt:nbTypesErreur ?ntypes .
  ?dev lt:mobilise ?notion ; lt:echeance ?ech .
}
"""

Q_PREUVES_SESSIONS = P + """
SELECT ?s ?debut ?fin ?duree WHERE {
  ?a lt:surEpisode <%s> ; lt:justifiePar ?s .
  ?s a lt:Session ; lt:debut ?debut ; lt:fin ?fin ; lt:dureeActiveMin ?duree .
} ORDER BY ?debut
"""

Q_PREUVES_EXEC = P + """
SELECT DISTINCT ?x ?debut ?res ?type ?id WHERE {
  <%s> lt:aSession ?s . ?s lt:aExecution ?x .
  ?x lt:debut ?debut ; lt:resultat ?res ; lt:idEvenement ?id ; lt:avantAlerte true .
  OPTIONAL { ?x lt:aPourTypeErreur ?type }
} ORDER BY ?debut
"""


def court(u):
    return str(u).split("#")[-1]


def natif(v):
    """Valeur RDF -> valeur Python (bool, int, float, date) ; une URI garde son nom court."""
    from rdflib import Literal
    if v is None:
        return None
    if isinstance(v, Literal):
        x = v.toPython()
        return float(x) if type(x).__name__ == "Decimal" else x
    return v


def phrase_condition(c, r):
    """Traduit une condition en phrase, avec la valeur observee dans le graphe."""
    if c.startswith("notion="):
        return f"le devoir porte sur une notion ou les difficultes sont frequentes ({c[7:]})"
    textes = {
        "pas_commence_a_J-2": "aucun travail enregistre 48 h avant l'echeance",
        "temps_actif<30min": f"seulement {float(r['actif']):.1f} min de travail actif avant l'alerte",
        "moins_de_10_executions": (f"seulement {int(r['nexec'])} execution(s) du programme" if int(r["nexec"])
                                   else "aucune execution du programme"),
        "une_seule_session": f"{int(r['nsess'])} session de travail au plus",
        "3_erreurs_d_affilee": "au moins 3 executions en erreur d'affilee",
        "2_types_d_erreur_ou_plus": f"{int(r['ntypes'])} types d'erreurs differents",
        "taux_d_echec>=30%": f"{float(r['taux']):.0%} des executions en erreur",
        "code_non_compilable>=30%": "le code est souvent dans un etat non compilable",
        "5_collages_ou_plus": "au moins 5 collages de code",
    }
    return textes.get(c, c)


def explication(r, sessions, execs):
    conds = r["cond"].split(" ET ")
    l = [f"### {r['app']} - {r['dev']} (notion : {r['notion']})", "",
         f"**Alerte, 48 h avant l'echeance** : risque de note inferieure a 70. "
         f"Dans les donnees, {float(r['conf']):.0%} des episodes verifiant cette regle etaient en difficulte "
         f"(taux moyen : 21 %, lift {float(r['lift']):.1f}).", "",
         "**Pourquoi** :"]
    l += [f"- {phrase_condition(c, r)} ;" for c in conds]
    l += ["", "**Preuves dans le graphe** :"]
    if sessions:
        l.append(f"- {len(sessions)} session(s) avant l'alerte : " +
                 ", ".join(f"{d:%d/%m %H:%M} ({float(m):.0f} min actives)" for _, d, _, m in sessions))
    else:
        l.append("- aucune session avant l'alerte (absence d'activite) ;")
    if execs:
        err = [e for e in execs if str(e[2]) == "erreur"]
        types = sorted({court(e[3]).removeprefix("err_") for e in err if e[3] is not None})
        l.append(f"- {len(execs)} execution(s), dont {len(err)} en erreur"
                 + (f" ({', '.join(types)})" if types else "")
                 + f" ; evenements d'origine {', '.join(str(e[4]) for e in execs[:6])}"
                 + (" ..." if len(execs) > 6 else "") + " ;")
    l += ["", "**Action proposee** : " + " ; puis ".join(ACTIONS[c] for c in conds if c in ACTIONS) + ".", "",
          f"*Evaluation apres coup* : note obtenue {float(r['note']):.0f} -> "
          + ("alerte justifiee." if r["diff"] else "fausse alerte (l'etudiant a reussi)."), ""]
    return "\n".join(l)


def figure(g, ep_uri, r, sessions, execs, dossier):
    """Ecrit le sous-graphe justificatif d'un episode au format Graphviz (DOT), puis SVG/PNG."""
    nom = court(ep_uri)
    L = ['digraph G {', 'rankdir=LR; node [fontname="Helvetica", fontsize=11, style="filled,rounded", shape=box];',
         'edge [fontname="Helvetica", fontsize=9, color="#555555"];']
    noeud = lambda i, txt, coul: L.append(f'"{i}" [label="{txt}", fillcolor="{coul}"];')
    arc = lambda a, b, lab="": L.append(f'"{a}" -> "{b}" [label="{lab}"];')
    noeud("app", f"Apprenant\\n{r['app']}", "#dbeafe")
    noeud("dev", f"Devoir {r['dev']}\\néchéance {r['ech']:%d/%m/%Y}", "#dbeafe")
    noeud("notion", f"Notion\\n{r['notion']}", "#dbeafe")
    noeud("ep", f"Episode\\n{float(r['actif']):.1f} min actives, {int(r['nexec'])} exéc.\\nnote {float(r['note']):.0f}", "#e5e7eb")
    noeud("regle", f"Règle\\n{r['cond'].replace(' ET ', '\\nET ')}\\nconfiance {float(r['conf']):.0%}", "#fde68a")
    noeud("alerte", "Alerte (activation)\\n48 h avant l'échéance", "#fca5a5")
    arc("ep", "app", "concerne"); arc("ep", "dev", "porteSur"); arc("dev", "notion", "mobilise")
    arc("alerte", "regle", "regle"); arc("alerte", "ep", "surEpisode"); arc("alerte", "dev", "justifiePar")
    for i, (s, d, f, m) in enumerate(sessions):
        noeud(f"s{i}", f"Session {i + 1}\\n{d:%d/%m %H:%M}\\n{float(m):.1f} min", "#d1fae5")
        arc("ep", f"s{i}", "aSession"); arc("alerte", f"s{i}", "justifiePar")
    prec, MAXI = None, 6
    L.append("subgraph execs { rank=same; " + " ".join(f'"x{j}";' for j in range(min(len(execs), MAXI)))
             + (' "plus";' if len(execs) > MAXI else "") + " }")
    for j, (x, d, res, typ, i_d) in enumerate(execs[:MAXI]):
        coul = {"ok": "#bbf7d0", "erreur": "#fecaca", "interrompue": "#fde68a"}.get(str(res), "#e5e7eb")
        noeud(f"x{j}", f"Exécution n°{i_d}\\n{d:%d/%m %H:%M} : {res}", coul)
        if sessions and j == 0:
            arc("s0", "x0", "aExecution")
        if typ is not None:
            noeud(court(typ), court(typ).removeprefix("err_"), "#fecaca")
            arc(f"x{j}", court(typ), "aPourTypeErreur")
        if prec:
            arc(prec, f"x{j}", "suivante")
        prec = f"x{j}"
    if len(execs) > MAXI:
        noeud("plus", f"... {len(execs) - MAXI} autres exécutions", "#f3f4f6")
        arc(prec, "plus", "suivante")
    L.append("}")
    base = os.path.join(dossier, f"sous_graphe_{nom}")
    with open(base + ".dot", "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    if shutil.which("dot"):
        for fmt in ("svg", "png"):
            subprocess.run(["dot", f"-T{fmt}", "-Gdpi=160", base + ".dot", "-o", f"{base}.{fmt}"], check=True)
        return base + ".png"
    return base + ".dot"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resultats", default="resultats")
    ap.add_argument("--exemples", type=int, default=4, help="nombre d'explications detaillees dans le .md")
    a = ap.parse_args()

    g = Graph()
    g.parse(os.path.join(a.resultats, "graphe_avec_regles.ttl"), format="turtle")
    res = g.query(Q_ALERTES)
    df = pd.DataFrame([{k: (court(v) if k in ("app", "dev", "notion") else natif(v))
                        for k, v in zip(map(str, res.vars), row)} for row in res])
    df["notion"] = df["notion"].str.removeprefix("notion_")
    # la regle la plus forte par episode
    top = df.sort_values("conf", ascending=False).drop_duplicates("e").reset_index(drop=True)

    def preuves(e):
        sess = [tuple(natif(v) for v in x) for x in g.query(Q_PREUVES_SESSIONS % e)]
        ex = [tuple(natif(v) for v in x) for x in g.query(Q_PREUVES_EXEC % e)]
        return sess, ex

    # exemples : les alertes justifiees les plus fortes, avec de l'activite, + une fausse alerte
    vrais = top[top["diff"] & (top["nexec"] > 0)].sort_values(["conf", "nexec"], ascending=False).head(a.exemples - 1)
    faux = top[~top["diff"]].head(1)
    blocs = [explication(r, *preuves(r["e"])) for _, r in pd.concat([vrais, faux]).iterrows()]
    n_ok = int(top["diff"].sum())
    with open(os.path.join(a.resultats, "explications.md"), "w", encoding="utf-8") as f:
        f.write(f"# Explications generees depuis le graphe\n\n{len(top)} episodes alertes, dont {n_ok} "
                f"reellement en difficulte ({n_ok / len(top):.0%}).\n\n" + "\n".join(blocs))
    top.drop(columns="e").to_csv(os.path.join(a.resultats, "explications.csv"), index=False)

    exemple = vrais.iloc[0]
    img = figure(g, exemple["e"], exemple, *preuves(exemple["e"]), a.resultats)
    print(f"{len(top)} episodes alertes ({n_ok} justifies) -> {a.resultats}/explications.md")
    print(f"Figure du sous-graphe justificatif : {img}\n")
    print(blocs[0])


if __name__ == "__main__":
    main()
