# Journal de bord - Projet Sport Analytics

Je note ici ce que je fais, les problèmes que je rencontre et les choix que je prends.
Le but est de pouvoir expliquer chaque décision plus tard.

---

## Semaine 1 - Cadrage

### Ce que j'ai décidé
- Je choisis le projet **Sport Analytics** parce qu'il utilise des données **réelles**.
  Avec des données inventées, je retrouverais seulement ce que j'ai moi-même mis dedans.
- Je prends les données **StatsBomb Open Data** (football, fichiers JSON sur GitHub).
- Je regarde `competitions.json` : il y a 80 combinaisons compétition/saison.
  Je choisis la **Ligue 1 2015/2016** (competition_id 7, season_id 27) :
  elle est en français, et c'est une saison presque complète (377 matchs sur 380).
  Les 3 matchs manquants seront un vrai défaut de données à documenter.
- Ma question : *les écarts de buts, tirs et xG par 90 minutes entre joueurs sont-ils réels
  ou dus au hasard lié au temps de jeu ?*

### Ce que j'ai appris en regardant un premier match
- Un match = en moyenne 3 600 événements (passes, tirs, etc.) : 4 188 pour le premier que j'ai regardé, soit 3,5 Mo de JSON.
  Toute la saison pèse donc environ 1,1 Go.
- Une passe **sans** `outcome` est une passe réussie (957 réussies sur 1 166 dans ce match).
- Certains événements (début de mi-temps...) n'ont ni joueur ni position : c'est normal.
- Les tirs ont un `statsbomb_xg` (probabilité de but).
- Les compositions donnent l'heure d'entrée et de sortie de chaque joueur.
  Si la sortie est vide, le joueur est resté jusqu'à la fin.

### À faire
- [ ] Lire en entier le *User Agreement* de StatsBomb avant de publier quoi que ce soit.
  Pour l'instant je sais seulement qu'il faut citer StatsBomb et utiliser leur logo.

### Choix : SQLite au lieu de PostgreSQL
Je prends SQLite : un seul fichier, rien à installer, et c'est suffisant pour 1,3 million de lignes.
Je pourrai passer à PostgreSQL plus tard si j'en ai besoin.

### Ce qui est fait
- Structure du projet : `etl/`, `sql/`, `tests/`, `docs/`, `reports/`, `data/`.
- Script `etl/download.py` : télécharge les fichiers bruts. Il saute les fichiers déjà là,
  donc si ça s'arrête je peux le relancer sans tout recommencer.

### Problème rencontré
Le téléchargement s'est arrêté tout seul après 18 matchs. Je l'ai relancé en le détachant
du terminal, et il a repris où il s'était arrêté. Au final : 377 matchs, 1,1 Go, aucun fichier vide.

---

## Semaines 2-3 - Modèle SQL et ETL

### 1. Le modèle SQL (`sql/schema.sql`)
Tables : `competition`, `season`, `team`, `player`, `match`, `lineup`, `event`, `player_match`.

Choses que j'ai remarquées :
- `season_id` seul **n'est pas unique** (la saison 27 existe pour plusieurs compétitions).
  La clé de la table `season` est donc `(competition_id, season_id)`.
- Dans mon plan de départ, la table `player` avait une date de naissance et un poste.
  Ces champs n'existent pas dans les données : je garde seulement nom, surnom et pays.
- Mon plan prévoyait une table `player_match` avec des stats par match.
  Elle n'existe pas dans les données brutes : je la **calcule** moi-même à partir des
  événements (`sql/build_player_match.sql`).

Contraintes mises dans la base : clés primaires et étrangères, `NOT NULL`, `UNIQUE`
(un même match ne peut pas apparaître deux fois), et des `CHECK` (score >= 0, minute entre 0 et 130,
position dans le terrain 120 x 80, xG entre 0 et 1...). Sept index pour les requêtes futures.

### 2. Le data contract (`docs/data_contract.md`)
J'ai écrit les règles **avant** de coder l'ETL : champs attendus, types, limites.
Principe retenu : je rejette seulement ce qui est **impossible** (minute 200, score négatif).
Je ne rejette pas ce qui est seulement **rare** (xG de 0,95, score de 6-0).

### 3. L'ETL (`etl/etl.py`)
Les étapes : lire le JSON -> vérifier les règles -> garder les champs utiles ->
charger dans SQLite -> calculer `player_match` -> écrire le rapport qualité.

