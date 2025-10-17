# mujrozhlas → MP3
Dokumentácia bola vytvorená s GPT5

Jednoduchý skript v Pythone, ktorý:
1. pomocou Playwrightu prejde stránku **mujrozhlas.cz** a nájde URL streamov (`.mpd` alebo `.mp3`),  
2. stiahne/nahraje audio cez **ffmpeg**,  
3. spojí všetko do jedného **MP3** súboru.

> ⚠️ **ffmpeg musí byť stiahnutý z oficiálnych stránok** a uložený do **rovnakého priečinka** ako tento skript (alebo pridaný do `PATH`).  
> Odporúčané zdroje: [ffmpeg.org](https://ffmpeg.org/) / oficiálne buildy pre váš OS.

---

## Požiadavky

- **Python 3.9+**
- Knižnice Pythonu:
  - `playwright`
  - `requests`
- **Playwright prehliadač** (Chromium)
- **ffmpeg** (binárka v rovnakom priečinku alebo v `PATH`)

### Inštalácia

```bash
# 1) Klonovanie (alebo uložte súbor .py do priečinka)
git clone <tento-repo>
cd <tento-repo>

# 2) Závislosti Pythonu
pip install -r requirements.txt  # ak máte súbor, inak:
pip install playwright requests

# 3) Inštalácia prehliadača pre Playwright
python -m playwright install chromium
```

### ffmpeg

1. Stiahnite **oficiálny** ffmpeg pre váš systém (Windows/macOS/Linux).  
2. Rozbaľte binárky a **skopírujte `ffmpeg`/`ffmpeg.exe` do rovnakého priečinka** ako je tento skript  
   *(alebo pridajte cestu k `ffmpeg` do systémového `PATH`)*.

---

## Použitie

Základný príkaz:

```bash
python mujrozhlas_dl.py "https://www.mujrozhlas.cz/nejaky/konkretni-dil"
```

Vo výstupe sa vytvorí súbor `NázovDielu.mp3` (odvodený z URL).

### Voľby

- `-o, --output` – názov výsledného MP3
- `--keep-parts` – ponechá dočasné časti (jednotlivé stiahnuté/nahrané MP3)

**Príklady:**

```bash
# 1) Automatický názov podľa URL
python mujrozhlas_dl.py "https://www.mujrozhlas.cz/podcasty/sci-fi/epizoda-42"

# 2) Vlastný názov výstupu
python mujrozhlas_dl.py "https://www.mujrozhlas.cz/porad/..." -o "moj_vystup.mp3"

# 3) Ponechať časti (na debug/kontrolu)
python mujrozhlas_dl.py "https://www.mujrozhlas.cz/porad/..." --keep-parts
```

---

## Ako to funguje (stručne)

- **Playwright (Chromium)** otvorí stránku a klikne na tlačidlá prehrávania, aby vyvolal načítanie manifestov/streamov.
- URL s doménou `croaod.cz` a príponou `.mpd` alebo `.mp3` sa zozbierajú.
- `.mp3` sa sťahujú priamo; **DASH (`.mpd`)** sa nahráva cez `ffmpeg` a prekonvertuje do MP3 (192 kbps).
- Všetky časti sa **spoja** do jedného MP3 cez `ffmpeg concat`.

---

## Riešenie problémov

- **„ffmpeg not found in PATH“**  
  Uistite sa, že `ffmpeg` je v rovnakom priečinku ako skript alebo v `PATH`.

- **„No croaod.cz .mpd/.mp3 streams detected“**  
  Skúste spustiť znovu, uistite sa, že ide o stránku s prehrávačom na mujrozhlas.cz.  
  (Skript sa snaží kliknúť na rôzne tlačidlá „Přehrát“, aby sa streamy načítali.)

- **Pomalé alebo nestabilné sťahovanie**  
  Skontrolujte pripojenie. Pri `.mpd` záznamoch ide o real-time nahrávanie cez `ffmpeg`.

---

## Bezpečnosť a zodpovednosť

Skript používajte len na osobné účely a rešpektujte podmienky používania a autorské práva.  

---

## Súbor `requirements.txt` (voliteľné)

Ak chcete, vytvorte si `requirements.txt` s obsahom:

```
playwright
requests
```

Potom stačí:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

---

## Licencia

MIT
