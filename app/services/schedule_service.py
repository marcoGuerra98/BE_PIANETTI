"""Calendario: generazione del girone all'italiana e gestione automatica della fase finale."""

import random
from collections import defaultdict
from uuid import UUID

from app.errors import ConflictError, ValidationError
from app.models.match import (
    KNOCKOUT_PHASES,
    Fase,
    GiornataOut,
    Match,
    ScheduleOut,
    TeamRef,
)
from app.repositories.base import DataStore
from app.services.goals import recalculate_goals
from app.services.standings_service import compute_group_standings
from app.services.views import match_out

# Minimo per il girone e anche numero di squadre ammesse alla fase finale.
MIN_TEAMS = 4


def _plays_home(i: int, j: int, n: int) -> bool:
    """Decide se la squadra di indice i gioca in casa contro j.

    Con m squadre "dispari" (m = n se n dispari, altrimenti n - 1) ognuna gioca in
    casa contro le (m-1)/2 squadre che la seguono in senso circolare; l'eventuale
    n-esima squadra alterna. Ogni squadra ha così un numero di partite in casa che
    differisce al massimo di 1 dalle altre.
    """
    m = n if n % 2 else n - 1
    # Tra le prime m squadre: i gioca in casa se j la segue di 1..(m-1)/2
    # posizioni sul cerchio di m elementi (relazione antisimmetrica).
    if i < m and j < m:
        return 1 <= (j - i) % m <= (m - 1) // 2
    if j >= m:  # j è la squadra extra
        return i % 2 == 0
    # i è la squadra extra: vale il contrario del caso precedente.
    return not _plays_home(j, i, n)