- Les lignes rejetées vont dans `reports/lignes_rejetees.csv` avec la raison.
- Je supprime et je recrée la base à chaque exécution : relancer donne toujours le même résultat.
- Minutes jouées : sortie moins entrée. Si la sortie est vide, j'utilise la dernière minute du match.
  Limite : le temps additionnel de la 1re mi-temps n'est pas compté.
- Les remplaçants qui ne sont pas entrés (3 083) sont ignorés dans `lineup`, mais ce n'est pas une erreur.

### 4. Les tests (`tests/test_etl.py`)
J'ai écrit 45 tests avec pytest, sur un mini jeu de données que je fabrique moi-même.
Ils couvrent : fichier absent, vide ou invalide, score négatif, date impossible, minute hors limites,
doublons, équipe ou joueur inconnu, champ manquant, sortie avant entrée, et les contraintes SQL.
Il y a aussi un test qui lance tout le pipeline deux fois et vérifie que les chiffres sont identiques.

**Vérification des tests** : pour être sûr que les tests servent à quelque chose, j'ai cassé
exprès deux endroits du code. Les tests ont bien échoué les deux fois.

**Une erreur bête** : après avoir remis le code d'origine, un test échouait encore. Le coupable était
le cache de Python (`__pycache__`) qui gardait l'ancienne version. J'ai supprimé le cache et tout
est repassé au vert. À retenir : si un test échoue de façon inexplicable, vider le cache.

### 5. Premier import sur les vraies données
Durée : environ 35 secondes. Résultat :

| | Lu | Chargé | Rejeté |
|---|---:|---:|---:|
| match | 377 | 377 | 0 |
| lineup | 10 479 | 10 479 | 0 |
| event | 1 358 593 | 1 358 593 | 0 (2 corrigés) |

Au premier essai, 2 événements avaient été rejetés (« position hors du terrain »).
Je les ai regardés : des passes à x = 120,4 et x = 120,5, donc à 40-50 cm de la limite du terrain.
Ce n'est pas une valeur impossible, c'est une imprécision de mesure (je ne connais pas la cause exacte).
**J'ai donc changé la règle** : tolérance de 1 unité, valeur ramenée à la limite, et la correction est
comptée dans le rapport. Au-delà de 1 unité, la ligne est toujours rejetée (test ajouté).

### 6. Ce que le rapport qualité m'a montré
- **3 matchs manquants** : Troyes-Bordeaux, Saint-Étienne-PSG, Bastia-Gazélec Ajaccio.
  Je les trouve en cherchant, parmi les 20 x 19 = 380 rencontres possibles, celles qui n'existent pas.
- **Aucune incohérence** entre le score officiel et les buts trouvés dans les événements (377 matchs sur 377).
- Minutes cumulées par équipe et par match : entre 995 et 1 126 (attendu : environ 11 x 90 à 98).
  Aucune équipe-match en dehors de 950-1 150.
- Aucun doublon de joueur, aucun tir sans xG.

### 7. Vérifications
Je ne voulais pas croire mon propre code sans contrôle.

**Contrôle interne** : j'ai recalculé les totaux directement depuis les fichiers JSON, avec un
script séparé qui n'utilise pas l'ETL. Tout est identique à la base :
1 358 593 événements, 374 239 passes, 8 814 tirs, 916 buts, 596 passes décisives, xG total 874,91.

**Contrôle externe** :
- Buts de la saison : 949 dans mes 377 matchs + 11 dans les 3 matchs absents = **960**,
  ce qui correspond au total de la saison indiqué sur Wikipedia.
  (Je n'ai pas vérifié que ces 3 matchs contiennent bien 11 buts : le total est seulement compatible.)
- Meilleurs buteurs : Zlatan Ibrahimović, Lacazette et Cavani sont aux mêmes rangs que dans
  les classements externes (FBref). Mais Zlatan a **36 buts** chez moi contre **38** officiellement,
  et 30 matchs contre 31. Je pense que c'est parce que le match Saint-Étienne-PSG manque,
  mais **je ne l'ai pas vérifié**. Je le garde en tête : toute analyse sur le PSG sera incomplète.

### Ce que je n'ai pas encore fait
- Lire le User Agreement StatsBomb.
- Vérifier les 3 matchs manquants (sont-ils ailleurs dans le dépôt StatsBomb ?).
- Comparer mes minutes jouées avec une source officielle.

---

## Prochaine étape - Semaines 4-5 : SQL analytique
Écrire 10 à 15 requêtes commentées (vues, CTE, fonctions de fenêtre, `HAVING` avec un seuil minimal
de minutes, `EXPLAIN` avant/après index).
