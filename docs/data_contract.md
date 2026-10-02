# Data contract (version simple)

Un data contract, c'est la liste des **règles** que les données doivent respecter
avant que je les mette dans ma base. C'est comme le règlement d'un jeu :
si une ligne ne respecte pas une règle, elle n'entre pas dans la base.

- Les lignes refusées sont écrites dans `reports/lignes_rejetees.csv`, avec la raison.
- Les données viennent de **StatsBomb Open Data** : Ligue 1, saison 2015/2016.

## Les règles

### Pour chaque match
- Il a un numéro (`match_id`) unique : pas deux fois le même match.
- La date existe vraiment (le 30 février est refusé).
- Les deux équipes sont différentes (une équipe ne joue pas contre elle-même).
- Les scores ne sont pas négatifs.

### Pour chaque joueur dans un match
- Il est dans l'une des deux équipes du match.
- Il n'apparaît qu'une seule fois dans le match.
- Il ne peut pas sortir avant d'être entré.
- Il ne joue pas plus de 130 minutes.

### Pour chaque événement (une passe, un tir...)
- Il a un identifiant unique : pas deux fois le même événement.
- La minute est entre 0 et 130, la seconde entre 0 et 59.
- Il appartient à l'une des deux équipes du match.
- Le joueur est facultatif (le coup d'envoi n'a pas de joueur), mais s'il est indiqué,
  il doit faire partie du match.
- La position est facultative. Si elle est indiquée, elle doit être dans le terrain
  (120 de long, 80 de large), avec une petite tolérance de 1.
- La probabilité de but (xG) d'un tir est entre 0 et 1.

## Impossible ou juste rare ?

Je refuse seulement ce qui est **impossible** : une minute 200, un score de -3.
Je garde ce qui est seulement **rare** : un match 6-0, un tir avec 95 % de chances de but.
Ces valeurs rares sont peut-être justement ce que je veux étudier.

## Ce que j'ai décidé de simplifier

- Les minutes jouées sont calculées avec l'horloge du match : elles peuvent être
  différentes de quelques minutes des chiffres officiels.
- Un but = un tir dont le résultat est "But" (penalty compris).
- Une passe sans résultat indiqué = une passe réussie (c'est la façon de faire de StatsBomb).
- Une saison de Ligue 1 a 20 équipes, donc 20 x 19 = 380 matchs. Si j'en trouve moins,
  je le signale dans le rapport.
