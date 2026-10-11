"""ETAPE 1 - Resumer chaque execution (run) du jeu CS1 Keystroke 2021.

Probleme : runs1.csv et runs2.csv font 2,4 Go car ils contiennent TOUTE la sortie
de chaque execution (une ligne par ligne affichee).
Solution : on lit le fichier ligne a ligne, sans tout charger en memoire.
Une ligne Action = "r" ouvre une execution ; les lignes Action = "o" qui suivent
sont sa sortie. Pour chaque execution on garde :
  - l'etudiant, le devoir, le fichier, l'heure ;
  - le code de sortie ("Process finished with exit code N") ;
  - le type d'erreur Python s'il y en a une (NameError, SyntaxError...).

Sortie : un petit fichier executions.csv (une ligne par execution).

Usage :
    python etape1_resumer_executions.py runs1.csv runs2.csv --sortie executions.csv
    (on peut aussi lire directement dans le zip : --zip dataverse_files.zip)
"""
import argparse
import csv
import io
import re
import sys
import zipfile

csv.field_size_limit(sys.maxsize)
RE_EXIT = re.compile(r"exit code (-?\d+)")
# derniere ligne d'une trace Python : "NomErreur: message" ou "NomErreur"
RE_ERREUR = re.compile(r"^([A-Z][A-Za-z]*(?:Error|Exception|Interrupt|Exit))\b")


def lignes(source, zip_path=None):
    if zip_path:
        with zipfile.ZipFile(zip_path) as z, z.open(source) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline=""))
    else:
        with open(source, encoding="utf-8", errors="replace", newline="") as f:
            yield from csv.DictReader(f)


def resumer(sources, zip_path, sortie):
    champs = ["SubjectID", "AssignmentID", "File", "Timestamp", "ExitCode", "ErrorType", "NumOutputLines"]
    n = 0
    with open(sortie, "w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=champs)
        w.writeheader()
        courante = None
        for src in sources:
            for row in lignes(src, zip_path):
                if row["Action"] == "r":                     # debut d'une nouvelle execution
                    if courante:
                        w.writerow(courante); n += 1
                    courante = {"SubjectID": row["SubjectID"], "AssignmentID": row["AssignmentID"],
                                "File": row["File"], "Timestamp": row["ClientTimestamp"],
                                "ExitCode": "", "ErrorType": "", "NumOutputLines": row["NumOutputLines"]}
                elif row["Action"] == "o" and courante:      # sortie de l'execution courante
                    texte = row["Output"] or ""
                    if row["OutputDestination"] == "system":
                        m = RE_EXIT.search(texte)
                        if m:
                            courante["ExitCode"] = m.group(1)
                    elif row["OutputDestination"] == "stderr":
                        for l in texte.strip().splitlines():
                            m = RE_ERREUR.match(l.strip())
                            if m:
                                courante["ErrorType"] = m.group(1)   # on garde la derniere
            if courante:
                w.writerow(courante); n += 1
                courante = None
    print(f"{n} executions resumees dans {sortie}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="+", help="runs1.csv runs2.csv (chemins ou noms dans le zip)")
    ap.add_argument("--zip", help="lire directement dans l'archive dataverse_files.zip")
    ap.add_argument("--sortie", default="executions.csv")
    a = ap.parse_args()
    resumer(a.sources, a.zip, a.sortie)
