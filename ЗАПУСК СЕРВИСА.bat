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

rem Vtoraya model GigaAM - vtoroe mnenie: esli po tekstu pervoy modeli tema v baze
rem ne nashlas, replika raspoznaetsya eshche raz. VYKLYUCHENO 07.11.2026.
rem
rem Pochemu. Obeshchalos +0.5 s tolko na promahah, a po logu za 23 dnya eto do
rem +3.5 s na srezannyh replikah (hudshie zamery 15.4 s i 12.1 s pri mediane
rem 1.7 s), prichem embedding schitaetsya dvazhdy. Polza za mesyac: 7 zamen, iz
rem nih polezna odna ('da borka' -> 'da sborka'), a dve vrednye: 'ne
rem vklyuchaetsya' -> 'perfer ne vklyuchaetsya' i 'mne nuzhen' -> 'mne nuzhen
rem sayt' (obrashchenie 270057961: model vydumala temu, kotoroy klient ne
rem nazyval). Varianty oshibok raspoznavaniya brendov derzhat BRAND_GATES v
rem knowledge.py, tak chto poleznaya chast kompensirovana.
rem
rem Vklyuchit obratno: postavit v2_rnnt i perezapustit servis.
rem
rem VAZHNO: vyklyuchenie zadayotsya SLOVOM 'net', a ne pustotoy.
rem V cmd `set AIA_X=` peremennuyu NE obnulyaet, a UDALYAET, posle chego
rem config.py beret svoyo umolchanie. Na etom molcha ne srabotala pravka F6
rem plana ultrakoda 07.11.2026: v bat postavili pustoe znachenie, a v loge
rem SBORKA pechatalos vtoroe_mnenie=v2_rnnt i vtoraya model gruzilas kazhdyy
rem start. Poymala eto stroka SBORKA 09.11.2026, do volny pravka ne doshla.
rem Slova vyklyucheniya: net, vykl, off, none, minus. Proverit mozhno po
rem stroke SBORKA v logs/aia.log: tam dolzhno byt vtoroe_mnenie=vykl.
set AIA_STT_FALLBACK_MODEL=net

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

rem Skolko molchaniya podryad schitaetsya 'klient ne otvechaet'. Po pervomu
rem takomu sobytiyu bot sprashivaet 'Vy menya slyshite?', po vtoromu perevodit
rem na soprovozhdenie (dialog.py, silence_count >= 2).
rem Bylo 15000 (znachenie po umolchaniyu v kode). Zamer 10.11.2026 na zhivoy
rem zapisi molchashchego zvonka (Maksim molchal v trubku 31 s): pri 15000 pervoe
rem sobytie prishlo na 29 sekunde, a ne na 15. Prichina: Silero v chistoy tishine
rem izredka metit kadr kak rech, i schetchik obnulyaetsya; chem dlinnee okno, tem
rem veroyatnee, chto sbros popadet vnutr. Pri 5000 sobytiya idut na 5.5 / 10.5 /
rem 19.0 / 24.0 sekunde, to est bot sprashivaet na 6 sekunde i perevodit na 11.
rem Cena: klient, kotoryy dumaet dolshe 6 sekund, uslyshit vopros, a esli
rem promolchit eshche 5, uedet k cheloveku. Reshenie Maksima 10.11.2026.
set AIA_SILENCE_TIMEOUT_MS=5000

rem Porog detektora rechi Silero (0..1). 0.35 - zamer 13.10.2026 na syryh potokah:
rem vmeste so sbrosom pamyati detektora po razryvu potoka vozvrashchaet korotkie
rem otvety posle frazy bota ("novyy", "ugu", "da"); 0.5 teryal tri korotkih otveta.
set AIA_VAD_THRESHOLD=0.35

rem Porog blizosti voprosa k baze znaniy (0..1). 0.66 podobran zamerom 20.08.2026
rem na boevoy baze iz 40 napravleniy: svoi voprosy 0.675-0.850, postoronnie
rem 0.472-0.643. Nizhniy kray svoih derzhat korotkie zaprosy remonta:
rem "remont televizora" 0.6752, "remont stiralnoy mashiny" 0.6768.
rem Nizhe - bot uverenno sprashivaet ne pro tu tehniku ("pochinit pitstsu"
rem daet 0.6432). Vyshe - teryayutsya korotkie zaprosy remonta.
set AIA_SIMILARITY_THRESHOLD=0.74
set AIA_CORPUS_INDEX_PATH=ai_assistant\corpus_index.npz
set AIA_CORPUS_K=15
set AIA_CORPUS_THRESHOLD=0.50

