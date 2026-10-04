# Dane demonstracyjne

`python -m domain.graph.export_fixture` zapisuje `smart-city.json` z deterministycznego generatora. Graf ma dwa początki, dwa niezależne dojścia i jedno rzeczywiste w modelu wejście. Współrzędne ilustrują kandydata obszaru pilota w Krakowie, a geometria, dowody, prace i profile są syntetyczne. Nie przedstawiają aktualnego stanu ulic.

Zegar: 3 października 2026, strefa Europe/Warsaw. Okno wyjść 08:00-20:30, maksymalne dojście 30 minut. X:08:00-14:00; Y:10:00-16:00. Wynik referencyjny: 9 godzin niedostępności relacji i 8 godzin według diagnostyki chwilowej. Przesunięcie Y na 14:30-20:30 odzyskuje 9 godzin przy założeniu potwierdzonego otwarcia X o 14:00. Y od 14:00 nie zachowuje całych okien podróży.

Licencja własnych danych syntetycznych: CC0-1.0. Źródło: generator `domain/graph/fixture.py`. Dane demo zapisuje się wyłącznie w przestrzeni fixture.
