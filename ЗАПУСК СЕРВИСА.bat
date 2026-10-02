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

rem Sintez rechi. Dvizhok: vosk (boevoy) ili silero (zapasnoy).
rem Silero ostavlen tolko kak zapasnoy: model v5_ru licenzirovana CC BY-NC,
rem to est nekommercheski, a bot rabotaet na boevoy linii. Vklyuchat ee
rem nadolgo nelzya - eto pravovoy risk, a ne vopros vkusa.
set AIA_TTS_ENGINE=vosk

rem Papka s raspakovannoy modelyu vosk-model-tts-ru-0.7-multi (~236 MB).
rem Bez nee servis ne podnimetsya: biblioteka umeet kachat model sama, no
rem so stancii GitHub nedostupen, poetomu model kladetsya rukami.
set AIA_VOSK_TTS_MODEL_PATH=C:\Users\user\models\vosk-model-tts-ru-0.7-multi

rem Diktor Vosk. Poryadok - po razborchivosti (zamer 04.09.2026):
rem   s3 - 49%%, vybran osnovnym
rem   s4 - 42%%,  s0 - 41%%,  s1 - 40%%,  s2 - 37%%
rem Eto znachenie po umolchaniyu. Golos, vybrannyy v gruppe liniy ERP,
rem sil'nee: pustoe pole v spravochnike oznachaet "vzyat otsyuda".
set AIA_TTS_VOICE=s3

rem Tolko dlya AIA_TTS_ENGINE=silero. Modeli: v5_ru (novee), v4_ru
rem Golosa silero: eugene, aidar, baya, xenia, kseniya
set AIA_TTS_MODEL=v5_ru

rem Pauza tishiny (ms), po kotoroy bot ponimaet chto sobesednik dogovoril.
rem Menshe - otvechaet zhivee, no perebivaet zadumavshegosya.
rem Bolshe - razgovor oshchushchaetsya slomannym.
set AIA_UTTERANCE_PAUSE_MS=1000

rem Porog blizosti voprosa k baze znaniy (0..1). 0.66 podobran zamerom 20.08.2026
rem na boevoy baze iz 40 napravleniy: svoi voprosy 0.675-0.850, postoronnie
rem 0.472-0.643. Nizhniy kray svoih derzhat korotkie zaprosy remonta:
rem "remont televizora" 0.6752, "remont stiralnoy mashiny" 0.6768.
rem Nizhe - bot uverenno sprashivaet ne pro tu tehniku ("pochinit pitstsu"
rem daet 0.6432). Vyshe - teryayutsya korotkie zaprosy remonta.
set AIA_SIMILARITY_THRESHOLD=0.66
set AIA_CORPUS_INDEX_PATH=ai_assistant\corpus_index.npz
set AIA_CORPUS_K=15
set AIA_CORPUS_THRESHOLD=0.50

rem Kak chasto vholostuyu progonyat raspoznavanie i poisk, chtoby modeli ne
rem vygruzhalis iz pamyati vo vremya prostoya. U procesa, kotoryy dolgo nichego
rem ne delal, sistema urezaet rabochiy nabor - i pervaya replika sleduyushchego
rem zvonka schitaetsya 5.8 s vmesto obychnyh 1.5-2.5. 0 - vyklyuchit.
set AIA_KEEPWARM_SECONDS=300

rem Kuda skladyvat zapisi replik, kak ih uslyshal dvizhok raspoznavaniya.
rem Pusto - ne skladyvat (obychnyy rezhim). Zapolnyat tolko na vremya razbora
rem sporov vida "ya skazal net, a raspoznalos da": po logu ne otlichit golos
rem klienta ot eha sobstvennoy frazy bota. Imya fayla - vremya, zvonok i tekst.
set AIA_DEBUG_AUDIO_DIR=

rem Sintezirovat vse izvestnye frazy pri starte (1) ili po hodu zvonka (0).
rem Holodnyy sintez stoit do 2 sekund, i klient slushaet ih kak tishinu.
set AIA_PREWARM_TTS=1

cd /d "%~dp0"
echo.
echo   STT    : %AIA_STT_ENGINE%
echo   STT_M  : %AIA_GIGAAM_MODEL%
echo   TTS    : %AIA_TTS_ENGINE% / %AIA_TTS_VOICE%
echo   PAUSE  : %AIA_UTTERANCE_PAUSE_MS% ms
echo   THRESH : %AIA_SIMILARITY_THRESHOLD%
echo   CORPUS : %AIA_CORPUS_INDEX_PATH% (k=%AIA_CORPUS_K%, conf=%AIA_CORPUS_THRESHOLD%)
echo.
echo   Gotovnost = stroka "Uvicorn running on http://0.0.0.0:8080"
echo   Pervyy zapusk na novoy modeli dolshe: kachayutsya vesa.
echo.
py -3.12 -m ai_assistant.service.main

echo.
echo   Servis ostanovlen. Okno mozhno zakryt.
pause