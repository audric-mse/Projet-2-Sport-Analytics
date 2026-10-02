# Sport Analytics - Ligue 1 2015/2016

Projet de portfolio (BUT Sciences des Données) : construire une base de données
propre à partir de données de football réelles, puis l'analyser.

**État du projet : étapes 1 à 3 terminées** (cadrage, modèle SQL, ETL).
Les analyses SQL, les statistiques, l'API et le tableau de bord viennent ensuite.

## Question de départ

> Les écarts de production offensive entre joueurs (buts, tirs, xG par 90 minutes)
> sont-ils réels, ou dus au hasard lié au temps de jeu ?

## Données

- **Source** : [StatsBomb Open Data](https://github.com/statsbomb/open-data)
- **Contenu utilisé** : Ligue 1, saison 2015/2016 : 377 matchs, avec composition des équipes
  et tous les événements (passes, tirs, etc.)
- **Attribution** : données fournies par StatsBomb. Si je publie une analyse, je dois citer
  StatsBomb comme source et utiliser leur logo (condition indiquée dans leur dépôt).
- **À faire** : lire en entier le *StatsBomb Public Data User Agreement* avant toute publication.

## Architecture

```
GitHub StatsBomb (JSON)  ->  etl/download.py  ->  data/raw/
data/raw/  ->  etl/etl.py (lecture, validation, nettoyage, chargement)  ->  SQLite
                         |-> reports/rapport_qualite.md
                         |-> reports/lignes_rejetees.csv
```

## Modèle de données (SQLite)

| Table | Contenu |
|---|---|
| `competition`, `season` | la compétition et la saison |
| `team`, `player` | 20 équipes, 649 joueurs |
| `match` | 377 matchs (date, équipes, score) |
| `lineup` | qui a joué quel match et combien de minutes (10 479 lignes) |
| `event` | une ligne par action dans un match (1 358 593 lignes) |
| `player_match` | table calculée : tirs, buts, xG, passes, passes décisives par joueur et par match |

Le schéma complet (clés, contraintes `CHECK`, index) est dans `sql/schema.sql`.
Les règles de qualité sont dans `docs/data_contract.md`.

## Utilisation

```bash
pip install -r requirements.txt
python etl/download.py        # télécharge les données brutes (1,1 Go, quelques minutes)
python etl/etl.py             # construit data/sportanalytics.db (environ 35 secondes)
python -m pytest tests/ -v    # lance les 45 tests
```

L'ETL supprime et recrée la base à chaque exécution : le relancer redonne toujours le même résultat.

## Résultats de l'import

(Détails dans `reports/rapport_qualite.md`)

- 377 matchs, 10 479 lignes de composition, 1 358 593 événements chargés.
- **3 matchs absents** des données (sur 380 attendus) : Troyes-Bordeaux,
  Saint-Étienne-Paris Saint-Germain et Bastia-Gazélec Ajaccio.
- Pour les 377 matchs présents, le score officiel correspond au nombre de buts trouvés dans les événements.
- 2 positions légèrement hors du terrain (120,4 et 120,5 sur 120) : gardées, ramenées à la limite.
- Contrôle externe : 949 buts dans les 377 matchs, plus 11 dans les 3 matchs absents,
  donnent les 960 buts de la saison indiqués sur Wikipedia.

## Limites connues

- Les 3 matchs absents faussent un peu les totaux : par exemple Zlatan Ibrahimović a 36 buts dans
  mes données contre 38 officiellement (FBref, Wikipedia). Je pense que l'écart vient du match
  Saint-Étienne-PSG, absent, mais je ne l'ai pas vérifié.
- Les minutes jouées sont calculées avec l'horloge du match : l'écart avec les minutes officielles
  peut atteindre quelques minutes (voir `docs/data_contract.md`).
- Une seule saison d'une seule compétition : les conclusions ne pourront pas être généralisées.

## Prochaines étapes

1. Requêtes SQL d'analyse (vues, CTE, fonctions de fenêtre, `EXPLAIN`)
2. Analyse statistique (indicateurs par 90 minutes avec intervalles de confiance)
3. API FastAPI en lecture seule et petite interface web
4. Tableau de bord Power BI
