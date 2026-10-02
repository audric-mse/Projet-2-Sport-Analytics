"""
Tests de l'ETL. Lancer avec :  python -m pytest tests/ -v

Ces tests n'ont pas besoin des vraies données : je fabrique un tout petit
jeu de données (2 matchs) dans un dossier temporaire.
"""
import copy
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))
import etl  # noqa: E402


# ------------------------------------------------------------------
# Fabrication de petites données de test
# ------------------------------------------------------------------
def un_match(match_id=1, dom=10, ext=20, score_dom=1, score_ext=0, date="2016-01-10"):
    return {
        "match_id": match_id,
        "match_date": date,
        "kick_off": "20:00:00.000",
        "competition": {"competition_id": 7, "competition_name": "Ligue 1"},
        "season": {"season_id": 27, "season_name": "2015/2016"},
        "home_team": {"home_team_id": dom, "home_team_name": f"Equipe {dom}"},
        "away_team": {"away_team_id": ext, "away_team_name": f"Equipe {ext}"},
        "home_score": score_dom,
        "away_score": score_ext,
        "match_status": "available",
        "match_week": 1,
    }


def un_evenement(ev_id="e1", index=1, type_ev="Pass", team=10, player=100, minute=5, second=0,
                 location=(60.0, 40.0)):
    e = {
        "id": ev_id, "index": index, "period": 1, "minute": minute, "second": second,
        "type": {"name": type_ev}, "team": {"id": team},
    }
    if player is not None:
        e["player"] = {"id": player}
    if location is not None:
        e["location"] = list(location)
    return e


def un_tir_but(ev_id="s1", index=2, team=10, player=100, minute=30, xg=0.4):
    e = un_evenement(ev_id, index, "Shot", team, player, minute)
    e["shot"] = {"statsbomb_xg": xg, "outcome": {"name": "Goal"}}
    return e


def une_composition():
    """Équipe 10 : joueur 100 joue tout le match, joueur 101 remplacé à la 60e,
    joueur 102 remplaçant jamais entré. Équipe 20 : joueur 200 joue tout le match."""
    def joueur(pid, positions):
        return {"player_id": pid, "player_name": f"Joueur {pid}", "player_nickname": None,
                "jersey_number": pid % 100, "country": {"name": "France"}, "positions": positions}
    return [
        {"team_id": 10, "lineup": [
            joueur(100, [{"from": "00:00", "to": None}]),
            joueur(101, [{"from": "00:00", "to": "60:00"}]),
            joueur(102, []),
        ]},
        {"team_id": 20, "lineup": [joueur(200, [{"from": "00:00", "to": None}])]},
    ]


def ecrire(chemin, contenu):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(contenu, f)


def fabriquer_dossier_raw(tmp_path, matchs=None):
    """Crée data/raw complet pour 1 match valide (n°1) et retourne le dossier."""
    raw = str(tmp_path / "raw")
    ecrire(os.path.join(raw, "competitions.json"),
           [{"competition_id": 7, "season_id": 27, "competition_name": "Ligue 1",
             "season_name": "2015/2016", "country_name": "France"}])
    ecrire(os.path.join(raw, "matches", "7_27.json"), matchs or [un_match()])
    ecrire(os.path.join(raw, "lineups", "1.json"), une_composition())
    ecrire(os.path.join(raw, "events", "1.json"), [
        un_evenement("e1", 1, "Half Start", player=None, location=None, minute=0),
        un_evenement("e2", 2, "Pass", 10, 100, 5),
        un_tir_but("e3", 3, 10, 100, 30, 0.4),
        un_evenement("e4", 4, "Pass", 20, 200, 90),
    ])
    return raw


# ------------------------------------------------------------------
# Petites fonctions
# ------------------------------------------------------------------
def test_horloge_en_minutes():
    assert etl.horloge_en_minutes("73:51") == pytest.approx(73.85)
    assert etl.horloge_en_minutes("00:00") == 0
    assert etl.horloge_en_minutes(None) is None


@pytest.mark.parametrize("texte", ["abc", "12", "10:75", "1:2:3"])
def test_horloge_invalide(texte):
    with pytest.raises(ValueError):
        etl.horloge_en_minutes(texte)


def test_date_valide():
    assert etl.date_valide("2016-02-29")        # 2016 est bissextile
    assert not etl.date_valide("2015-02-29")
    assert not etl.date_valide("10/01/2016")
    assert not etl.date_valide(None)


