# Regles extraites

262 episodes ; taux de difficulte (note < 70) : 21%.
Indicateurs calcules 48 h avant l'echeance.

| # | Si | Episodes | Dont en difficulte | Confiance | Lift |
| --- | --- | --- | --- | --- | --- |
| 0 | moins_de_10_executions ET notion=listes_2D_recursivite | 16 (6%) | 11 | 69% | 3.22 |
| 1 | notion=listes_2D_recursivite ET temps_actif<30min | 16 (6%) | 11 | 69% | 3.22 |
| 2 | notion=listes_2D_recursivite | 23 (9%) | 14 | 61% | 2.85 |
| 3 | notion=boucles ET pas_commence_a_J-2 | 19 (7%) | 10 | 53% | 2.46 |
| 4 | moins_de_10_executions ET notion=boucles ET une_seule_session | 21 (8%) | 11 | 52% | 2.45 |
| 5 | moins_de_10_executions ET notion=boucles | 24 (9%) | 12 | 50% | 2.34 |
| 6 | notion=boucles ET une_seule_session | 23 (9%) | 11 | 48% | 2.24 |
| 7 | notion=recherche_tri ET pas_commence_a_J-2 | 14 (5%) | 6 | 43% | 2.01 |
| 8 | notion=recherche_tri ET une_seule_session | 18 (7%) | 7 | 39% | 1.82 |
| 9 | notion=recherche_tri ET temps_actif<30min | 17 (6%) | 6 | 35% | 1.65 |

## Regles sur le comportement seul (sans la notion du devoir)

| # | Si | Episodes | Dont en difficulte | Confiance | Lift |
| --- | --- | --- | --- | --- | --- |
| C0 | pas_commence_a_J-2 | 108 (41%) | 36 | 33% | 1.56 |
| C1 | temps_actif<30min ET une_seule_session | 136 (52%) | 44 | 32% | 1.51 |
| C2 | moins_de_10_executions ET une_seule_session | 134 (51%) | 42 | 31% | 1.47 |
| C3 | temps_actif<30min | 150 (57%) | 47 | 31% | 1.47 |
| C4 | une_seule_session | 147 (56%) | 46 | 31% | 1.46 |
| C5 | moins_de_10_executions | 160 (61%) | 47 | 29% | 1.37 |

## Comparaison (validation croisee en 5 plis, groupee par etudiant)

| Modele                                |   AUC |   Precision_alertes |   Rappel |   F1 |   Alertes |
|:--------------------------------------|------:|--------------------:|---------:|-----:|----------:|
| Regles (interpretable)                |  0.69 |                0.42 |     0.55 | 0.48 |        73 |
| Arbre profondeur 3 (interpretable)    |  0.68 |                0.31 |     0.88 | 0.46 |       157 |
| Regression logistique (interpretable) |  0.69 |                0.29 |     0.73 | 0.42 |       139 |
| Foret aleatoire (opaque)              |  0.71 |                0.32 |     0.73 | 0.44 |       130 |

## Arbre de decision (profondeur 3, appris sur tout le jeu)

```
|--- temps_actif_min <= 60.05
|   |--- n_executions <= 7.50
|   |   |--- part_non_compilable <= 0.25
|   |   |   |--- class: 1
|   |   |--- part_non_compilable >  0.25
|   |   |   |--- class: 0
|   |--- n_executions >  7.50
|   |   |--- n_sessions <= 3.50
|   |   |   |--- class: 1
|   |   |--- n_sessions >  3.50
|   |   |   |--- class: 1
|--- temps_actif_min >  60.05
|   |--- class: 0
```
