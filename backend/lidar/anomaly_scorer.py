"""
Ocena "typowosci" wykrytego klastru metoda nienadzorowanej detekcji
anomalii (Isolation Forest) - bez potrzeby recznie oznaczonych danych
treningowych. Model uczy sie NA ZYWO z historii ostatnio widzianych
klastrow (zakladajac, ze wiekszosc klastrow w typowej scenie to prawdziwe
obiekty, a "dziwne" - np. artefakty klastrowania, szum na krawedzi
detekcji - sa relatywnie rzadkie) i ocenia kazdy nowy klaster wzgledem
tego, co widzial dotychczas.

WAZNE - czym to NIE jest: to NIE jest klasyfikator "realna przeszkoda vs
szum" (do tego trzeba etykiet, ktorych nie mamy - patrz brainstorming w
rozmowie). To miernik "jak bardzo ten klaster odstaje (w przestrzeni cech)
od typowych klastrow widzianych do tej pory w tej scenie". Niska ocena
moze rownie dobrze oznaczac szum, jak i rzadki, ale realny obiekt (np.
jedyny stojacy kubek na inaczej pustym stole) - to jeden dodatkowy sygnal
do wizualizacji/decyzji czlowieka, nie wyrocznia.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Sequence

import numpy as np
from sklearn.ensemble import IsolationForest

if TYPE_CHECKING:
    from .obstacle_clustering import ObstacleCluster


@dataclass
class FittedAnomalyModel:
    """Las izolacyjny RAZEM z rozkladem jego surowych ocen na danych
    treningowych - ten drugi sluzy do kalibracji wyniku na [0,1] (patrz
    ClusterAnomalyScorer.score)."""

    forest: IsolationForest
    # Posortowane rosnaco surowe decision_function() na zbiorze treningowym.
    reference_scores: np.ndarray

FEATURE_NAMES = ["point_count", "diameter_m", "density", "mean_intensity", "intensity_std", "range_m"]

# Ponizej tylu przykladow w historii model NIE jest dopasowywany - Isolation
# Forest na garstce probek dawalby przypadkowe, niestabilne oceny zamiast
# sensownego obrazu "co jest typowe w tej scenie".
DEFAULT_MIN_HISTORY = 50
DEFAULT_MAX_HISTORY = 2000


def extract_features(cluster: "ObstacleCluster") -> np.ndarray:
    x_span = cluster.x_max - cluster.x_min
    y_span = cluster.y_max - cluster.y_min
    diameter_m = float(np.hypot(x_span, y_span))
    area = max(diameter_m**2, 1e-6)
    density = cluster.point_count / area
    range_m = float(np.hypot(cluster.centroid_x, cluster.centroid_y))
    return np.array(
        [
            cluster.point_count,
            diameter_m,
            density,
            cluster.mean_intensity,
            cluster.intensity_std,
            range_m,
        ],
        dtype=np.float64,
    )


class ClusterAnomalyScorer:
    def __init__(
        self,
        n_estimators: int = 100,
        min_history: int = DEFAULT_MIN_HISTORY,
        random_state: int = 0,
    ):
        self.n_estimators = n_estimators
        self.min_history = min_history
        self.random_state = random_state
        self._model: Optional[IsolationForest] = None
        self._fitted = False

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    def build_fitted_model(self, clusters: Sequence["ObstacleCluster"]) -> Optional[FittedAnomalyModel]:
        """
        Trenuje i zwraca NOWY model (nie modyfikuje stanu tej instancji) -
        celowo tak zaprojektowane, zeby dalo sie to bezpiecznie wywolac w
        tle (np. asyncio.to_thread) BEZ ryzyka wyscigu z rownolegle
        trwajacym score() na aktualnym self._model. Wywolujacy podmienia
        model dopiero po zakonczeniu, przez apply_fitted_model().

        Zwraca None, jesli historii jest za malo - IsolationForest na
        garstce probek dawalby przypadkowe, niestabilne oceny.

        UWAGA WYDAJNOSCIOWA: fit() na n_estimators=100 zmierzono na ~320ms
        na Raspberry Pi 5 (patrz brainstorming w rozmowie) - stanowczo za
        wolno, zeby wywolywac synchronicznie w petli obstacle_loop (budzet
        200ms/tick) bez blokowania event loop i ryzyka utraty datagramow
        UDP w tym oknie.
        """
        if len(clusters) < self.min_history:
            return None
        features = np.array([extract_features(c) for c in clusters])
        forest = IsolationForest(n_estimators=self.n_estimators, random_state=self.random_state)
        forest.fit(features)
        # Zapamietaj rozklad surowych ocen na danych treningowych - to on
        # kalibruje pozniejszy wynik na [0,1] (patrz score()). Liczone tu,
        # a nie w score(), bo to czesc treningu i ma sie wykonac w watku w
        # tle razem z fit().
        reference = np.sort(forest.decision_function(features))
        return FittedAnomalyModel(forest=forest, reference_scores=reference)

    def apply_fitted_model(self, model: FittedAnomalyModel) -> None:
        """Podmiana modelu - szybka, bezpieczna do wywolania synchronicznie
        w glownym watku/event loop (samo przypisanie referencji)."""
        self._model = model
        self._fitted = True

    def fit(self, clusters: Sequence["ObstacleCluster"]) -> bool:
        """
        Wygodny synchroniczny helper (fit+apply w jednym) - do uzytku w
        testach/prostych skryptach. W obstacle_loop (app.py) uzywana jest
        para build_fitted_model()+apply_fitted_model() z fit w tle, zeby
        NIE blokowac event loop - patrz docstring build_fitted_model.
        """
        model = self.build_fitted_model(clusters)
        if model is None:
            return False
        self.apply_fitted_model(model)
        return True

    def score(self, clusters: Sequence["ObstacleCluster"]) -> List[float]:
        """
        Zwraca liste ocen w [0, 1] - RANGA PERCENTYLOWA wzgledem ocen, jakie
        model wystawil wlasnym danym treningowym. 1.0 = bardziej typowy niz
        wszystko, co widzial; 0.0 = mniej typowy niz cokolwiek, co widzial.
        Jesli model nie jest jeszcze dopasowany, zwraca 0.5 (neutralne
        "brak oceny") dla wszystkich - NIE zgaduje.

        Dlaczego ranga percentylowa, a nie sigmoida surowej oceny: poprzednia
        wersja robila 1/(1+exp(-raw*5.0)), zakladajac (w komentarzu), ze
        decision_function daje "typowo w przyblizeniu [-0.5, 0.5]". Zmierzone
        na 927 klastrach z ZYWEGO lidaru: faktyczny zakres to [-0.157, 0.078],
        czyli ~10x wezszy. Efekt: wszystkie oceny ladowaly w [0.31, 0.60],
        wskaznik wygladal jak stala 0.5, calkiem obcy obiekt dostawal 0.38, a
        prog "nietypowe < 0.3" w UI nie mogl sie odpalic NIGDY. Ranga
        percentylowa jest samokalibrujaca - rozklada sie na calym [0,1] bez
        wzgledu na skale surowych ocen, wiec nie wymaga zgadywania stalej i
        nie psuje sie, gdy zmieni sie scena albo liczba cech.
        """
        if not clusters:
            return []
        if not self._fitted:
            return [0.5] * len(clusters)

        features = np.array([extract_features(c) for c in clusters])
        raw = self._model.forest.decision_function(features)
        reference = self._model.reference_scores
        # Ranga percentylowa = ilu punktom treningowym ten klaster jest
        # "rowny lub bardziej typowy", podzielone przez rozmiar historii.
        #
        # SRODEK wiazki remisow (srednia z granicy lewej i prawej), a nie
        # sama granica lewa: w statycznej scenie te same klastry powtarzaja
        # sie co tick, wiec historia 2000 probek miewa tylko kilkadziesiat
        # UNIKALNYCH wektorow cech, kazdy powielony dziesiatki razy. Przy
        # side="left" kazdy klaster bylby systematycznie zanizony o cala
        # swoja wiazke remisow, a najbardziej typowy nigdy nie osiagnalby
        # 1.0 (zmierzone: max 0.963 zamiast 0.981 przy 27 unikalnych
        # wartosciach). Srodek wiazki to standardowa definicja rangi
        # percentylowej i usuwa to obciazenie.
        left = np.searchsorted(reference, raw, side="left")
        right = np.searchsorted(reference, raw, side="right")
        scores = (left + right) / (2.0 * len(reference))
        return scores.tolist()