# ------------------------------------------------------------------
# Lecture de fichiers
# ------------------------------------------------------------------
def test_lire_json_fichier_absent(tmp_path):
    assert etl.lire_json(str(tmp_path / "nexiste_pas.json"))[1] == "fichier absent"


def test_lire_json_fichier_vide(tmp_path):
    chemin = tmp_path / "vide.json"
    chemin.write_text("")
    assert etl.lire_json(str(chemin))[1] == "fichier vide"


def test_lire_json_invalide(tmp_path):
    chemin = tmp_path / "casse.json"
    chemin.write_text("{pas du json")
    assert etl.lire_json(str(chemin))[1] == "JSON invalide"


def test_lire_json_liste_vide(tmp_path):
    chemin = tmp_path / "liste_vide.json"
    chemin.write_text("[]")
    assert etl.lire_json(str(chemin))[1] == "aucune donnée dans le fichier"


# ------------------------------------------------------------------
# Matchs
# ------------------------------------------------------------------
def test_match_valide():
    assert etl.verifier_match(un_match(), 7, 27) is None


def test_match_score_negatif():
    assert etl.verifier_match(un_match(score_dom=-1), 7, 27) == "score négatif"


def test_match_meme_equipe():
    assert etl.verifier_match(un_match(dom=10, ext=10), 7, 27) == "une équipe joue contre elle-même"


def test_match_date_invalide():
    assert etl.verifier_match(un_match(date="2016-13-45"), 7, 27) == "date invalide"


def test_match_champ_absent():
    m = un_match()
    del m["home_score"]
    assert etl.verifier_match(m, 7, 27) == "champ obligatoire absent"


def test_match_autre_saison():
    assert etl.verifier_match(un_match(), 7, 99) == "match hors de la compétition/saison choisie"


# ------------------------------------------------------------------
# Événements
# ------------------------------------------------------------------
EQUIPES = {10, 20}
JOUEURS = {100, 101, 200}


def test_evenement_valide():
    assert etl.verifier_evenement(un_evenement(), EQUIPES, JOUEURS) is None


def test_evenement_sans_joueur_est_normal():
    e = un_evenement(type_ev="Half Start", player=None, location=None)
    assert etl.verifier_evenement(e, EQUIPES, JOUEURS) is None


def test_evenement_minute_hors_domaine():
    assert etl.verifier_evenement(un_evenement(minute=200), EQUIPES, JOUEURS) == "minute hors domaine"
    assert etl.verifier_evenement(un_evenement(minute=-1), EQUIPES, JOUEURS) == "minute hors domaine"


def test_evenement_seconde_hors_domaine():
    assert etl.verifier_evenement(un_evenement(second=75), EQUIPES, JOUEURS) == "seconde hors domaine"


def test_evenement_hors_du_terrain():
    e = un_evenement(location=(150.0, 40.0))
    assert etl.verifier_evenement(e, EQUIPES, JOUEURS) == "location hors du terrain"


def test_evenement_legerement_hors_du_terrain_est_tolere():
    """120.4 est à 0.4 du bord : on le garde (cas réel rencontré dans les données)."""
    e = un_evenement(location=(120.4, 80.0))
    assert etl.verifier_evenement(e, EQUIPES, JOUEURS) is None
    ligne = etl.transformer_evenement(e, 1)
    assert ligne["x"] == 120          # ramené à la limite du terrain
    assert ligne["y"] == 80


def test_evenement_trop_hors_du_terrain_est_rejete():
    e = un_evenement(location=(122.0, 40.0))
    assert etl.verifier_evenement(e, EQUIPES, JOUEURS) == "location hors du terrain"


def test_evenement_equipe_inconnue():
    assert etl.verifier_evenement(un_evenement(team=999), EQUIPES, JOUEURS) == "équipe inconnue pour ce match"


def test_evenement_joueur_inconnu():
    assert etl.verifier_evenement(un_evenement(player=999), EQUIPES, JOUEURS) == \
        "joueur absent de la composition du match"


def test_evenement_xg_hors_domaine():
    e = un_tir_but(xg=1.7)
    assert etl.verifier_evenement(e, EQUIPES, JOUEURS) == "xG hors domaine"


def test_evenement_champ_absent():
    e = un_evenement()
    del e["team"]
    assert etl.verifier_evenement(e, EQUIPES, JOUEURS) == "champ obligatoire absent"