def round_robin(team_ids: list[UUID]) -> list[list[tuple[UUID, UUID]]]:
    """Girone all'italiana di sola andata (metodo del cerchio).

    Con un numero dispari di squadre si aggiunge un "riposo" fittizio.
    Restituisce una lista di giornate, ognuna con le coppie (casa, trasferta).
    """
    n = len(team_ids)
    slots: list[int | None] = list(range(n))
    if n % 2:
        slots.append(None)
    size = len(slots)
    rounds = []
    for _ in range(size - 1):
        pairs = []
        # Accoppiamento a specchio: primo con ultimo, secondo con penultimo, ...
        for k in range(size // 2):
            a, b = slots[k], slots[size - 1 - k]
            if a is None or b is None:
                continue  # la squadra abbinata al "riposo" non gioca
            # Il campo di casa dipende solo dalla coppia, non dalla giornata.
            if not _plays_home(a, b, n):
                a, b = b, a
            pairs.append((team_ids[a], team_ids[b]))
        rounds.append(pairs)
        # Rotazione del cerchio: il primo slot resta fermo, gli altri scorrono di uno.
        slots = [slots[0], slots[-1], *slots[1:-1]]
    return rounds


class ScheduleService:
    """Generazione, lettura ed eliminazione del calendario e sincronizzazione della fase finale.

    `rng` è iniettabile per avere calendari riproducibili (seed e test).
    """

    def __init__(self, store: DataStore, rng: random.Random | None = None):
        self.store = store
        self.rng = rng or random.Random()

    # --- Lettura ---

    def get_schedule(self) -> ScheduleOut:
        """Calendario raggruppato per giornata, con le squadre a riposo nel girone.

        Nella giornata le partite sono ordinate per data/ora (quelle senza data in fondo).
        """
        matches = self.store.matches.list()
        teams = {t.id: t for t in self.store.teams.list()}
        players = {p.id: p for p in self.store.players.list()}

        by_day: dict[int, list[Match]] = defaultdict(list)
        for m in matches:
            by_day[m.giornata].append(m)

        # Le squadre del girone sono quelle presenti nelle sue partite, non
        # tutte le squadre esistenti (una creata dopo non risulta a riposo).
        group_teams = {
            tid
            for m in matches
            if m.fase == Fase.GIRONE
            for tid in (m.squadra_casa_id, m.squadra_trasferta_id)
        }
        giornate = []
        for day in sorted(by_day):
            day_matches = sorted(
                by_day[day],
                key=lambda m: (m.data_ora is None, m.data_ora.isoformat() if m.data_ora else "", m.fase),
            )
            fase = day_matches[0].fase
            riposa = []
            if fase == Fase.GIRONE:
                playing = {t for m in day_matches for t in (m.squadra_casa_id, m.squadra_trasferta_id)}
                riposa = [
                    TeamRef(id=t.id, nome=t.nome, stemma=t.stemma)
                    for tid in group_teams - playing
                    if (t := teams.get(tid))
                ]
                riposa.sort(key=lambda t: t.nome.casefold())
            giornate.append(
                GiornataOut(
                    giornata=day,
                    fase=fase,
                    partite=[match_out(m, teams, players) for m in day_matches],
                    riposa=riposa,
                )
            )
        group = [m for m in matches if m.fase == Fase.GIRONE]
        return ScheduleOut(
            giornate=giornate,
            totale_partite=len(matches),
            partite_giocate=sum(m.giocata for m in matches),
            girone_completato=bool(group) and all(m.giocata for m in group),
        )

    # --- Generazione / eliminazione ---

    def _require_confirm_if_exists(self, confirm: bool, action: str) -> None:
        """409 se esiste già un calendario e l'operazione non è stata confermata."""
        matches = self.store.matches.list()
        if matches and not confirm:
            played = sum(m.giocata for m in matches)
            msg = f"Esiste già un calendario con {len(matches)} partite"
            if played:
                msg += f", di cui {played} giocate (i loro risultati e i goal verranno persi)"
            raise ConflictError(
                f"{msg}. Ripeti con confirm=true per {action}.",
                details={"partite": len(matches), "partite_giocate": played},
            )

    def _clear(self) -> None:
        """Elimina tutte le partite; se c'erano risultati azzera i goal dei giocatori."""
        matches = self.store.matches.list()
        had_results = any(m.giocata for m in matches)
        self.store.matches.delete_many(m.id for m in matches)
        if had_results:
            recalculate_goals(self.store)

    def generate(self, confirm: bool = False, shuffle: bool = True) -> ScheduleOut:
        """Genera il girone di sola andata con tutte le squadre esistenti.

        Sostituisce l'eventuale calendario esistente solo con `confirm=True`.
        `shuffle` mescola l'ordine delle squadre (quindi abbinamenti e campo).
        """
        with self.store.transaction():
            teams = self.store.teams.list()
            if len(teams) < MIN_TEAMS:
                raise ValidationError(
                    f"Servono almeno {MIN_TEAMS} squadre per generare il calendario "
                    f"(girone + fase finale tra le prime quattro)"
                )
            self._require_confirm_if_exists(confirm, "rigenerarlo")
            self._clear()

            ids = [t.id for t in teams]
            if shuffle:
                self.rng.shuffle(ids)
            for day, pairs in enumerate(round_robin(ids), start=1):
                for home, away in pairs:
                    self.store.matches.add(
                        Match(giornata=day, fase=Fase.GIRONE, squadra_casa_id=home, squadra_trasferta_id=away)
                    )
        return self.get_schedule()

    def delete(self, confirm: bool = False) -> None:
        """Elimina l'intero calendario (richiede confirm se esistono partite)."""
        with self.store.transaction():
            self._require_confirm_if_exists(confirm, "eliminarlo")
            self._clear()

    # --- Fase finale ---

    def sync_final_phase(self) -> None:
        """Allinea la fase finale allo stato del girone.

        - Girone non completo: si rimuovono le partite della fase finale non giocate.
        - Girone completo: semifinali 1ª-4ª e 2ª-3ª secondo la classifica
          (se esistono già e non sono giocate, si aggiornano le squadre
          mantenendo date e orari).
        - Semifinali entrambe giocate: finale 1°/2° tra le vincitrici e
          finale 3°/4° tra le perdenti.

        Va chiamata all'interno di una transazione, dopo ogni cambio di risultato.
        """
        matches = self.store.matches.list()
        group = [m for m in matches if m.fase == Fase.GIRONE]
        knockout = [m for m in matches if m.fase in KNOCKOUT_PHASES]
        if not group:
            return

        # Le partite della fase finale già giocate non si toccano mai qui:
        # MatchService._check_dependents impedisce che diventino incoerenti.
        if not all(m.giocata for m in group):
            self.store.matches.delete_many(m.id for m in knockout if not m.giocata)
            return

        standings = compute_group_standings(self.store.teams.list(), group)
        if len(standings) < MIN_TEAMS:
            return
        seeds = [r.squadra_id for r in standings[:MIN_TEAMS]]
        semi_day = max(m.giornata for m in group) + 1
        expected_semis = [(seeds[0], seeds[3]), (seeds[1], seeds[2])]

        semis = [m for m in knockout if m.fase == Fase.SEMIFINALE]
        # Semifinali assenti: si creano. Presenti ma non giocate: si riallineano
        # alla classifica attuale (un risultato del girone può essere cambiato).
        if not semis:
            semis = [
                self.store.matches.add(
                    Match(giornata=semi_day, fase=Fase.SEMIFINALE, squadra_casa_id=h, squadra_trasferta_id=a)
                )
                for h, a in expected_semis
            ]
        elif not any(m.giocata for m in semis):
            current = {(m.squadra_casa_id, m.squadra_trasferta_id) for m in semis}
            if current != set(expected_semis):
                updated = [
                    m.model_copy(update={"squadra_casa_id": h, "squadra_trasferta_id": a})
                    for m, (h, a) in zip(semis, expected_semis)
                ]
                self.store.matches.update_many(updated)
                semis = updated

        finals = [m for m in knockout if m.fase in (Fase.FINALE_1_2, Fase.FINALE_3_4)]
        # Finali solo con entrambe le semifinali giocate; altrimenti si
        # rimuovono quelle non giocate eventualmente rimaste.
        if len(semis) != 2 or not all(m.giocata for m in semis):
            self.store.matches.delete_many(m.id for m in finals if not m.giocata)
            return

        # Semifinale "A" è quella della prima classificata: la sua vincitrice gioca in casa.
        semi_a = next((m for m in semis if m.involves(seeds[0])), semis[0])
        semi_b = semis[1] if semi_a is semis[0] else semis[0]
        expected_finals = {
            Fase.FINALE_1_2: (semi_a.winner_id(), semi_b.winner_id()),
            Fase.FINALE_3_4: (semi_a.loser_id(), semi_b.loser_id()),
        }
        final_day = max(m.giornata for m in semis) + 1
        for fase, (home, away) in expected_finals.items():
            existing = next((m for m in finals if m.fase == fase), None)
            if existing is None:
                self.store.matches.add(
                    Match(giornata=final_day, fase=fase, squadra_casa_id=home, squadra_trasferta_id=away)
                )
            elif not existing.giocata and (existing.squadra_casa_id, existing.squadra_trasferta_id) != (home, away):
                self.store.matches.update(
                    existing.model_copy(update={"squadra_casa_id": home, "squadra_trasferta_id": away})
                )
