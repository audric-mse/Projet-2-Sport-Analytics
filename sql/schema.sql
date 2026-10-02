-- schema.sql : modèle de la base Sport Analytics (SQLite)
-- Source des données : StatsBomb Open Data (Ligue 1 2015/2016)

PRAGMA foreign_keys = ON;

-- ---------- Référentiels ----------

CREATE TABLE competition (
    competition_id  INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    country         TEXT NOT NULL
);

-- Attention : season_id tout seul n'est PAS unique dans les données
-- (la saison 27 existe pour plusieurs compétitions), donc clé composée.
CREATE TABLE season (
    competition_id  INTEGER NOT NULL REFERENCES competition(competition_id),
    season_id       INTEGER NOT NULL,
    label           TEXT NOT NULL,
    PRIMARY KEY (competition_id, season_id)
);

CREATE TABLE team (
    team_id  INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE
);

CREATE TABLE player (
    player_id  INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    nickname   TEXT,
    country    TEXT
);

-- ---------- Matchs ----------

CREATE TABLE match (
    match_id         INTEGER PRIMARY KEY,
    competition_id   INTEGER NOT NULL,
    season_id        INTEGER NOT NULL,
    match_date       TEXT NOT NULL,          -- format AAAA-MM-JJ
    kick_off         TEXT,
    match_week       INTEGER CHECK (match_week >= 1),
    home_team_id     INTEGER NOT NULL REFERENCES team(team_id),
    away_team_id     INTEGER NOT NULL REFERENCES team(team_id),
    home_score       INTEGER NOT NULL CHECK (home_score >= 0),
    away_score       INTEGER NOT NULL CHECK (away_score >= 0),
    FOREIGN KEY (competition_id, season_id) REFERENCES season(competition_id, season_id),
    CHECK (home_team_id <> away_team_id),
    -- en championnat, une même rencontre (domicile, extérieur) n'a lieu qu'une fois
    UNIQUE (competition_id, season_id, home_team_id, away_team_id)
);

-- Qui a joué quel match, et pendant combien de temps
CREATE TABLE lineup (
    match_id        INTEGER NOT NULL REFERENCES match(match_id),
    team_id         INTEGER NOT NULL REFERENCES team(team_id),
    player_id       INTEGER NOT NULL REFERENCES player(player_id),
    jersey_number   INTEGER,
    start_minute    REAL NOT NULL CHECK (start_minute >= 0),
    end_minute      REAL NOT NULL,
    minutes_played  REAL NOT NULL CHECK (minutes_played >= 0 AND minutes_played <= 130),
    PRIMARY KEY (match_id, player_id),
    CHECK (end_minute >= start_minute)
);

-- ---------- Événements (une ligne = une action dans un match) ----------

CREATE TABLE event (
    event_id        TEXT PRIMARY KEY,
    match_id        INTEGER NOT NULL REFERENCES match(match_id),
    event_index     INTEGER NOT NULL,
    period          INTEGER NOT NULL CHECK (period BETWEEN 1 AND 5),
    minute          INTEGER NOT NULL CHECK (minute BETWEEN 0 AND 130),
    second          INTEGER NOT NULL CHECK (second BETWEEN 0 AND 59),
    type            TEXT NOT NULL,           -- Pass, Shot, Carry, ...
    team_id         INTEGER NOT NULL REFERENCES team(team_id),
    player_id       INTEGER REFERENCES player(player_id),   -- NULL normal pour certains types
    position        TEXT,
    x               REAL CHECK (x BETWEEN 0 AND 120),       -- terrain 120 x 80
    y               REAL CHECK (y BETWEEN 0 AND 80),
    outcome         TEXT,   -- tirs : Goal, Saved... ; passes : NULL = passe réussie
    xg              REAL CHECK (xg BETWEEN 0 AND 1),        -- seulement pour les tirs
    is_goal_assist  INTEGER NOT NULL DEFAULT 0 CHECK (is_goal_assist IN (0, 1)),
    UNIQUE (match_id, event_index)
);

-- ---------- Table calculée : une ligne par joueur et par match ----------
-- (remplie par sql/build_player_match.sql après le chargement)

CREATE TABLE player_match (
    match_id          INTEGER NOT NULL REFERENCES match(match_id),
    player_id         INTEGER NOT NULL REFERENCES player(player_id),
    team_id           INTEGER NOT NULL REFERENCES team(team_id),
    minutes_played    REAL NOT NULL,
    shots             INTEGER NOT NULL,
    goals             INTEGER NOT NULL,
    xg                REAL NOT NULL,
    passes            INTEGER NOT NULL,
    passes_completed  INTEGER NOT NULL,
    assists           INTEGER NOT NULL,
    PRIMARY KEY (match_id, player_id)
);

-- ---------- Index ----------
CREATE INDEX idx_event_match_player ON event(match_id, player_id);
CREATE INDEX idx_event_type         ON event(type);
CREATE INDEX idx_match_date         ON match(match_date);
CREATE INDEX idx_match_home         ON match(home_team_id);
CREATE INDEX idx_match_away         ON match(away_team_id);
CREATE INDEX idx_lineup_player      ON lineup(player_id);
CREATE INDEX idx_pm_player          ON player_match(player_id);
