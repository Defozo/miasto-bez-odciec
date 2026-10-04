# Architektura i odtwarzalność

Autor: DEFOZO SOFTWARE HOUSE, Michał Kiełtyka.

## Warstwy rozwiązania

React 18, TypeScript i Vite tworzą polski interfejs mieszkańca, koordynatora, moderatora oraz weryfikatora. MapLibre wyświetla lokalny styl i geometrie; tekstowa lista zachowuje informację potrzebną bez mapy. Frontend i API działają pod jednym originem. FastAPI obsługuje kontrakt `/api/v1`; modele Pydantic w `services/api/schemas.py` opisują mutacje, wymagane pola i dozwolone stany. Swagger/OpenAPI są dostępne pod `/docs` i `/openapi.json` uruchomionego API.

SQLAlchemy przechowuje encje jako wersjonowane rekordy z `kind`, `layer` i danymi JSON. Osobne tabele obejmują użytkowników, sesje, idempotencję, audyt, stan wersji, zadania i outbox. Encje domenowe z planu, np. źródło, dowód, graf, zadanie terenowe, scenariusz i decyzja, są rodzajami rekordów, a nie odrębnymi tabelami dla każdego rzeczownika. Alembic wersjonuje schemat. PostgreSQL/PostGIS jest wariantem kontenerowym; SQLite zapewnia powtarzalny lokalny pokaz. To dwa warianty uruchomienia tej samej aplikacji.

`services/worker` niezależnie pobiera trwałe zadania. Lease, heartbeat, próby ponowienia i identyfikator właściciela umożliwiają odzyskanie po przerwaniu. Zapis wyniku kontroluje właściciela i wersję scenariusza. Zdarzenie outbox powstaje razem z mutacją w transakcji. SSE `/events` przekazuje publikacje wersji i uprawnionemu personelowi postęp zadań. Klient po ponownym połączeniu odczytuje aktualny stan, a odpytywanie `/versions` i statusu zadania pozostaje mechanizmem zapasowym.

## Dane i pochodzenie

`fixture`, `observed`, `planned` i `scenario` mają odrębne znaczenie. Testowy seed nie zastępuje danych obserwowanych. Scenariusz zachowuje migawkę wejścia, a zatwierdzenie planu nie publikuje nowej drożności. Wygaśnięcie dowodu prowadzi do niewiadomej lub kontroli, nie do automatycznego przedłużenia.

Źródło zachowuje treść, hash, wydawcę, prawa użycia oraz znane daty. Dowód dotyczy jednej cechy konkretnego obiektu, ma metodę i okno ważności. Potwierdzenie szerokości nie potwierdza nawierzchni. Konflikt dowodów nie może stać się trasą potwierdzoną. Zdjęcie stanowi materiał prywatny; aplikacja usuwa metadane przy ponownym zakodowaniu, ogranicza wielkość i nie wyprowadza z fotografii pomiaru w centymetrach.

Importer przyjmuje OSM/Overpass JSON, GeoJSON i CSV ograniczeń. Zachowuje topologię, poziomy oraz stabilne identyfikatory obiektów. Nowy graf jest najpierw w stagingu. Walidacja sprawdza wejścia, powiązania i aktywne ograniczenia. Niejednoznaczne powiązanie wstrzymuje publikację; nieznane tagi OSM nie są dowodem przejezdności. Pobrany graf OSM pozostaje w stagingu do kontroli topologii, wejść i cech przejść.

## Routing

Skierowany multigraf rozróżnia krawędzie, poziomy, fizyczne obiekty i wspólne grupy awarii. Samo przecięcie linii nie tworzy przejścia. Profil jest zestawem edytowalnych wymagań: schody, szerokość, krawężnik, spadek kierunkowy, nawierzchnia, dystans i czas. Nie jest diagnozą ani uniwersalną normą dostępności.