def test_valeur_rare_n_est_pas_rejetee():
    """Un xG très élevé (0.99) est rare mais possible : on ne doit PAS le rejeter."""
    assert etl.verifier_evenement(un_tir_but(xg=0.99), EQUIPES, JOUEURS) is None


def test_transformer_passe_reussie_et_passe_decisive():
    e = un_evenement()
    e["pass"] = {"goal_assist": True}
    ligne = etl.transformer_evenement(e, 1)
    assert ligne["outcome"] is None           # pas d'outcome = passe réussie
    assert ligne["is_goal_assist"] == 1


def test_transformer_tir():
    ligne = etl.transformer_evenement(un_tir_but(xg=0.4), 1)
    assert ligne["outcome"] == "Goal"
    assert ligne["xg"] == 0.4


# ------------------------------------------------------------------
# Compositions
# ------------------------------------------------------------------
def test_compositions_minutes():
    lignes, joueurs, rejets, non_entres = etl.extraire_compositions(1, une_composition(), 94.5, {10, 20})
    par_joueur = {l["player_id"]: l for l in lignes}
    assert par_joueur[100]["minutes_played"] == 94.5     # a fini le match
    assert par_joueur[101]["minutes_played"] == 60.0     # remplacé à la 60e
    assert non_entres == 1                               # joueur 102
    assert 102 in joueurs                                # mais il est connu
    assert rejets == []


def test_compositions_sortie_avant_entree():
    compo = une_composition()
    compo[0]["lineup"][1]["positions"] = [{"from": "50:00", "to": "40:00"}]
    lignes, _, rejets, _ = etl.extraire_compositions(1, compo, 90, {10, 20})
    assert ("1/101", "sortie avant l'entrée") in rejets
    assert 101 not in [l["player_id"] for l in lignes]


def test_compositions_joueur_en_double():
    compo = une_composition()
    compo[0]["lineup"].append(copy.deepcopy(compo[0]["lineup"][0]))
    _, _, rejets, _ = etl.extraire_compositions(1, compo, 90, {10, 20})
    assert ("1/100", "joueur en double dans le match") in rejets


def test_compositions_equipe_inconnue():
    _, _, rejets, _ = etl.extraire_compositions(1, une_composition(), 90, {10})
    assert any(raison == "équipe de la composition absente du match" for _, raison in rejets)


# ------------------------------------------------------------------
# La base SQL elle-même refuse les données impossibles
# ------------------------------------------------------------------
@pytest.fixture
def base_vide():
    connexion = sqlite3.connect(":memory:")
    with open(os.path.join(etl.SQL_DIR, "schema.sql"), encoding="utf-8") as f:
        connexion.executescript(f.read())
    connexion.execute("INSERT INTO competition VALUES (7, 'Ligue 1', 'France')")
    connexion.execute("INSERT INTO season VALUES (7, 27, '2015/2016')")
    connexion.execute("INSERT INTO team VALUES (10, 'A')")
    connexion.execute("INSERT INTO team VALUES (20, 'B')")
    connexion.execute("INSERT INTO match VALUES (1, 7, 27, '2016-01-10', NULL, 1, 10, 20, 1, 0)")
    connexion.execute("INSERT INTO player VALUES (100, 'J', NULL, NULL)")
    return connexion


def test_sql_refuse_minutes_negatives(base_vide):
    with pytest.raises(sqlite3.IntegrityError):
        base_vide.execute("INSERT INTO lineup VALUES (1, 10, 100, 9, 0, 10, -5)")


def test_sql_refuse_equipe_inexistante(base_vide):
    with pytest.raises(sqlite3.IntegrityError):
        base_vide.execute("INSERT INTO lineup VALUES (1, 999, 100, 9, 0, 90, 90)")


def test_sql_refuse_match_en_double(base_vide):
    with pytest.raises(sqlite3.IntegrityError):
        base_vide.execute("INSERT INTO match VALUES (2, 7, 27, '2016-02-10', NULL, 2, 10, 20, 0, 0)")


def test_sql_refuse_equipe_contre_elle_meme(base_vide):
    with pytest.raises(sqlite3.IntegrityError):
        base_vide.execute("INSERT INTO match VALUES (3, 7, 27, '2016-02-10', NULL, 2, 10, 10, 0, 0)")


