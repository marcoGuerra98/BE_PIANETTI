"""Popola i dati di esempio: 8 squadre, 12 giocatori ciascuna, calendario e
alcune giornate già giocate (con marcatori coerenti con i punteggi).

Uso:  python scripts/seed.py [--giornate N] [--force]
  --giornate N   numero di giornate da simulare (default 4; 7 = girone completo)
  --force        sovrascrive i dati esistenti (giocatori, squadre, partite)
"""

import argparse
import random
import sys

from _common import get_settings  # imposta anche sys.path

from app.main import build_services
from app.models.match import Fase, MarcatoreIn, ResultIn
from app.models.player import PlayerCreate, Ruolo
from app.models.team import TeamCreate

TEAMS = [
    "Atletico Pianetti", "Real Borgo", "Sporting Collina", "Union Lago",
    "Dinamo Valle", "Olimpia Porto", "Virtus Castello", "Fortitudo Mare",
]
NOMI = [
    "Marco", "Luca", "Andrea", "Matteo", "Lorenzo", "Davide", "Simone", "Federico", "Alessandro",
    "Gabriele", "Riccardo", "Tommaso", "Giorgio", "Stefano", "Nicola", "Paolo", "Daniele", "Fabio",
    "Emanuele", "Michele", "Antonio", "Francesco", "Pietro", "Giacomo", "Leonardo", "Edoardo",
]
COGNOMI = [
    "Rossi", "Russo", "Ferrari", "Esposito", "Bianchi", "Romano", "Colombo", "Ricci", "Marino",
    "Greco", "Bruno", "Gallo", "Conti", "De Luca", "Mancini", "Costa", "Giordano", "Rizzo",
    "Lombardi", "Moretti", "Barbieri", "Fontana", "Santoro", "Mariani", "Rinaldi", "Caruso",
    "Ferrara", "Galli", "Martini", "Leone", "Longo", "Gentile", "Martinelli", "Vitale", "Serra",
    "Coppola", "De Santis", "D'Angelo", "Marchetti", "Parisi", "Villa", "Conte", "Ferraro", "Fabbri",
]
# Rosa tipo di 12 giocatori e peso di ciascun ruolo nella scelta dei marcatori.
ROSTER = [Ruolo.POR] * 2 + [Ruolo.DIF] * 4 + [Ruolo.CEN] * 3 + [Ruolo.ATT] * 3
SCORER_WEIGHT = {Ruolo.POR: 0, Ruolo.DIF: 1, Ruolo.CEN: 3, Ruolo.ATT: 7}
DESCRIZIONI = {
    Ruolo.POR: "Reattivo tra i pali, bravo nelle uscite alte.",
    Ruolo.DIF: "Difensore solido, forte nel gioco aereo e negli anticipi.",
    Ruolo.CEN: "Centrocampista dinamico, ottima visione di gioco.",
    Ruolo.ATT: "Attaccante rapido con un gran fiuto del gol.",
}


def main() -> int:
    """Rigenera i dati di esempio; `--seed` rende il risultato riproducibile."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--giornate", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    svc = build_services(get_settings())
    store = svc.store

    if (store.teams.list() or store.players.list()) and not args.force:
        print("Ci sono già dei dati. Usa --force per sovrascriverli.")
        return 1

    # La pulizia usa direttamente i repository; la creazione passa invece dai
    # service, così i dati rispettano le stesse validazioni dell'API.
    with store.transaction():
        store.matches.delete_many(m.id for m in store.matches.list())
        store.players.delete_many(p.id for p in store.players.list())
        store.teams.delete_many(t.id for t in store.teams.list())

    names = rng.sample([(n, c) for n in NOMI for c in COGNOMI], len(TEAMS) * len(ROSTER) + 2)
    roster: dict = {}
    for team_name in TEAMS:
        team = svc.teams.create(TeamCreate(nome=team_name))
        roster[team.id] = []
        for ruolo in ROSTER:
            nome, cognome = names.pop()
            roster[team.id].append(
                svc.players.create(
                    PlayerCreate(
                        nome=nome, cognome=cognome, ruolo=ruolo, squadra_id=team.id,
                        overall=max(45, min(95, int(rng.gauss(72, 9)))),
                        descrizione=DESCRIZIONI[ruolo],
                    )
                )
            )
    # qualche svincolato
    for ruolo in (Ruolo.CEN, Ruolo.ATT):
        nome, cognome = names.pop()
        svc.players.create(PlayerCreate(nome=nome, cognome=cognome, ruolo=ruolo, overall=60))

    svc.schedule.rng = rng
    schedule = svc.schedule.generate(confirm=True)

    def scorers_for(team_id, goals):
        """Distribuisce `goals` tra i giocatori della squadra, con qualche autogol avversario."""
        players = roster[team_id]
        weights = [SCORER_WEIGHT[p.ruolo] for p in players]
        picks: dict = {}
        own_goals = 0
        for _ in range(goals):
            if rng.random() < 0.06:  # ogni tanto un autogol avversario
                own_goals += 1
                continue
            p = rng.choices(players, weights)[0]
            picks[p.id] = picks.get(p.id, 0) + 1
        result = [MarcatoreIn(giocatore_id=pid, goal=g) for pid, g in picks.items()]
        if own_goals:
            result.append(MarcatoreIn(autogol=True, squadra_id=team_id, goal=own_goals))
        return result

    played = 0
    # Solo partite del girone: la fase finale si genera da sola a girone completato.
    for g in schedule.giornate[: args.giornate]:
        for m in g.partite:
            if m.fase != Fase.GIRONE:
                continue
            gc, gt = rng.choice([0, 1, 1, 2, 2, 3, 4]), rng.choice([0, 0, 1, 1, 2, 3])
            svc.matches.set_result(
                m.id,
                ResultIn(
                    gol_casa=gc, gol_trasferta=gt,
                    marcatori=scorers_for(m.squadra_casa_id, gc) + scorers_for(m.squadra_trasferta_id, gt),
                ),
            )
            played += 1

    print(
        f"Creati {len(TEAMS)} squadre, {len(store.players.list())} giocatori, "
        f"{len(store.matches.list())} partite ({played} giocate)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
