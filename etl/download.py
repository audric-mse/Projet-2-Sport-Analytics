"""
download.py - télécharge les données brutes StatsBomb (Open Data) dans data/raw/

Source : https://github.com/statsbomb/open-data
Données : StatsBomb (à citer si je publie quelque chose, voir README)

Utilisation :
    python etl/download.py
"""
import json
import os
import time
import urllib.request

# --- Réglages : la saison que j'ai choisie ---
COMPETITION_ID = 7      # Ligue 1
SEASON_ID = 27          # 2015/2016

BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data/"
RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")


def telecharger(url, chemin, essais=3):
    """Télécharge un fichier. Si le fichier existe déjà, on ne le retélécharge pas."""
    if os.path.exists(chemin) and os.path.getsize(chemin) > 0:
        return False
    for essai in range(1, essais + 1):
        try:
            contenu = urllib.request.urlopen(url, timeout=60).read()
            with open(chemin, "wb") as f:
                f.write(contenu)
            return True
        except Exception as erreur:
            print(f"  erreur ({essai}/{essais}) pour {url} : {erreur}")
            time.sleep(2)
    print(f"  ABANDON : {url}")
    return False


def main():
    for sous_dossier in ["matches", "events", "lineups"]:
        os.makedirs(os.path.join(RAW_DIR, sous_dossier), exist_ok=True)

    # 1) la liste des compétitions
    telecharger(BASE_URL + "competitions.json", os.path.join(RAW_DIR, "competitions.json"))

    # 2) la liste des matchs de la saison
    chemin_matchs = os.path.join(RAW_DIR, "matches", f"{COMPETITION_ID}_{SEASON_ID}.json")
    telecharger(BASE_URL + f"matches/{COMPETITION_ID}/{SEASON_ID}.json", chemin_matchs)
    with open(chemin_matchs, encoding="utf-8") as f:
        matchs = json.load(f)
    print(len(matchs), "matchs à télécharger")

    # 3) pour chaque match : les événements et les compositions
    for i, m in enumerate(matchs, start=1):
        match_id = m["match_id"]
        telecharger(BASE_URL + f"events/{match_id}.json",
                    os.path.join(RAW_DIR, "events", f"{match_id}.json"))
        telecharger(BASE_URL + f"lineups/{match_id}.json",
                    os.path.join(RAW_DIR, "lineups", f"{match_id}.json"))
        if i % 25 == 0:
            print(f"  {i}/{len(matchs)} matchs traités")
    print("Terminé.")


if __name__ == "__main__":
    main()
