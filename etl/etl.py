"""
etl.py - lit les fichiers bruts StatsBomb, les vérifie, les nettoie
et les charge dans une base SQLite.

Étapes :
    1. Lecture des fichiers JSON
    2. Validation (règles du data contract, voir docs/data_contract.md)
    3. Transformation (on garde seulement les champs utiles, à plat)
    4. Chargement dans la base SQLite
    5. Calcul de la table player_match
    6. Rapport qualité + fichier des lignes rejetées

Utilisation :
    python etl/etl.py
"""
import csv
import datetime
import json
import os
import sqlite3
import sys
from collections import Counter

# ------------------------------------------------------------------
# Réglages
# ------------------------------------------------------------------
DOSSIER_PROJET = os.path.join(os.path.dirname(__file__), "..")
RAW_DIR = os.path.join(DOSSIER_PROJET, "data", "raw")
DB_PATH = os.path.join(DOSSIER_PROJET, "data", "sportanalytics.db")
SQL_DIR = os.path.join(DOSSIER_PROJET, "sql")
REPORTS_DIR = os.path.join(DOSSIER_PROJET, "reports")

COMPETITION_ID = 7   # Ligue 1
SEASON_ID = 27       # 2015/2016

# Limites du data contract
MINUTE_MAX = 130          # un match ne dure pas plus (prolongations comprises)
TERRAIN_X_MAX = 120       # le terrain StatsBomb fait 120 x 80
TERRAIN_Y_MAX = 80
TOLERANCE_TERRAIN = 1     # écart toléré hors du terrain : la valeur est ramenée à la limite


# ------------------------------------------------------------------
# Petites fonctions utiles
# ------------------------------------------------------------------
def horloge_en_minutes(texte):
    """Transforme "73:51" en 73.85 (minutes). None reste None."""
    if texte is None:
        return None
    morceaux = texte.split(":")
    if len(morceaux) != 2:
        raise ValueError("format d'horloge invalide : " + str(texte))
    minutes = int(morceaux[0])
    secondes = int(morceaux[1])
    if secondes < 0 or secondes > 59:
        raise ValueError("secondes invalides : " + str(texte))
    return minutes + secondes / 60


