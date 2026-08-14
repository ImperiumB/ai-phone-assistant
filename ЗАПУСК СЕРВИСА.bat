@echo off
rem ===========================================================================
rem  ZAPUSK SERVISA - prototip UL-17568 (tiket: virtualnyy AI pomoshchnik)
rem
rem  Dvazhdy kliknut po faylu. Okno ne zakryvat: poka ono otkryto - servis
rem  rabotaet. Nastroyki nizhe mozhno pravit pryamo zdes, potom perezapustit.
rem
rem  Kommentarii latinicey namerenno: komandnye fayly Windows lomayutsya
rem  na kirillice iz-za kodirovok. Podrobnoe opisanie nastroek - v README.md.
rem ===========================================================================

rem Dvizhok raspoznavaniya: gigaam (bystree, put k modeli ne nuzhen) ili vosk
set AIA_STT_ENGINE=gigaam

rem Model GigaAM. v3_rnnt - obychnyy vybor (bystree v2_rnnt na tret).
rem   v3_ctc      - eshche bystree, chut menee tochnaya
rem   v3_e2e_rnnt - stavit punktuatsiyu i zaglavnye bukvy
set AIA_GIGAAM_MODEL=v3_rnnt

rem Tolko dlya vosk: put k raspakovannoy modeli
set AIA_VOSK_MODEL_PATH=C:\Users\user\models\vosk-model-small-ru-0.22

rem Sintez rechi. Modeli: v5_ru (novee), v4_ru
rem Golosa: eugene, aidar, baya, xenia, kseniya
set AIA_TTS_MODEL=v5_ru
set AIA_TTS_VOICE=eugene

rem Pauza tishiny (ms), po kotoroy bot ponimaet chto sobesednik dogovoril.
rem Menshe - otvechaet zhivee, no perebivaet zadumavshegosya.
rem Bolshe - razgovor oshchushchaetsya slomannym.
set AIA_UTTERANCE_PAUSE_MS=1000

rem Porog blizosti voprosa k baze znaniy (0..1). 0.65 podobran zamerom 14.08.2026:
rem vernye popadaniya 0.669-0.857, postoronnie voprosy 0.455-0.568.
rem Vyshe - chashche chestno perevodit na spetsialista.
set AIA_SIMILARITY_THRESHOLD=0.65

cd /d "%~dp0"
echo.
echo   STT    : %AIA_STT_ENGINE%
echo   STT_M  : %AIA_GIGAAM_MODEL%
echo   TTS    : %AIA_TTS_MODEL% / %AIA_TTS_VOICE%
echo   PAUSE  : %AIA_UTTERANCE_PAUSE_MS% ms
echo   THRESH : %AIA_SIMILARITY_THRESHOLD%
echo.
echo   Gotovnost = stroka "Uvicorn running on http://0.0.0.0:8080"
echo   Pervyy zapusk na novoy modeli dolshe: kachayutsya vesa.
echo.
py -3.12 -m ai_assistant.service.main

echo.
echo   Servis ostanovlen. Okno mozhno zakryt.
pause