@echo off
rem ===========================================================================
rem  SBOR KORPUSA REPLIK KLIENTOV (UL-19020)
rem
rem  Dvazhdy kliknut po faylu. Okno ne zakryvat: poka ono otkryto - sbor idet.
rem  Ostanovit mozhno v lyuboy moment (Ctrl+C ili zakryt okno): razobrannoe
rem  sohranyaetsya srazu, sleduyushchiy zapusk prodolzhit s togo zhe mesta.
rem
rem  Kommentarii latinicey namerenno: komandnye fayly Windows lomayutsya
rem  na kirillice iz-za kodirovok.
rem ===========================================================================

rem Skolko protsessov. Kazhdyy zanimaet ~1,6 GB OZU i TORCH_THREADS yader.
rem Na mashine 10 yader i 25 GB: 5 x 2 zanimaet vse yadra i ~8 GB.
rem Esli na mashine rabotaet chto-to eshche - stavit 3.
set WORKERS=5

rem Potokov torch na protsess. WORKERS * TORCH_THREADS ne bolshe chisla yader.
set TORCH_THREADS=2

rem Skolko zvonkov razobrat za etot zapusk. 0 - vse, chto est v calls.tsv.
rem Pervaya noch - 50000 (reshenie Maksima 17.09.2026). Pri 5 workers eto ~12 ch.
set LIMIT=50000

cd /d "%~dp0"
echo.
echo   WORKERS : %WORKERS% x %TORCH_THREADS% potoka
echo   LIMIT   : %LIMIT% zvonkov za zapusk
echo.
echo   Progress pechataetsya kazhdye 200 zvonkov.
echo   Rezultat: dataset\corpus.jsonl
echo.
py -3.12 tools/build_corpus.py --workers %WORKERS% --torch-threads %TORCH_THREADS% --limit %LIMIT%

echo.
echo   Sbor ostanovlen. Okno mozhno zakryt.
pause
