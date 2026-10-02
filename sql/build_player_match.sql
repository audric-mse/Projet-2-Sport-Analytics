-- build_player_match.sql : calcule les stats de chaque joueur dans chaque match
-- à partir des tables lineup (minutes) et event (actions).

DELETE FROM player_match;

INSERT INTO player_match
    (match_id, player_id, team_id, minutes_played,
     shots, goals, xg, passes, passes_completed, assists)
SELECT
    l.match_id,
    l.player_id,
    l.team_id,
    l.minutes_played,
    COALESCE(SUM(CASE WHEN e.type = 'Shot' THEN 1 END), 0)                          AS shots,
    -- buts = tirs au but (penalties inclus ; pas de tirs au but de fin de match en championnat)
    COALESCE(SUM(CASE WHEN e.type = 'Shot' AND e.outcome = 'Goal' THEN 1 END), 0)   AS goals,
    COALESCE(SUM(CASE WHEN e.type = 'Shot' THEN e.xg END), 0)                       AS xg,
    COALESCE(SUM(CASE WHEN e.type = 'Pass' THEN 1 END), 0)                          AS passes,
    -- convention StatsBomb : une passe sans "outcome" est une passe réussie
    COALESCE(SUM(CASE WHEN e.type = 'Pass' AND e.outcome IS NULL THEN 1 END), 0)    AS passes_completed,
    COALESCE(SUM(e.is_goal_assist), 0)                                              AS assists
FROM lineup l
LEFT JOIN event e
       ON e.match_id = l.match_id
      AND e.player_id = l.player_id
GROUP BY l.match_id, l.player_id;
