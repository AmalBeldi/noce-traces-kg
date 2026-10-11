"""ETAPE 3 (suite) - Interroger le graphe avec SPARQL.

Chaque requete repond a une question qu'un enseignant pourrait se poser.
On les lance avec rdflib : pas besoin d'installer un triplestore.
(Le meme graphe.ttl peut aussi etre charge dans GraphDB ou Apache Jena Fuseki.)

Usage :
    python etape3_requetes.py --graphe resultats/graphe.ttl
"""
import argparse

from rdflib import Graph

PREFIXES = """
PREFIX lt:  <https://example.org/learning-traces#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""

REQUETES = {
    "Q1 - Par notion : episodes, part en difficulte, temps actif moyen avant l'alerte": """
SELECT ?notion (COUNT(?e) AS ?episodes)
       (ROUND(100 * AVG(IF(?diff, 1, 0))) AS ?pct_difficulte)
       (ROUND(AVG(?actif)) AS ?min_actives_avant_alerte)
WHERE {
  ?e a lt:Episode ; lt:porteSur ?d ; lt:enDifficulte ?diff ; lt:tempsActifMin ?actif .
  ?d lt:mobilise ?notion .
}
GROUP BY ?notion ORDER BY DESC(?pct_difficulte)
""",
    "Q2 - Avoir commence ou non 48 h avant l'echeance, et l'issue": """
SELECT ?commence ?diff (COUNT(?e) AS ?episodes)
WHERE { ?e a lt:Episode ; lt:commenceAvantAlerte ?commence ; lt:enDifficulte ?diff . }
GROUP BY ?commence ?diff ORDER BY ?commence ?diff
""",
    "Q3 - Les 3 types d'erreurs les plus frequents par notion": """
SELECT ?notion ?type (COUNT(?x) AS ?n)
WHERE {
  ?e a lt:Episode ; lt:porteSur ?d ; lt:aSession ?s .
  ?d lt:mobilise ?notion .
  ?s lt:aExecution ?x .
  ?x lt:aPourTypeErreur ?type .
}
GROUP BY ?notion ?type ORDER BY ?notion DESC(?n)
""",
    "Q4 - Justification : les executions d'un episode en difficulte, avant l'alerte": """
SELECT ?debut ?resultat ?type ?id
WHERE {
  BIND(lt:ep_EPISODE AS ?e)
  ?e lt:aSession ?s . ?s lt:aExecution ?x .
  ?x lt:debut ?debut ; lt:resultat ?resultat ; lt:idEvenement ?id ; lt:avantAlerte true .
  OPTIONAL { ?x lt:aPourTypeErreur ?type }
}
ORDER BY ?debut
""",
}

# Episode qui sert d'exemple pour Q4 : en difficulte, mais deja actif avant l'alerte
CHOIX_EXEMPLE = """
SELECT ?e ?n WHERE {
  ?e a lt:Episode ; lt:enDifficulte true ; lt:nbExecutions ?n .
  FILTER(?n >= 5)
} ORDER BY DESC(?n) LIMIT 1
"""


def court(v):
    s = str(v)
    return s.split("#")[-1] if "#" in s else s


def afficher(titre, resultats, maxi=24):
    print(f"\n=== {titre}")
    lignes = list(resultats)
    if not lignes:
        print("(aucun resultat)")
        return
    noms = [str(v) for v in resultats.vars]
    print(" | ".join(noms))
    for l in lignes[:maxi]:
        print(" | ".join(court(v) for v in l))
    if len(lignes) > maxi:
        print(f"... ({len(lignes)} lignes au total)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graphe", default="resultats/graphe.ttl")
    a = ap.parse_args()
    g = Graph()
    g.parse(a.graphe, format="turtle")
    print(f"{len(g)} triplets charges")

    exemple = list(g.query(PREFIXES + CHOIX_EXEMPLE))
    nom_exemple = court(exemple[0][0]).removeprefix("ep_") if exemple else "AUCUN"
    for titre, q in REQUETES.items():
        q = q.replace("EPISODE", nom_exemple)
        if titre.startswith("Q3"):                      # top 3 par notion
            res = g.query(PREFIXES + q)
            vus, garde = {}, []
            for l in res:
                vus[l[0]] = vus.get(l[0], 0) + 1
                if vus[l[0]] <= 3:
                    garde.append(l)
            res.bindings = [dict(zip(res.vars, l)) for l in garde]
            afficher(titre, res)
        else:
            afficher(titre + (f" ({nom_exemple})" if titre.startswith("Q4") else ""), g.query(PREFIXES + q))


if __name__ == "__main__":
    main()
