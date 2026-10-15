"""Modifica delle partite e gestione dei risultati con i relativi marcatori."""

from collections import Counter
from uuid import UUID

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.match import (
    KNOCKOUT_PHASES,
    Fase,
    Marcatore,
    Match,
    MatchOut,
    MatchUpdate,
    ResultIn,
)
from app.repositories.base import DataStore
from app.services.goals import recalculate_goals
from app.services.schedule_service import ScheduleService
from app.services.views import match_out

# Partite che dipendono dall'esito delle semifinali.
FINALS = {Fase.FINALE_1_2, Fase.FINALE_3_4}


class MatchService:
    """Aggiornamento di data/giornata/squadre e inserimento o annullamento dei risultati.

    Ogni cambio di risultato ricalcola i goal dei giocatori coinvolti e
    riallinea la fase finale (ScheduleService.sync_final_phase).
    """

    def __init__(self, store: DataStore, schedule: ScheduleService):
        self.store = store
        self.schedule = schedule

    def _get(self, match_id: UUID) -> Match:
        match = self.store.matches.get(match_id)
        if match is None:
            raise NotFoundError("Partita non trovata")
        return match

    def get(self, match_id: UUID) -> MatchOut:
        """Partita arricchita con nomi di squadre e marcatori."""
        match = self._get(match_id)
        teams = {t.id: t for t in self.store.teams.list()}
        players = {p.id: p for p in self.store.players.list()}
        return match_out(match, teams, players)

    # --- Modifica dati partita ---

    def update(self, match_id: UUID, data: MatchUpdate) -> MatchOut:
        """Aggiorna solo i campi presenti nel body (semantica PATCH).

        Regole: nella fase finale si cambia solo `data_ora`; le squadre di una
        partita giocata non si cambiano; due squadre si affrontano una sola volta
        nel girone; il girone resta prima della fase finale; una squadra non gioca
        due volte nella stessa giornata.
        """
        # model_fields_set distingue "campo assente" da "campo esplicitamente null".
        fields = data.model_fields_set
        with self.store.transaction():
            match = self._get(match_id)
            all_matches = self.store.matches.list()
            changes: dict = {}

            if "data_ora" in fields:
                changes["data_ora"] = data.data_ora

            teams_changed = {"squadra_casa_id", "squadra_trasferta_id"} & fields
            if "giornata" in fields and data.giornata is None:
                raise ValidationError("La giornata è obbligatoria")
            day_changed = "giornata" in fields and data.giornata != match.giornata

            if (teams_changed or day_changed) and match.fase in KNOCKOUT_PHASES:
                raise ValidationError(
                    "Squadre e giornata della fase finale sono determinate dalla classifica: "
                    "si può modificare solo data e ora"
                )

            home = data.squadra_casa_id if "squadra_casa_id" in fields else match.squadra_casa_id
            away = data.squadra_trasferta_id if "squadra_trasferta_id" in fields else match.squadra_trasferta_id
            day = data.giornata if day_changed else match.giornata

            if teams_changed and (home, away) != (match.squadra_casa_id, match.squadra_trasferta_id):
                if match.giocata:
                    raise ConflictError(
                        "Non si possono cambiare le squadre di una partita già giocata: "
                        "annulla prima il risultato"
                    )
                if home is None or away is None:
                    raise ValidationError("Entrambe le squadre sono obbligatorie")
                if home == away:
                    raise ValidationError("Una squadra non può giocare contro se stessa")
                for tid in (home, away):
                    if self.store.teams.get(tid) is None:
                        raise ValidationError("Squadra inesistente")
                pair = {home, away}
                if any(
                    m.id != match.id and m.fase == Fase.GIRONE
                    and {m.squadra_casa_id, m.squadra_trasferta_id} == pair
                    for m in all_matches
                ):
                    raise ConflictError("Queste due squadre si affrontano già in un'altra partita del girone")
                changes["squadra_casa_id"], changes["squadra_trasferta_id"] = home, away

            if day_changed:
                knockout_days = [m.giornata for m in all_matches if m.fase in KNOCKOUT_PHASES]
                if knockout_days and day >= min(knockout_days):
                    raise ValidationError(
                        f"Le partite del girone devono stare prima della fase finale (giornata {min(knockout_days)})"
                    )
                changes["giornata"] = day

            # Si ricontrolla anche quando cambia solo la giornata: la partita
            # spostata non deve sovrapporsi ad altre delle stesse squadre.
            if teams_changed or day_changed:
                busy = [
                    m for m in all_matches
                    if m.id != match.id and m.giornata == day and (m.involves(home) or m.involves(away))
                ]
                if busy:
                    raise ConflictError(f"Una delle due squadre gioca già nella giornata {day}")

            if changes:
                self.store.matches.update(match.model_copy(update=changes))
        return self.get(match_id)

    # --- Risultati ---

    def _check_dependents(self, match: Match) -> None:
        """Vieta di cambiare un risultato da cui dipendono partite successive già giocate."""
        if match.fase == Fase.GIRONE:
            dependent = KNOCKOUT_PHASES
        elif match.fase == Fase.SEMIFINALE:
            dependent = FINALS
        else:
            return
        if any(m.fase in dependent and m.giocata for m in self.store.matches.list()):
            raise ConflictError(
                "La fase successiva ha già dei risultati che dipendono da questa partita: "
                "annullali prima di modificare questo risultato"
            )

    def _build_scorers(self, match: Match, data: ResultIn) -> list[Marcatore]:
        """Valida i marcatori in ingresso e li converte in voci persistibili.

        - ogni giocatore compare una sola volta (i suoi goal vanno sommati);
        - al più una voce di autogol per squadra beneficiaria, che deve essere
          una delle due squadre in campo;
        - il giocatore deve appartenere a una delle due squadre (oggi o, se è
          stato trasferito, al momento del precedente inserimento);
        - per ciascuna squadra la somma dei goal deve coincidere col punteggio.
        La squadra di ogni marcatore viene fissata qui, una volta per tutte.
        """
        ids = [mk.giocatore_id for mk in data.marcatori if not mk.autogol]
        if len(ids) != len(set(ids)):
            raise ValidationError("Lo stesso giocatore compare più volte tra i marcatori: somma i suoi goal")
        own_goal_teams = [mk.squadra_id for mk in data.marcatori if mk.autogol]
        if len(own_goal_teams) != len(set(own_goal_teams)):
            raise ValidationError("Gli autogol a favore della stessa squadra vanno indicati in un'unica voce")

        teams_in_match = (match.squadra_casa_id, match.squadra_trasferta_id)
        # Se un giocatore ha cambiato squadra dopo aver segnato, la squadra
        # registrata in precedenza per questa partita resta valida.
        previous = {mk.giocatore_id: mk.squadra_id for mk in match.marcatori if not mk.autogol}

        scorers: list[Marcatore] = []
        for mk in data.marcatori:
            if mk.autogol:
                if mk.squadra_id not in teams_in_match:
                    raise ValidationError("L'autogol deve essere assegnato a una delle due squadre della partita")
                scorers.append(Marcatore(giocatore_id=None, squadra_id=mk.squadra_id, goal=mk.goal, autogol=True))
                continue
            player = self.store.players.get(mk.giocatore_id)
            if player is None:
                raise ValidationError(f"Giocatore {mk.giocatore_id} inesistente")
            if player.squadra_id in teams_in_match:
                squadra = player.squadra_id
            elif previous.get(player.id) in teams_in_match:
                squadra = previous[player.id]
            else:
                raise ValidationError(
                    f"{player.nome} {player.cognome} non appartiene a nessuna delle due squadre"
                )
            scorers.append(Marcatore(giocatore_id=player.id, squadra_id=squadra, goal=mk.goal))

        per_team = Counter()
        for s in scorers:
            per_team[s.squadra_id] += s.goal
        # Il controllo include gli autogol, conteggiati per la squadra che ne beneficia.
        for team_id, score, label in (
            (match.squadra_casa_id, data.gol_casa, "casa"),
            (match.squadra_trasferta_id, data.gol_trasferta, "trasferta"),
        ):
            if per_team[team_id] != score:
                raise ValidationError(
                    f"I goal dei marcatori (autogol compresi) della squadra in {label} ({per_team[team_id]}) "
                    f"non coincidono con il punteggio ({score})"
                )
        return scorers

    def _penalty_winner(self, match: Match, data: ResultIn) -> UUID | None:
        """Vincitore ai rigori da salvare.

        Vietato nel girone; nella fase finale obbligatorio in caso di pareggio
        e ignorato (salvato come None) se il punteggio decide già la partita.
        """
        if match.fase == Fase.GIRONE:
            if data.vincitore_rigori_id is not None:
                raise ValidationError("Nel girone non si tirano i rigori: il pareggio è ammesso")
            return None
        if data.gol_casa != data.gol_trasferta:
            return None  # vincitore già determinato dal punteggio
        if data.vincitore_rigori_id not in (match.squadra_casa_id, match.squadra_trasferta_id):
            raise ValidationError(
                "Partita della fase finale in parità: indica la squadra vincitrice ai rigori"
            )
        return data.vincitore_rigori_id

    def set_result(self, match_id: UUID, data: ResultIn) -> MatchOut:
        """Inserisce o sostituisce il risultato di una partita."""
        with self.store.transaction():
            match = self._get(match_id)
            scorers = self._build_scorers(match, data)
            penalty_winner = self._penalty_winner(match, data)
            self._check_dependents(match)

            # Vecchi e nuovi marcatori: chi esce dal tabellino deve perdere i goal.
            involved = {mk.giocatore_id for mk in [*match.marcatori, *scorers] if mk.giocatore_id}
            self.store.matches.update(
                match.model_copy(
                    update={
                        "gol_casa": data.gol_casa,
                        "gol_trasferta": data.gol_trasferta,
                        "marcatori": scorers,
                        "vincitore_rigori_id": penalty_winner,
                        "giocata": True,
                    }
                )
            )
            recalculate_goals(self.store, involved)
            self.schedule.sync_final_phase()
        return self.get(match_id)

    def clear_result(self, match_id: UUID) -> MatchOut:
        """Riporta la partita a "non giocata"; idempotente se già non giocata."""
        with self.store.transaction():
            match = self._get(match_id)
            if not match.giocata:
                return self.get(match_id)
            self._check_dependents(match)
            involved = {mk.giocatore_id for mk in match.marcatori if mk.giocatore_id}
            self.store.matches.update(
                match.model_copy(
                    update={
                        "gol_casa": None,
                        "gol_trasferta": None,
                        "marcatori": [],
                        "vincitore_rigori_id": None,
                        "giocata": False,
                    }
                )
            )
            recalculate_goals(self.store, involved)
            self.schedule.sync_final_phase()
        return self.get(match_id)