def date_valide(texte):
    """Vrai si le texte est une vraie date au format AAAA-MM-JJ."""
    try:
        datetime.datetime.strptime(texte, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def est_entier(valeur):
    # bool est un sous-type de int en Python : on l'exclut
    return isinstance(valeur, int) and not isinstance(valeur, bool)


def est_nombre(valeur):
    return isinstance(valeur, (int, float)) and not isinstance(valeur, bool)


def lire_json(chemin):
    """
    Lit un fichier JSON.
    Retourne (donnees, None) si tout va bien, ou (None, "raison") sinon.
    """
    if not os.path.exists(chemin):
        return None, "fichier absent"
    if os.path.getsize(chemin) == 0:
        return None, "fichier vide"
    try:
        with open(chemin, encoding="utf-8") as f:
            donnees = json.load(f)
    except json.JSONDecodeError:
        return None, "JSON invalide"
    if not isinstance(donnees, list) or len(donnees) == 0:
        return None, "aucune donnée dans le fichier"
    return donnees, None


# ------------------------------------------------------------------
# MATCHS : validation + transformation
# ------------------------------------------------------------------
def verifier_match(m, competition_id, season_id):
    """Retourne None si le match est valide, sinon la raison du rejet."""
    try:
        if not est_entier(m["match_id"]):
            return "match_id n'est pas un entier"
        if not date_valide(m["match_date"]):
            return "date invalide"
        if not est_entier(m["home_team"]["home_team_id"]) or not est_entier(m["away_team"]["away_team_id"]):
            return "identifiant d'équipe invalide"
        if m["home_team"]["home_team_id"] == m["away_team"]["away_team_id"]:
            return "une équipe joue contre elle-même"
        if not est_entier(m["home_score"]) or not est_entier(m["away_score"]):
            return "score invalide"
        if m["home_score"] < 0 or m["away_score"] < 0:
            return "score négatif"
        if m["competition"]["competition_id"] != competition_id or m["season"]["season_id"] != season_id:
            return "match hors de la compétition/saison choisie"
        if m.get("match_status") != "available":
            return "match non disponible"
    except (KeyError, TypeError):
        return "champ obligatoire absent"
    return None


def transformer_match(m):
    return {
        "match_id": m["match_id"],
        "competition_id": m["competition"]["competition_id"],
        "season_id": m["season"]["season_id"],
        "match_date": m["match_date"],
        "kick_off": m.get("kick_off"),
        "match_week": m.get("match_week"),
        "home_team_id": m["home_team"]["home_team_id"],
        "away_team_id": m["away_team"]["away_team_id"],
        "home_score": m["home_score"],
        "away_score": m["away_score"],
    }


# ------------------------------------------------------------------
# COMPOSITIONS : validation + transformation
# ------------------------------------------------------------------
def extraire_compositions(match_id, lineup_json, fin_match, equipes_du_match):
    """
    Transforme le fichier lineups d'un match en lignes pour la table lineup.
    Retourne (lignes, joueurs, rejets, nb_non_entres)
        rejets = liste de (cle, raison)
        nb_non_entres = remplaçants qui ne sont pas entrés (ce n'est pas une erreur)
    """
    lignes, joueurs, rejets = [], {}, []
    nb_non_entres = 0
    vus = set()

    for equipe in lineup_json:
        team_id = equipe.get("team_id")
        if team_id not in equipes_du_match:
            rejets.append((str(team_id), "équipe de la composition absente du match"))
            continue
        for j in equipe.get("lineup", []):
            player_id = j.get("player_id")
            cle = f"{match_id}/{player_id}"
            if not est_entier(player_id):
                rejets.append((cle, "player_id invalide"))
                continue
            if player_id in vus:
                rejets.append((cle, "joueur en double dans le match"))
                continue
            vus.add(player_id)

            # joueur de la feuille de match, enregistré dans tous les cas
            joueurs[player_id] = {
                "player_id": player_id,
                "name": j.get("player_name"),
                "nickname": j.get("player_nickname"),
                "country": (j.get("country") or {}).get("name"),
            }

            positions = j.get("positions") or []
            if len(positions) == 0:
                nb_non_entres += 1     # remplaçant jamais entré : normal
                continue
            try:
                debut = horloge_en_minutes(positions[0]["from"])
                fin = horloge_en_minutes(positions[-1]["to"])
            except (ValueError, KeyError, TypeError, AttributeError):
                rejets.append((cle, "horloge invalide"))
                continue
            if debut is None:
                rejets.append((cle, "heure d'entrée absente"))
                continue
            if fin is None:            # "to" = null veut dire : jusqu'au coup de sifflet final
                fin = fin_match
            if fin < debut:
                rejets.append((cle, "sortie avant l'entrée"))
                continue
            if fin - debut > MINUTE_MAX:
                rejets.append((cle, "durée de jeu impossible"))
                continue
            lignes.append({
                "match_id": match_id,
                "team_id": team_id,
                "player_id": player_id,
                "jersey_number": j.get("jersey_number"),
                "start_minute": round(debut, 2),
                "end_minute": round(fin, 2),
                "minutes_played": round(fin - debut, 2),
            })
    return lignes, joueurs, rejets, nb_non_entres


# ------------------------------------------------------------------
# ÉVÉNEMENTS : validation + transformation
# ------------------------------------------------------------------
def verifier_evenement(e, equipes_du_match, joueurs_du_match):
    """Retourne None si l'événement est valide, sinon la raison du rejet."""
    try:
        if not isinstance(e["id"], str) or e["id"] == "":
            return "event_id invalide"
        if not est_entier(e["index"]):
            return "index invalide"
        if not est_entier(e["period"]) or not 1 <= e["period"] <= 5:
            return "période hors domaine"
        if not est_entier(e["minute"]) or not 0 <= e["minute"] <= MINUTE_MAX:
            return "minute hors domaine"
        if not est_entier(e["second"]) or not 0 <= e["second"] <= 59:
            return "seconde hors domaine"
        if not e["type"]["name"]:
            return "type d'événement vide"
        if e["team"]["id"] not in equipes_du_match:
            return "équipe inconnue pour ce match"
    except (KeyError, TypeError):
        return "champ obligatoire absent"

    # joueur : facultatif (ex. "Half Start"), mais s'il est là il doit être connu
    if "player" in e and e["player"]["id"] not in joueurs_du_match:
        return "joueur absent de la composition du match"

    # position sur le terrain : facultative, mais si elle est là elle doit être dans le terrain
    if "location" in e:
        loc = e["location"]
        if not isinstance(loc, list) or len(loc) < 2 or not est_nombre(loc[0]) or not est_nombre(loc[1]):
            return "location invalide"
        t = TOLERANCE_TERRAIN
        if not -t <= loc[0] <= TERRAIN_X_MAX + t or not -t <= loc[1] <= TERRAIN_Y_MAX + t:
            return "location hors du terrain"

    # xG : seulement pour les tirs, entre 0 et 1
    if "shot" in e:
        xg = e["shot"].get("statsbomb_xg")
        if xg is not None and (not est_nombre(xg) or not 0 <= xg <= 1):
            return "xG hors domaine"
    return None


def ramener(valeur, maximum):
    """Ramène une coordonnée légèrement hors du terrain à la limite (0 ou maximum)."""
    return min(max(valeur, 0), maximum)


def transformer_evenement(e, match_id):
    loc = e.get("location")
    type_ev = e["type"]["name"]

    # issue : pour un tir ou une passe seulement
    outcome = None
    xg = None
    est_passe_decisive = 0
    if "shot" in e:
        outcome = (e["shot"].get("outcome") or {}).get("name")
        xg = e["shot"].get("statsbomb_xg")
    elif "pass" in e:
        outcome = (e["pass"].get("outcome") or {}).get("name")
        if e["pass"].get("goal_assist") is True:
            est_passe_decisive = 1

    return {
        "event_id": e["id"],
        "match_id": match_id,
        "event_index": e["index"],
        "period": e["period"],
        "minute": e["minute"],
        "second": e["second"],
        "type": type_ev,
        "team_id": e["team"]["id"],
        "player_id": e["player"]["id"] if "player" in e else None,
        "position": e["position"]["name"] if "position" in e else None,
        "x": ramener(loc[0], TERRAIN_X_MAX) if loc else None,
        "y": ramener(loc[1], TERRAIN_Y_MAX) if loc else None,
        "outcome": outcome,
        "xg": xg,
        "is_goal_assist": est_passe_decisive,
    }


def fin_de_match_en_minutes(evenements):
    """Dernière minute jouée dans le match (sert pour les joueurs qui finissent le match)."""
    plus_grand = 0
    for e in evenements:
        try:
            plus_grand = max(plus_grand, e["minute"] + e["second"] / 60)
        except (KeyError, TypeError):
            pass
    return plus_grand


# ------------------------------------------------------------------
# CHARGEMENT dans SQLite
# ------------------------------------------------------------------
def inserer(connexion, table, lignes):
    """Insère une liste de dictionnaires dans une table."""
    if not lignes:
        return
    colonnes = list(lignes[0].keys())
    requete = "INSERT INTO {} ({}) VALUES ({})".format(
        table, ", ".join(colonnes), ", ".join("?" for _ in colonnes))
    connexion.executemany(requete, [[l[c] for c in colonnes] for l in lignes])


def lire_fichier_sql(nom):
    with open(os.path.join(SQL_DIR, nom), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------
# PROGRAMME PRINCIPAL
# ------------------------------------------------------------------
def lancer_etl(raw_dir=RAW_DIR, db_path=DB_PATH, reports_dir=REPORTS_DIR,
               competition_id=COMPETITION_ID, season_id=SEASON_ID, verbose=True):
    """
    Lance tout le pipeline. On supprime et on recrée la base à chaque fois :
    relancer l'ETL donne donc toujours le même résultat (pas de doublons).
    Retourne un dictionnaire de résultats (utile pour les tests).
    """
    def dire(texte):
        if verbose:
            print(texte)

    os.makedirs(reports_dir, exist_ok=True)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    lus = Counter()        # nombre de lignes lues, par table
    valides = Counter()    # nombre de lignes valides, par table
    rejets = []            # (table, fichier, cle, raison)
    fichiers_ignores = []  # (fichier, raison)
    non_entres = 0
    corrections = Counter()  # valeurs corrigées (et non rejetées)

    # ---- 1) Les matchs ----
    chemin_matchs = os.path.join(raw_dir, "matches", f"{competition_id}_{season_id}.json")
    matchs_bruts, erreur = lire_json(chemin_matchs)
    if erreur:
        raise RuntimeError(f"Impossible de lire la liste des matchs : {erreur} ({chemin_matchs})")

    # ---- 2) Les compétitions (pour le nom et le pays) ----
    comps, erreur = lire_json(os.path.join(raw_dir, "competitions.json"))
    if erreur:
        raise RuntimeError(f"Impossible de lire competitions.json : {erreur}")
    comp = None
    for c in comps:
        if c.get("competition_id") == competition_id and c.get("season_id") == season_id:
            comp = c
    if comp is None:
        raise RuntimeError("Compétition/saison introuvable dans competitions.json")

    competition = {"competition_id": competition_id, "name": comp["competition_name"],
                   "country": comp["country_name"]}
    saison = {"competition_id": competition_id, "season_id": season_id, "label": comp["season_name"]}

    equipes = {}           # team_id -> nom
    joueurs = {}           # player_id -> infos
    matchs, compos, evenements = [], [], []
    ids_matchs_vus = set()

    for m in matchs_bruts:
        lus["match"] += 1
        raison = verifier_match(m, competition_id, season_id)
        if raison is None and m["match_id"] in ids_matchs_vus:
            raison = "match en double"
        if raison:
            cle = str(m.get("match_id")) if isinstance(m, dict) else "?"
            rejets.append(("match", f"matches/{competition_id}_{season_id}.json", cle, raison))
            continue
        ids_matchs_vus.add(m["match_id"])
        valides["match"] += 1
        matchs.append(transformer_match(m))
        equipes[m["home_team"]["home_team_id"]] = m["home_team"]["home_team_name"]
        equipes[m["away_team"]["away_team_id"]] = m["away_team"]["away_team_name"]

    # ---- 3) Compositions et événements, match par match ----
    ids_evenements_vus = set()
    for m in matchs:
        match_id = m["match_id"]
        equipes_du_match = {m["home_team_id"], m["away_team_id"]}

        evs_bruts, err_ev = lire_json(os.path.join(raw_dir, "events", f"{match_id}.json"))
        lu_bruts, err_lu = lire_json(os.path.join(raw_dir, "lineups", f"{match_id}.json"))
        if err_ev or err_lu:
            if err_ev:
                fichiers_ignores.append((f"events/{match_id}.json", err_ev))
            if err_lu:
                fichiers_ignores.append((f"lineups/{match_id}.json", err_lu))
            continue

        # compositions
        fin_match = fin_de_match_en_minutes(evs_bruts)
        lignes_lu, joueurs_match, rej_lu, nb_ne = extraire_compositions(
            match_id, lu_bruts, fin_match, equipes_du_match)
        lus["lineup"] += len(lignes_lu) + len(rej_lu)
        valides["lineup"] += len(lignes_lu)
        non_entres += nb_ne
        for cle, raison in rej_lu:
            rejets.append(("lineup", f"lineups/{match_id}.json", cle, raison))
        compos.extend(lignes_lu)
        joueurs.update(joueurs_match)

        # événements : un joueur est "connu" s'il est dans la feuille de match
        joueurs_du_match = set(joueurs_match.keys())
        for e in evs_bruts:
            lus["event"] += 1
            raison = verifier_evenement(e, equipes_du_match, joueurs_du_match)
            if raison is None and e["id"] in ids_evenements_vus:
                raison = "événement en double"
            if raison:
                rejets.append(("event", f"events/{match_id}.json",
                               str(e.get("id", "?")) if isinstance(e, dict) else "?", raison))
                continue
            ids_evenements_vus.add(e["id"])
            valides["event"] += 1
            ligne = transformer_evenement(e, match_id)
            if "location" in e and (ligne["x"] != e["location"][0] or ligne["y"] != e["location"][1]):
                corrections["position légèrement hors terrain, ramenée à la limite"] += 1
            evenements.append(ligne)

    # ---- 4) Chargement ----
    dire("Chargement dans la base...")
    if os.path.exists(db_path):
        os.remove(db_path)
    connexion = sqlite3.connect(db_path)
    connexion.executescript(lire_fichier_sql("schema.sql"))
    connexion.execute("INSERT INTO competition VALUES (?, ?, ?)",
                      (competition["competition_id"], competition["name"], competition["country"]))
    connexion.execute("INSERT INTO season VALUES (?, ?, ?)",
                      (saison["competition_id"], saison["season_id"], saison["label"]))
    inserer(connexion, "team", [{"team_id": i, "name": n} for i, n in sorted(equipes.items())])
    inserer(connexion, "player", [joueurs[i] for i in sorted(joueurs)])
    inserer(connexion, "match", matchs)
    inserer(connexion, "lineup", compos)
    inserer(connexion, "event", evenements)
    connexion.commit()

    # ---- 5) Table calculée ----
    connexion.executescript(lire_fichier_sql("build_player_match.sql"))
    connexion.commit()

    # ---- 6) Rapport qualité ----
    resultats = ecrire_rapport(connexion, reports_dir, lus, valides, rejets,
                               fichiers_ignores, non_entres, corrections)
    connexion.close()
    dire(f"Terminé : {valides['match']} matchs, {valides['lineup']} lignes de composition, "
         f"{valides['event']} événements chargés.")
    dire(f"Lignes rejetées : {len(rejets)} (voir reports/lignes_rejetees.csv)")
    return resultats


# ------------------------------------------------------------------
# RAPPORT QUALITÉ
# ------------------------------------------------------------------
def ecrire_rapport(connexion, reports_dir, lus, valides, rejets, fichiers_ignores, non_entres,
                   corrections):
    # fichier des lignes rejetées
    with open(os.path.join(reports_dir, "lignes_rejetees.csv"), "w", newline="", encoding="utf-8") as f:
        ecrivain = csv.writer(f)
        ecrivain.writerow(["table", "fichier", "cle", "raison"])
        ecrivain.writerows(rejets)

    requete = lambda sql: connexion.execute(sql).fetchall()

    # matchs attendus : pour un championnat à N équipes, chaque équipe reçoit chaque autre une fois
    nb_equipes = requete("SELECT COUNT(*) FROM team")[0][0]
    attendus = nb_equipes * (nb_equipes - 1)
    presents = requete("SELECT COUNT(*) FROM match")[0][0]
    rencontres_presentes = set(requete("SELECT home_team_id, away_team_id FROM match"))
    equipes = dict(requete("SELECT team_id, name FROM team"))
    manquants = []
    for dom in equipes:
        for ext in equipes:
            if dom != ext and (dom, ext) not in rencontres_presentes:
                manquants.append(f"{equipes[dom]} - {equipes[ext]}")

    # cohérence : score du match vs buts trouvés dans les événements
    # (buts = tirs "Goal" + buts contre son camp attribués à l'équipe qui en profite)
    incoherences = requete("""
        WITH buts AS (
            SELECT match_id, team_id, COUNT(*) AS n
            FROM event
            WHERE period <= 4
              AND ((type = 'Shot' AND outcome = 'Goal') OR type = 'Own Goal For')
            GROUP BY match_id, team_id
        )
        SELECT m.match_id, m.match_date, th.name, ta.name,
               m.home_score, m.away_score,
               COALESCE(bh.n, 0) AS buts_dom, COALESCE(ba.n, 0) AS buts_ext
        FROM match m
        JOIN team th ON th.team_id = m.home_team_id
        JOIN team ta ON ta.team_id = m.away_team_id
        LEFT JOIN buts bh ON bh.match_id = m.match_id AND bh.team_id = m.home_team_id
        LEFT JOIN buts ba ON ba.match_id = m.match_id AND ba.team_id = m.away_team_id
        WHERE m.home_score <> COALESCE(bh.n, 0)
           OR m.away_score <> COALESCE(ba.n, 0)
        ORDER BY m.match_date
    """)

    # doublons de joueurs (même nom, identifiants différents)
    doublons_noms = requete("""
        SELECT name, COUNT(*) FROM player GROUP BY name HAVING COUNT(*) > 1""")

    # valeurs manquantes dans les événements (NULL attendu pour certains types)
    nb_event = requete("SELECT COUNT(*) FROM event")[0][0]
    sans_joueur = requete("SELECT COUNT(*) FROM event WHERE player_id IS NULL")[0][0]
    sans_pos = requete("SELECT COUNT(*) FROM event WHERE x IS NULL")[0][0]
    tirs = requete("SELECT COUNT(*) FROM event WHERE type='Shot'")[0][0]
    tirs_sans_xg = requete("SELECT COUNT(*) FROM event WHERE type='Shot' AND xg IS NULL")[0][0]

    # minutes jouées : contrôle de plausibilité
    stats_minutes = requete("""SELECT MIN(minutes_played), MAX(minutes_played), ROUND(AVG(minutes_played),1)
                               FROM lineup""")[0]
    nb_pm = requete("SELECT COUNT(*) FROM player_match")[0][0]

    # contrôle : la somme des buts de player_match doit égaler les tirs "Goal"
    buts_pm = requete("SELECT COALESCE(SUM(goals),0) FROM player_match")[0][0]
    buts_ev = requete("SELECT COUNT(*) FROM event WHERE type='Shot' AND outcome='Goal'")[0][0]

    raisons = Counter((t, r) for (t, _, _, r) in rejets)

    lignes = []
    ajouter = lignes.append
    ajouter("# Rapport qualité - import Ligue 1 2015/2016")
    ajouter("")
    ajouter(f"Généré le {datetime.date.today().isoformat()} par `etl/etl.py`.")
    ajouter("")
    ajouter("## Volumes")
    ajouter("")
    ajouter("| Table | Lignes lues | Valides | Rejetées |")
    ajouter("|---|---:|---:|---:|")
    for table in ["match", "lineup", "event"]:
        ajouter(f"| {table} | {lus[table]} | {valides[table]} | {lus[table] - valides[table]} |")
    ajouter("")
    ajouter(f"Fichiers ignorés (absents/vides/invalides) : {len(fichiers_ignores)}")
    for fichier, raison in fichiers_ignores:
        ajouter(f"- `{fichier}` : {raison}")
    ajouter("")
    ajouter("## Raisons de rejet")
    ajouter("")
    if raisons:
        ajouter("| Table | Raison | Nombre |")
        ajouter("|---|---|---:|")
        for (table, raison), n in raisons.most_common():
            ajouter(f"| {table} | {raison} | {n} |")
    else:
        ajouter("Aucune ligne rejetée.")
    ajouter("")
    ajouter("## Corrections appliquées (lignes gardées)")
    ajouter("")
    if corrections:
        for raison, n in corrections.items():
            ajouter(f"- {raison} (tolérance : {TOLERANCE_TERRAIN} unité) : {n}")
    else:
        ajouter("Aucune correction.")
    ajouter("")
    ajouter("## Complétude des matchs")
    ajouter("")
    ajouter(f"- Équipes : {nb_equipes}. Matchs attendus (aller-retour, hypothèse : championnat) : "
            f"{nb_equipes} x {nb_equipes - 1} = **{attendus}**.")
    ajouter(f"- Matchs présents : **{presents}**. Manquants : **{len(manquants)}**.")
    for m in manquants:
        ajouter(f"  - {m} (domicile - extérieur)")
    ajouter("")
    ajouter("## Cohérence score / événements")
    ajouter("")
    ajouter(f"Matchs où le score officiel diffère du nombre de buts trouvés dans les événements : "
            f"**{len(incoherences)}** sur {presents}.")
    for (mid, date, dom, ext, sd, se, ed, ee) in incoherences[:30]:
        ajouter(f"- {date} {dom} - {ext} (match {mid}) : score {sd}-{se}, événements {ed}-{ee}")
    ajouter("")
    ajouter("## Valeurs manquantes (NULL)")
    ajouter("")
    ajouter(f"- Événements sans joueur : {sans_joueur} / {nb_event} "
            f"({100 * sans_joueur / max(nb_event, 1):.1f} %) - normal pour des types comme Half Start.")
    ajouter(f"- Événements sans position (x, y) : {sans_pos} / {nb_event} "
            f"({100 * sans_pos / max(nb_event, 1):.1f} %) - normal pour des types comme Substitution.")
    ajouter(f"- Tirs sans xG : {tirs_sans_xg} / {tirs}.")
    ajouter(f"- Remplaçants qui ne sont pas entrés (ignorés, pas une erreur) : {non_entres}.")
    ajouter("")
    ajouter("## Contrôles de plausibilité")
    ajouter("")
    ajouter(f"- Minutes jouées par joueur et par match : min {stats_minutes[0]}, "
            f"max {stats_minutes[1]}, moyenne {stats_minutes[2]}.")
    ajouter(f"- Lignes player_match : {nb_pm} (doit être égal au nombre de lignes lineup valides : {valides['lineup']}).")
    ajouter(f"- Buts dans player_match : {buts_pm} ; tirs 'Goal' dans event : {buts_ev}.")
    ajouter(f"- Noms de joueurs avec plusieurs identifiants : {len(doublons_noms)}.")
    for nom, n in doublons_noms[:10]:
        ajouter(f"  - {nom} ({n} identifiants)")
    ajouter("")

    with open(os.path.join(reports_dir, "rapport_qualite.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lignes))

    return {
        "lus": dict(lus), "valides": dict(valides), "rejets": rejets,
        "fichiers_ignores": fichiers_ignores, "matchs_manquants": manquants,
        "corrections": dict(corrections),
        "incoherences": incoherences, "nb_player_match": nb_pm,
    }


if __name__ == "__main__":
    try:
        lancer_etl()
    except RuntimeError as erreur:
        print("ERREUR :", erreur)
        sys.exit(1)