`G_confirmed` zawiera wyłącznie aktualnie potwierdzone cechy. `G_possible` dopuszcza niewiadome, zachowując zakazy i znane bariery. Potencjalna ścieżka służy wskazaniu kontroli. Wynik odróżnia potwierdzenie, potrzebę kontroli, znaną barierę, limit użytkownika, niepołączony model, brak pokrycia i niepełne obliczenie.

Krawędź oraz wejście muszą spełniać warunki w całym oknie `[wyjście, wyjście + maksymalny czas dojścia)`. Ograniczenie lub wygaśnięcie wewnątrz tego okna uniemożliwia potwierdzenie. Algorytm nie zakłada oczekiwania na otwarcie ani dokładnego trafienia w krótką szczelinę harmonogramu. Jest celowo konserwatywny; nie przewiduje przyszłych niezgłoszonych awarii.

Wyszukiwanie zachowuje niezdominowane etykiety dystansu, czasu i kosztu preferencji. Wykluczenie jednej najkrótszej ścieżki po przekroczeniu limitu nie kończy szukania innych wykonalnych ścieżek. Kategoria korzysta z wyszukiwania od wielu dopuszczalnych wejść na odwróconym grafie, z zachowaniem kosztów i nachylenia w kierunku oryginalnej podróży. Cache tej analizy rozróżnia wejścia, profil, okno, ograniczenia, stan potwierdzony/możliwy oraz granice obliczeń. Twardy warunek usuwa krawędź zamiast dodawania dużej kary. Limit obliczeń daje jawny wynik niepełny, nie fałszywą odpowiedź o odcięciu.

Potwierdzona nowa organizacja robót unieważnia wcześniejsze dowody wskazanych cech. Nieznany zakres zmiany wymaga ponownych dowodów wszystkich cech dostępności. Sam nowy pomiar otwarcia nie odnawia starej szerokości lub nawierzchni. Historia pozostaje zachowana; scenariusz może dodać jawne założenie wyłącznie dla określonej cechy.

## Ocena harmonogramu

Stały zbiór relacji to iloczyn początków, profili i celów lub kategorii. Każda relacja ma ten sam horyzont i ograniczenia we wszystkich wariantach. Dostępna kategoria liczy się raz niezależnie od liczby osiągalnych placówek. Konkretny cel wymaga właściwego wejścia. Godzina relacji nie oznacza godziny życia konkretnego mieszkańca.

Podział czasu uwzględnia zdarzenia robót, dowodów i przesunięte granice okna podróży. Silnik całkuje dostępność, utratę, niewiadome i zakres niedokończonych obliczeń. Raport pokazuje zyski i straty per profil, najdłuższe przerwy, wspólny mianownik oraz diagnostykę chwilową. Koszt działania jest danymi wejściowymi z podstawą, nie automatycznie wyliczoną ceną rynkową.

Małe katalogi korzystają z pełnego przeglądu. Adapter OR-Tools CP-SAT wspiera większe katalogi z oknami, zasobami i zależnościami. `domain/graph/pathpool.py` generuje pulę legalnych ścieżek na fizycznym grafie przed filtrowaniem obserwacji, dzięki czemu zachowuje dojścia wymagające kilku napraw naraz. Model wiąże ważność obiektu przez całe okno z lokalnymi kombinacjami działań i sprawdza oba limity. Raport ujawnia limit liczby ścieżek, zakres lokalnych tablic, kompletność puli i status solvera. Każdy kandydat wymaga ponownej oceny pełnego grafu. Optimum dotyczy zadanej puli i katalogu. `OPTIMAL`, `FEASIBLE`, `INFEASIBLE` i `UNKNOWN` opisują różne stopnie rozstrzygnięcia. Wynik przerwany nie jest dowodem globalnego optimum.

Test wspólnej awarii usuwa cały obiekt lub grupę, również krawędzie w przeciwnych kierunkach. Kolejka kontroli porównuje wyniki po spełnieniu i niespełnieniu konkretnej nieznanej cechy. Nie interpretuje potencjalnego wpływu jako prawdopodobieństwa lub oczekiwanej oszczędności.

## Referencja 9/8 godzin