rem Seraya zona uverennosti korpusa: nizhe etogo poroga korpus oshibaetsya
rem chashche, chem popadaet (68 procentov oshibok pri 0.50-0.60 protiv 1.5
rem vyshe 0.90). V takoy zone bot ne ugadyvaet temu i ne otdaet repliku
rem rukopisnym formulirovkam (u nih tochnost 36 procentov), a ODIN raz
rem prosit povtorit. Vtoraya takaya replika idet k cheloveku.
rem Reshenie zakazchika 07.11.2026. Otkat: postavit 0.
rem Zamer 07.11.2026 na 4000 replikah: porog 0.60 daet 'ne tuda' 157 vmesto
rem 200 pri potere 20 vernyh voprosov, eto kurs 2.15 k 1 i pravilo zakazchika
rem '1 k 2' prohodit. Porog 0.70 daet 132 pri potere 60, eto 1.13 k 1 i ne
rem prohodit. Poetomu 0.60.
set AIA_CORPUS_GREY_ZONE=0.60
rem Skolko raz prosim povtorit v seroy zone. 0 - srazu k cheloveku.
set AIA_GREY_REASK_ATTEMPTS=1

rem Porog, s kotorogo uverennyy golos korpusa za napravlenie 17 (Soprovozhdenie)
rem vedet zvonok k cheloveku BEZ utochnyayushchego voprosa. 07.11.2026: 0.72 -> 0.50.
rem Pri 0.72 takaya replika uhodila v razvilku 'po oformlennomu zakazu ili novyy',
rem i zamer na 4000 replik pokazal: razvilka zadavalas 198 raz, iz nih 164 na
rem povtornyh obrashcheniyah, gde korpus UZHE golosoval za cheloveka. Pri 0.50
rem razvilki net vovse, povtornye uhodyat k cheloveku v 92.1 procenta sluchaev
rem vmesto 85.6. Menyat TOLKO paroy s AIA_SIMILARITY_THRESHOLD: poodinochke oni
rem dayut lozhnuyu kartinu. Otkat: vernut 0.72 i 0.66 i perezapustit servis.
set AIA_CORPUS_OPERATOR_THRESHOLD=0.50