# ------------------------------------------------------------------
# Test d'intégration : tout le pipeline sur le mini jeu de données
# ------------------------------------------------------------------
def lancer(tmp_path, raw):
    return etl.lancer_etl(raw_dir=raw, db_path=str(tmp_path / "test.db"),
                          reports_dir=str(tmp_path / "reports"), verbose=False)


def compter(tmp_path, table):
    connexion = sqlite3.connect(str(tmp_path / "test.db"))
    n = connexion.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    connexion.close()
    return n


def test_pipeline_complet(tmp_path):
    raw = fabriquer_dossier_raw(tmp_path)
    resultats = lancer(tmp_path, raw)
    assert compter(tmp_path, "match") == 1
    assert compter(tmp_path, "event") == 4
    assert compter(tmp_path, "lineup") == 3           # 100, 101, 200 (102 n'est pas entré)
    assert compter(tmp_path, "player") == 4           # 102 est quand même connu
    assert resultats["incoherences"] == []            # 1 but dans les événements = score 1-0

    connexion = sqlite3.connect(str(tmp_path / "test.db"))
    # joueur 100 : 1 passe, 1 tir, 1 but, xG 0.4
    ligne = connexion.execute(
        "SELECT shots, goals, xg, passes, passes_completed FROM player_match WHERE player_id = 100"
    ).fetchone()
    connexion.close()
    assert ligne == (1, 1, 0.4, 1, 1)
    assert os.path.exists(tmp_path / "reports" / "rapport_qualite.md")


def test_pipeline_idempotent(tmp_path):
    """Relancer l'ETL deux fois donne exactement le même résultat."""
    raw = fabriquer_dossier_raw(tmp_path)
    lancer(tmp_path, raw)
    avant = {t: compter(tmp_path, t) for t in ["match", "lineup", "event", "player_match"]}
    lancer(tmp_path, raw)
    apres = {t: compter(tmp_path, t) for t in ["match", "lineup", "event", "player_match"]}
    assert avant == apres


def test_pipeline_rejette_et_continue(tmp_path):
    """Un mauvais match et un mauvais événement sont écartés, le reste est chargé."""
    raw = fabriquer_dossier_raw(tmp_path, matchs=[un_match(), un_match(match_id=2, dom=30, ext=40, score_dom=-3)])
    evenements = json.load(open(os.path.join(raw, "events", "1.json")))
    evenements.append(un_evenement("e5", 5, "Pass", 10, 100, 200))          # minute 200 : impossible
    evenements.append(copy.deepcopy(evenements[1]))                        # doublon de e2
    ecrire(os.path.join(raw, "events", "1.json"), evenements)

    resultats = lancer(tmp_path, raw)
    raisons = [r for (_, _, _, r) in resultats["rejets"]]
    assert "score négatif" in raisons
    assert "minute hors domaine" in raisons
    assert "événement en double" in raisons
    assert compter(tmp_path, "match") == 1
    assert compter(tmp_path, "event") == 4


def test_pipeline_fichier_events_vide(tmp_path):
    raw = fabriquer_dossier_raw(tmp_path)
    open(os.path.join(raw, "events", "1.json"), "w").close()    # fichier vide
    resultats = lancer(tmp_path, raw)
    assert ("events/1.json", "fichier vide") in resultats["fichiers_ignores"]
    assert compter(tmp_path, "event") == 0


def test_pipeline_liste_matchs_vide(tmp_path):
    raw = fabriquer_dossier_raw(tmp_path)
    ecrire(os.path.join(raw, "matches", "7_27.json"), [])
    with pytest.raises(RuntimeError):
        lancer(tmp_path, raw)


def test_pipeline_detecte_incoherence_de_score(tmp_path):
    """Le score dit 3-0 mais les événements ne montrent qu'un but : on doit le signaler."""
    raw = fabriquer_dossier_raw(tmp_path, matchs=[un_match(score_dom=3)])
    resultats = lancer(tmp_path, raw)
    assert len(resultats["incoherences"]) == 1


def test_pipeline_matchs_manquants(tmp_path):
    """Avec 2 équipes, on attend 2 matchs (aller et retour) : il en manque 1."""
    raw = fabriquer_dossier_raw(tmp_path)
    resultats = lancer(tmp_path, raw)
    assert resultats["matchs_manquants"] == ["Equipe 20 - Equipe 10"]
