# Rapport qualité - import Ligue 1 2015/2016

Généré le 2026-10-01 par `etl/etl.py`.

## Volumes

| Table | Lignes lues | Valides | Rejetées |
|---|---:|---:|---:|
| match | 377 | 377 | 0 |
| lineup | 10479 | 10479 | 0 |
| event | 1358593 | 1358593 | 0 |

Fichiers ignorés (absents/vides/invalides) : 0

## Raisons de rejet

Aucune ligne rejetée.

## Corrections appliquées (lignes gardées)

- position légèrement hors terrain, ramenée à la limite (tolérance : 1 unité) : 2

## Complétude des matchs

- Équipes : 20. Matchs attendus (aller-retour, hypothèse : championnat) : 20 x 19 = **380**.
- Matchs présents : **377**. Manquants : **3**.
  - Troyes - Bordeaux (domicile - extérieur)
  - Saint-Étienne - Paris Saint-Germain (domicile - extérieur)
  - Bastia - Gazélec Ajaccio (domicile - extérieur)

## Cohérence score / événements

Matchs où le score officiel diffère du nombre de buts trouvés dans les événements : **0** sur 377.

## Valeurs manquantes (NULL)

- Événements sans joueur : 5494 / 1358593 (0.4 %) - normal pour des types comme Half Start.
- Événements sans position (x, y) : 10123 / 1358593 (0.7 %) - normal pour des types comme Substitution.
- Tirs sans xG : 0 / 8814.
- Remplaçants qui ne sont pas entrés (ignorés, pas une erreur) : 3083.

## Contrôles de plausibilité

- Minutes jouées par joueur et par match : min 0.4, max 98.57, moyenne 74.2.
- Lignes player_match : 10479 (doit être égal au nombre de lignes lineup valides : 10479).
- Buts dans player_match : 916 ; tirs 'Goal' dans event : 916.
- Noms de joueurs avec plusieurs identifiants : 0.