Dwa początki, jeden cel, dwa dojścia i profil 30 min. Horyzont wyjść 08:00-20:30, dane do 21:00. X: 08:00-14:00, Y: 10:00-16:00. Chwilowa utrata: 2 × 4 h = 8 h relacji. Całe okno podróży: wyjścia 09:30-14:00, czyli 2 × 4,5 h = 9 h relacji.

Y przesunięte na 14:30-20:30 odzyskuje 9 h przy potwierdzonym otwarciu X o 14:00. Y od 14:00 odzyskuje tylko 8 h, ponieważ wyjścia przed zmianą nie mają jednego dojścia ważnego przez całe okno. Opóźnienie otwarcia X znosi warunek wariantu bezpiecznego. To kontrolowany przykład syntetyczny.

## Reprodukcja i API

Analiza przechowuje migawkę grafu i ograniczeń, wersje danych, profile, cele, horyzont, założenia, parametry oraz identyfikator algorytmu. Porównanie efektu zachowuje także pierwotny brak wymagania lub wartość `null`; późniejsze ustawienia profilu nie mogą zmienić przedmiotu oceny. Zapis scenariusza zawiera fingerprint kodu wyliczany przez `services/version.py`, a wynik i eksport także `evaluated_code_version` faktycznie wykonującego workera. Pozwala to rozpoznać przeliczenie starszego scenariusza po aktualizacji programu. Manifest pakietu identyfikuje pliki kodu wydania hashami SHA-256. Eksport JSON wraz z właściwym wydaniem kodu służy reprodukcji; CSV do zestawienia, GeoJSON do geometrii. Eksporty oznaczają warstwę i nie obejmują kontaktu autora. Komórki CSV z początkiem interpretowalnym jako formuła są neutralizowane.

| API | Główne operacje |
| --- | --- |
| `/coverage`, `/places`, `/profiles`, `/routes` | Zakres danych, wybór celu i trasa |
| `/reports`, `/reports/{id}/review` | Zgłoszenie, prywatny status, moderacja |
| `/tasks`, `/tasks/{id}/photos`, `/tasks/{id}/observe` | Plan kontroli, prywatne zdjęcie i pomiar |
| `/evidence/{id}/publish`, `/evidence/{id}/history` | Publikacja cechy i historia |
| `/sources`, `/sources/{id}/extract` | Zachowanie komunikatu i kandydatura ekstrakcji |
| `/restrictions`, `/restrictions/{id}/open` | Ograniczenie i potwierdzone otwarcie |
| `/imports`, `/graphs/{id}/edit`, `/graphs/{id}/validate`, `/graphs/{id}/publish` | Staging, uzupełnienie danych, kontrola i atomowa publikacja |
| `/analysis/evaluate`, `/analysis/failures`, `/analysis/verification-impact` | Ocena, awarie i wpływ brakujących danych |
| `/scenarios`, `/scenarios/{id}/evaluate`, `/jobs/{id}` | Trwała analiza i postęp |
| `/scenarios/{id}/decision`, `/scenarios/{id}/effects`, `/exports/{id}` | Decyzja, wykonanie, efekt i eksport |
| `/diagnostics`, `/audit`, `/versions`, `/events` | Eksploatacja, historia i aktualizacja widoku |

Ścieżki mają prefiks `/api/v1`. Mutacje operatora wymagają sesji, właściwej roli, CSRF, klucza idempotencji i oczekiwanej wersji odpowiedniego zasobu. Ponowienie identycznego żądania zwraca jego wynik; zmiana treści z tym samym kluczem jest konfliktem. Publiczny status zgłoszenia wymaga losowego prywatnego tokenu.

Mechanizm haseł Argon2 był inspirowany audytem przypiętego pliku Full Stack FastAPI Template. Zastosowano własne odwoływalne sesje opaque w ciasteczku zamiast JWT startera. Nie sklonowano całej aplikacji startera. Dokładny zakres, revision i licencja są w `third_party/` i `ATTRIBUTIONS.md`.