rem Yarus nameneniya: povtornoe obrashchenie ('mne master zvonil', 'ya u vas
rem zakazyval') uhodit k cheloveku DO geytov kategoriy i do korpusa. Model
rem obuchaetsya otdelno: py -3.12 tools/train_intent.py. 1 - vklyuchit.
rem Vklyuchat TOLKO posle zamera lineykoy (tools/measure_live.py): zamok
rem priemki - 'verno po novym zakazam ne upalo ni na odnu repliku'.
rem Otkat: postavit 0 i perezapustit servis.
rem Zamer 07.11.2026 proyden: 'ne tuda' 233 -> 197, povtornye k cheloveku
rem 85.4 -> 93.8 procenta, verno po novym zakazam NE upalo ni na odnu repliku
rem (549 i 549). Poetomu vklyucheno.
rem 12.11.2026: yarus vyklyuchali na chas po oshibke i vernuli. On i est to, chto
rem nuzhno Maksimu: povtornye srazu v soprovozhdenie. Zamer 12.11: bez yarusa
rem 20 povtornyh iz 2469 poluchayut vopros pro tehniku, novye zakazy bez izmeneniy.
set AIA_TIERS_ENABLED=1
set AIA_INTENT_MODEL_PATH=ai_assistant/intent_model.json
rem Porog veroyatnosti povtornogo obrashcheniya. 0.70: kross-validaciya na 5
rem foldah daet tochnost otbora 98.4 procenta pri polnote 71.6.
set AIA_INTENT_REPEAT_THRESHOLD=0.70

rem Zamki tem (tablichnaya chast 'Zamki' zapisi bazy znaniy v ERP) molchat, esli
rem korpus uverenno golosuet za soprovozhdenie. Reshenie zakazchika 12.11.2026:
rem povtornoe obrashchenie idet v soprovozhdenie, dazhe esli nazvana tehnika.
rem Zamer lineykoy na 4000 replik (novyh zakazov verno / povtornyh verno):
rem   0 (vykl) 614 / 2152,  0.80 608 / 2227,  0.70 604 / 2253,  0.50 593 / 2304.
rem 0.80 vybran potomu, chto nizhe nego snova padayut keysy volny 13
rem ('mastera po televizoru na dom', 'televizor slomalsya'): tam korpus uverenno
rem i neverno golosuet za soprovozhdenie. Proverka: tools/regress_waves.py.
rem Otkat: postavit 0 i perezapustit servis.
set AIA_GATE_CORPUS_GUARD=0.80

rem Yavnoe 'net' na ugadannuyu temu vedet k cheloveku, bez vtorogo kruga
rem ugadyvaniya (reshenie analitika KC posle 11-y volny, 07.11.2026).
rem Zamer replea 738 zhivyh zvonkov: zvonkov s 4+ frazami bota 70 -> 36,
rem povtor otvergnutoy temy 15 -> 0, razgovor bez ishoda 137 -> 104.
rem Cena: perevodov v profilnyy otdel 194 -> 168, na operatorskiy stol
rem 407 -> 466. Otkat: postavit 0 i perezapustit servis.
set AIA_NO_SECOND_ROUND=1

rem Skolko fraz bot govorit za zvonok, prezhde chem otdat razgovor
rem cheloveku. 0 - bez predela (povedenie do 07.11.2026). Predel 5
rem obrezaet 2 zvonka iz 738, vse uzhe dlinnye.
set AIA_MAX_BOT_PHRASES=5

rem Kak chasto vholostuyu progonyat raspoznavanie i poisk, chtoby modeli ne
rem vygruzhalis iz pamyati vo vremya prostoya. U procesa, kotoryy dolgo nichego
rem ne delal, sistema urezaet rabochiy nabor - i pervaya replika sleduyushchego
rem zvonka schitaetsya 5.8 s vmesto obychnyh 1.5-2.5. 0 - vyklyuchit.
set AIA_KEEPWARM_SECONDS=120

rem Kuda skladyvat zapisi replik, kak ih uslyshal dvizhok raspoznavaniya.
rem Pusto - ne skladyvat (obychnyy rezhim). Zapolnyat tolko na vremya razbora
rem sporov vida "ya skazal net, a raspoznalos da": po logu ne otlichit golos
rem klienta ot eha sobstvennoy frazy bota. Imya fayla - vremya, zvonok i tekst.
set AIA_DEBUG_AUDIO_DIR=debug_audio

rem Predel papki otladochnyh zapisey (MB) i srok hraneniya (dni). 0 - bez pravila.
rem Zapis vklyuchena postoyanno, a zapisi razgovorov klientov nelzya kopit bez
rem predela: 0.3 MB na zvonok, 181 MB za 25 dney na odnoy gruppe liniy. Polnyy
rem disk nemeet bota celikom: sintez ne sozdast vremennyy fayl, /tts otdast 500,
rem i stanciya uvodit kazhdyy zvonok na avariynyy perevod. 07.11.2026: disk C
rem zanyat na 94 procenta.
set AIA_DEBUG_AUDIO_MAX_MB=1024
set AIA_DEBUG_AUDIO_KEEP_DAYS=14

rem Skolko zvonkov obsluzhivaem odnovremenno: razmer pula potokov i predel
rem odnovremennyh vyzovov gRPC. Lishniy zvonok poluchaet otkaz srazu, i
rem stanciya uvodit ego na avariynyy perevod k cheloveku. Bez predela lishniy
rem vyzov molcha zhdal v ocheredi, i klient slushal tishinu do taymauta 120 s.
set AIA_GRPC_MAX_CALLS=24

rem Skolko potokov otdavat odnomu raspoznavaniyu (torch). 0 - ne trogat, kak
rem seychas: kazhdoe raspoznavanie beret vse yadra. Menyat tolko posle zamera:
rem pri neskolkih odnovremennyh zvonkah yadra delyatsya i otvet rastet
rem nelineyno, a pri odinochnom zvonke limit zamedlyaet otvet.
set AIA_TORCH_THREADS=0

rem Sintezirovat vse izvestnye frazy pri starte (1) ili po hodu zvonka (0).
rem Holodnyy sintez stoit do 2 sekund, i klient slushaet ih kak tishinu.
set AIA_PREWARM_TTS=1

rem Nizhe kakoy pikovoy gromkosti probovat raspoznat tihuyu repliku VTOROY raz,
rem podnyav uroven. 0 - vyklyuchit vtoruyu popytku.
rem Snachala stoyalo -30 dB (hvost raspredeleniya gromkosti), i eto okazalos vdvoe
rem strozhe nuzhnogo. 09.11.2026 na zhivom prozvone: replika "da" s pikom -15.8 dB
rem vernula pustotu, bot otvetil "Slushayu vas", a podem urovnya tu repliku vytaskivaet.
rem Zamer po 251 zapisannoy replike: pustyh 14, podem vytaskivaet 6, i vse shest
rem dostayutsya porogom -15 dB (pri -30 dB bylo 3). Cena: 4 lishnih prohoda na 251
rem repliku, i tolko tam, gde pervyy prohod uzhe vernul pustotu.
set AIA_QUIET_RETRY_DBFS=-15.0
rem Do kakogo urovnya podnimat. -6 dB eto zapas ot klippinga.
set AIA_QUIET_RETRY_TARGET_DBFS=-6.0

rem Predely kesha sinteza: megabayty i srok zhizni fayla v dnyah. 0 - pravilo
rem vyklyucheno (slovo "net" tut tozhe ponimaetsya kak nol). Nuzhny potomu, chto v
rem klyuch kesha vhodit otpechatok biblioteki golosov: kazhdaya ee pravka
rem pereimenovyvaet ves kesh, a fayly pod prezhnimi imenami ostayutsya naveki.
rem 09.11.2026 nabralos 2287 faylov na 177 MB pri 58 zhivyh frazah. Chistka idet
rem na starte i TOLKO vmeste s progrevom vyshe: bez nego vosstanavlivat udalennoe
rem nekomu, i sintez prishelsya by na razgovor.
set AIA_TTS_CACHE_MAX_MB=64
set AIA_TTS_CACHE_KEEP_DAYS=30

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