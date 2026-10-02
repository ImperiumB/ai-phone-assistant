"""Синтез речи и кэш готовых WAV.

Asterisk (format_wav) играет только PCM 16 бит / моно / 8000 Гц. Любой другой
формат он молча отвергает, и клиент слышит тишину — так уже ловили UL-18592.
"""
import contextlib
import hashlib
import logging
import math
import os
import re
import uuid
import wave
from typing import Dict, Iterator, List, Optional, Tuple

log = logging.getLogger(__name__)

# Модель Silero просят синтезировать на 48000 Гц, а не сразу на телефонных
# 8000 Гц, и понижают частоту сами через scipy.signal.resample_poly. Прямой
# синтез в 8000 Гц звучит заметно "деревянно" — эксперимент показал на 4-70%
# больше энергии в полосе 3400-4000 Гц (там оседают артефакты грубого
# понижения частоты) на всех пяти голосах модели по сравнению с обходным
# путём через 48 кГц. Плата — около 40-90 мс на фразу (по факту заметно
# больше первоначальной прикидки в 18 мс), что всё равно незаметно на фоне
# кэша готовых WAV (TtsCache). НЕ УПРОЩАТЬ обратно на прямой синтез в
# TELEPHONY_SAMPLE_RATE_HZ — это вернёт деревянный звук.
MODEL_SAMPLE_RATE_HZ = 48000
TELEPHONY_SAMPLE_RATE_HZ = 8000

# Частота модели Vosk-TTS. В отличие от Silero, просить у неё другую частоту
# нельзя: 22050 Гц зашиты в саму модель (vosk_tts.Synth.synth пишет WAV именно
# с этой частотой), и выбора «синтезировать повыше, понизить самим» тут просто
# нет. Понижение до телефонных 8000 Гц поэтому идёт не целым делением, а
# дробным отношением — см. resample_ratio.
VOSK_SAMPLE_RATE_HZ = 22050


def resample_ratio(sample_rate: int) -> Tuple[int, int]:
    """Целые up/down для resample_poly: 48000 -> (1, 6), 22050 -> (160, 441).

    resample_poly работает с целым отношением, а не с дробной частотой, и
    отношение надо сократить самим: 22050/8000 без сокращения — это фильтр на
    22050 точек вместо 441, то есть секунды на фразу вместо миллисекунд.
    """
    divisor = math.gcd(sample_rate, TELEPHONY_SAMPLE_RATE_HZ)
    return TELEPHONY_SAMPLE_RATE_HZ // divisor, sample_rate // divisor

# Пик готовой фразы. Минус децибел от полной шкалы: запас нужен, потому что
# дальше звук ещё раз проходит преобразование в кодек линии (alaw/ulaw), а
# сигнал, упирающийся в потолок, там начинает трещать.
#
# Замер кэша 31.08.2026 (196 фраз): пики разъезжались от -4.6 до 0.0 дБFS, у
# десяти фраз отсчёты были обрезаны по потолку. Обрезка бралась не из синтеза,
# а отсюда же: у полифазного фильтра есть выброс за пределы диапазона, и
# прежний код срезал его жёстко — верхушки волны у самых громких фраз
# получались плоскими, а это слышно как хрип на гласных.
#
# Нормализация по пику решает обе беды разом: выброс больше не срезается, а
# фразы перестают отличаться друг от друга по громкости. Средняя мощность речи
# при этом остаётся прежней (медиана -16.9 дБFS), то есть тише бот не станет.
TARGET_PEAK = 0.891  # -1 дБFS

# Эквализация под телефонный канал. Полоса канала — 300-3400 Гц, и всё, что
# ниже, до клиента не доходит: G.711 это просто отрежет. Но в синтезе такая
# энергия есть, она занимает запас громкости и заставляет нормализацию давить
# полезную часть сигнала. Срезаем её сами и заранее.
#
# Подъём в районе 2.5 кГц — там живёт разборчивость согласных. В телефонной
# полосе от них остаются одни хвосты, и небольшой акцент на этом участке —
# обычная практика для голосовых меню.
#
# Числа скромные намеренно: агрессивная эквализация на 8 кГц даёт звонкий,
# «жестяной» голос, который слушать хуже, чем глуховатый.
HIGHPASS_HZ = 250.0
PRESENCE_HZ = 2500.0
PRESENCE_GAIN_DB = 3.0
PRESENCE_Q = 0.9

# Версия обработки звука. Входит в подпись, а значит и в имя файла на станции:
# без этого правка громкости не доехала бы до боевых звонков вовсе — станция
# продолжила бы играть уже скачанные файлы. Ровно так уже вышло 13.08.2026 при
# смене модели синтеза. Менять при любой правке, слышимой в трубке.
AUDIO_PIPELINE_VERSION = "n2"


def telephony_eq(audio, sample_rate):
    """Подготовить синтезированную речь к телефонной полосе.

    Два звена: срез низов, которых канал всё равно не пропустит, и лёгкий
    подъём разборчивости в районе 2.5 кГц.

    Фильтруем на модельной частоте, до понижения до 8 кГц: полоса подъёма
    оказывается далеко от частоты Найквиста, и фильтр не звенит у самого края.

    Применяем в обе стороны (sosfiltfilt) — фаза не съезжает, а это на речи
    слышно как размазанные согласные.
    """
    import numpy as np
    from scipy.signal import butter, sosfiltfilt

    if audio.size == 0:
        return audio

    sos = butter(2, HIGHPASS_HZ / (sample_rate / 2.0), btype="highpass", output="sos")

    # Пиковый фильтр по классическим формулам биквада: в scipy готового
    # пикового эквалайзера нет, iirpeak делает узкий резонанс — не то.
    amp = 10.0 ** (PRESENCE_GAIN_DB / 40.0)
    w0 = 2.0 * np.pi * PRESENCE_HZ / sample_rate
    alpha = np.sin(w0) / (2.0 * PRESENCE_Q)
    b = [1 + alpha * amp, -2 * np.cos(w0), 1 - alpha * amp]
    a = [1 + alpha / amp, -2 * np.cos(w0), 1 - alpha / amp]
    peaking = np.array([[b[0] / a[0], b[1] / a[0], b[2] / a[0],
                         1.0, a[1] / a[0], a[2] / a[0]]])

    return sosfiltfilt(np.vstack([sos, peaking]), audio)


def to_telephony_pcm(audio, sample_rate: int) -> bytes:
    """Звук с модели -> PCM 16 бит на телефонных 8000 Гц.

    Общий хвост для всех синтезаторов: движки отличаются тем, как они
    получают звук, а обработка у них обязана быть одна. Разойдись она — и
    голоса разных движков поедут по громкости и по тембру, а сравнивать их на
    слух станет невозможно.

    Порядок звеньев не переставлять: эквализация до понижения частоты (фильтр
    работает вдали от края полосы), нормализация — после (фильтр меняет пик, и
    нормализовать до него значит нормализовать не то).
    """
    import numpy as np
    from scipy.signal import resample_poly

    equalized = telephony_eq(audio, sample_rate)
    up, down = resample_ratio(sample_rate)
    audio_8k = resample_poly(equalized, up=up, down=down)
    # Приводим фразу к одному пику вместо того, чтобы срезать выброс
    # полифазного фильтра по потолку. Срезание делало верхушки волны
    # плоскими — на слух это хрип на гласных, и в кэше такие фразы нашлись.
    # Заодно уходит разброс громкости между фразами: раньше одна звучала
    # заметно тише соседней просто потому, что так вышло у модели.
    peak = float(np.max(np.abs(audio_8k))) if audio_8k.size else 0.0
    if peak > 0:
        audio_8k = audio_8k * (TARGET_PEAK / peak)
    # Страховка от краёв численного диапазона: после нормализации выйти за
    # единицу нельзя, но и стоит она ничего.
    clipped = np.clip(audio_8k, -1.0, 1.0)
    return (clipped * 32767).astype(np.int16).tobytes()


@contextlib.contextmanager
def _temporary_ssl_cert_file(path: str) -> Iterator[None]:
    """Выставляет SSL_CERT_FILE только на время блока и возвращает как было.

    Нужно исключительно на время torch.hub.load: gRPC-сервер и HTTP-сервис
    живут в этом же процессе и могут ходить по TLS к своим адресам (например,
    к внутреннему CA компании), поэтому подменять доверенные корни для всего
    процесса навсегда нельзя — такие соединения начнут молча падать.
    """
    had_value = "SSL_CERT_FILE" in os.environ
    previous_value = os.environ.get("SSL_CERT_FILE")
    os.environ["SSL_CERT_FILE"] = path
    try:
        yield
    finally:
        if had_value:
            os.environ["SSL_CERT_FILE"] = previous_value
        else:
            del os.environ["SSL_CERT_FILE"]


def write_wav_8k(path: str, pcm: bytes) -> None:
    """Атомарная запись: сначала .tmp, потом переименование.

    Без этого оборванный синтез оставляет в кэше битый файл, который потом
    воспроизводится тишиной при каждом звонке.

    Имя временного файла уникально для каждого вызова (случайный суффикс), а
    не просто `путь + ".tmp"`. FastAPI-ручка `/tts` выполняет обработчики в
    разных потоках, и если демон перезапустили и несколько звонков разом
    просят одну и ту же ещё не закэшированную фразу, несколько потоков
    одновременно попадали бы этим же самым именем — на Windows это кладёт
    запись ошибкой доступа к файлу (см. ревью Task 9, Critical 2: так падали
    все восемь потоков в воспроизведённом сценарии). Уникальное имя убирает
    коллизию на самом временном файле, но не решает всё целиком: если два
    потока одновременно делают `os.replace(..., <тот же итоговый путь>)`,
    Windows у одного из них временами всё равно отвечает
    `PermissionError`/`WinError 5` — это подтверждено эмпирически, а не
    домысел из документации. Поэтому такую ошибку на `os.replace` не считаем
    падением: если итоговый файл на месте, значит другой поток уже успел его
    туда положить — это нормальный исход гонки, а не ошибка, и наша попытка
    просто не нужна.
    """
    tmp_path = "{0}.{1}.tmp".format(path, uuid.uuid4().hex)
    try:
        with wave.open(tmp_path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(pcm)
        try:
            os.replace(tmp_path, path)
        except OSError:
            if not os.path.exists(path):
                raise  # это не гонка с другим писателем, а настоящая ошибка
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass  # обычный случай: файл уже переименован


def read_wav_format(path: str) -> Tuple[int, int, int]:
    with wave.open(path, "rb") as handle:
        return handle.getnchannels(), handle.getsampwidth() * 8, handle.getframerate()


class SileroSynthesizer:
    """Запасной движок. Модель качается через torch.hub при первом обращении.

    До 04.09.2026 был боевым. Ушёл в запас не по качеству, а по лицензии:
    v5_ru опубликована как CC BY-NC (UL-17568, разбор 03.09.2026). Включать
    её на боевой линии надолго нельзя.
    """

    #: Частота, на которой синтезатор отдаёт звук в synthesize_at_model_rate.
    #: Читают генератор образцов голосов и to_telephony_pcm.
    model_sample_rate = MODEL_SAMPLE_RATE_HZ
    #: Голоса русской модели Silero.
    VOICES = ("eugene", "aidar", "baya", "xenia", "kseniya")

    def __init__(self, model_id: str = "v4_ru"):
        import certifi
        import torch

        # На части Windows-машин системное хранилище сертификатов не доверяет
        # цепочке models.silero.ai (сертификат в порядке, но сертификат
        # издателя туда не попал), из-за чего загрузка падает с
        # CERTIFICATE_VERIFY_FAILED. Актуальный набор корневых сертификатов
        # certifi решает это без отключения проверки. Действует только на
        # время загрузки модели, см. _temporary_ssl_cert_file.
        with _temporary_ssl_cert_file(certifi.where()):
            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-models",
                model="silero_tts",
                language="ru",
                speaker=model_id,
                trust_repo=True,
            )
        model.to(torch.device("cpu"))
        self._model = model
        #: Читается кэшем: при смене модели старые файлы обязаны стать недействительными.
        self.model_id = model_id

    def synthesize_at_model_rate(self, text: str, voice: str):
        """Звук прямо с модели, на её собственной частоте, без понижения.

        Телефонии это не нужно (Asterisk играет только 8000 Гц), но нужно
        генератору образцов голосов: там звук слушает человек через колонки, а
        не через телефонную линию. Отдельный метод — чтобы генератор не лез в
        приватную модель и не повторял загрузку через torch.hub со всей
        вознёй вокруг сертификатов.

        Отдаёт numpy, а не тензор: это общий контракт всех синтезаторов, и
        генератор образцов не должен знать, torch за движком или onnx.
        """
        return self._model.apply_tts(
            text=text, speaker=voice, sample_rate=MODEL_SAMPLE_RATE_HZ
        ).numpy()

    def synthesize(self, text: str, voice: str) -> bytes:
        return to_telephony_pcm(
            self.synthesize_at_model_rate(text, voice), MODEL_SAMPLE_RATE_HZ
        )


# --- Что Vosk-TTS не выговаривает ------------------------------------------
#
# Преобразователь букв в звуки у Vosk (`vosk_tts.g2p.convert`) знает только
# кириллицу. Слово, которого нет в словаре модели, он разбирает по буквам — и
# на первой же латинской букве или цифре падает с `KeyError`. Не «звучит
# плохо», а именно падает, посреди живого звонка.
#
# Поймано 16.09.2026 при переезде на Vosk: прогрев синтеза на боевой базе
# знаний дал «60 из 62 фраз» — обе потерянные содержали слово Samsung. Проба
# на цифрах и символах роняет синтез так же: «1500», «20%», «№15».
#
# Silero такого не делал, поэтому до переезда проблемы не было и в текстах
# справочника латиница спокойно живёт.
#
# Лечим здесь, а не правкой справочника: аналитик заводит новые записи когда
# угодно и про кириллицу знать не обязан, а цена ошибки — оборванный звонок.

#: Как читать латиницу, которую по буквам не прочитаешь.
#:
#: Побуквенная транслитерация годится далеко не всегда: Samsung так и выйдет
#: «самсунг», а вот Dyson превратится в «дысон» вместо «дайсон», а VPN — в
#: «впн» вместо «ви пи эн». Здесь лежат разборы для того, что реально есть в
#: боевой базе знаний (проверено запросом 16.09.2026), плюс несколько ходовых
#: марок. Слова, которое модель и так знает (LG, Bosch и прочие из её
#: словаря), тут быть не должно — она произнесёт его лучше.
LATIN_READINGS = {
    "samsung": "самсунг",
    "karcher": "кэрхер",
    "dyson": "дайсон",
    "vpn": "ви пи эн",
    "wi-fi": "вай фай",
    "wifi": "вай фай",
    "iphone": "айфон",
    "ipad": "айпад",
    "apple": "эппл",
    "xiaomi": "сяоми",
    "huawei": "хуавэй",
    "honor": "хонор",
    "philips": "филипс",
    "siemens": "сименс",
    "indesit": "индезит",
    "ariston": "аристон",
    "electrolux": "электролюкс",
    "whirlpool": "вирпул",
    "beko": "беко",
    "candy": "канди",
    "haier": "хайер",
    "hansa": "ханза",
    "gorenje": "горенье",
    "lg": "эл джи",
    "e-mail": "имейл",
    "email": "имейл",
    "tv": "тэ вэ",
    "smart": "смарт",
    "sms": "эс эм эс",
    "ok": "окей",
}

#: Побуквенный запасной разбор — чтобы незнакомое слово читалось хоть как-то,
#: а не роняло звонок. Точности тут не ждём: это сеть безопасности, а не
#: способ произношения. Незнакомую марку правильнее добавить в LATIN_READINGS.
_LATIN_LETTERS = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г",
    "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н",
    "o": "о", "p": "п", "q": "ку", "r": "р", "s": "с", "t": "т", "u": "у",
    "v": "в", "w": "в", "x": "кс", "y": "й", "z": "з",
}

_UNITS = ("ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь",
          "восемь", "девять", "десять", "одиннадцать", "двенадцать",
          "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать",
          "семнадцать", "восемнадцать", "девятнадцать")
_TENS = ("", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят",
         "семьдесят", "восемьдесят", "девяносто")
_HUNDREDS = ("", "сто", "двести", "триста", "четыреста", "пятьсот",
             "шестьсот", "семьсот", "восемьсот", "девятьсот")


def _small_number_words(value, feminine=False):
    """Число 0..999 словами. Женский род нужен тысячам: «одна тысяча»."""
    words = []
    if value >= 100:
        words.append(_HUNDREDS[value // 100])
        value %= 100
    if value >= 20:
        words.append(_TENS[value // 10])
        value %= 10
    if value:
        if feminine and value in (1, 2):
            words.append("одна" if value == 1 else "две")
        else:
            words.append(_UNITS[value])
    return words


def _plural(value, forms):
    """Согласование: 1 тысяча, 2 тысячи, 5 тысяч."""
    if value % 100 // 10 == 1:
        return forms[2]
    last = value % 10
    if last == 1:
        return forms[0]
    if last in (2, 3, 4):
        return forms[1]
    return forms[2]


def number_to_words(digits):
    """«1500» -> «одна тысяча пятьсот».

    Читаем числом, а не по цифрам: «один пять ноль ноль» звучит как считалка.
    Длинное число (от миллиарда) читаем всё же по цифрам — это скорее номер
    телефона или заказа, чем количество.
    """
    if len(digits) > 9:
        return " ".join(_UNITS[int(d)] for d in digits)
    value = int(digits)
    if value == 0:
        return "ноль"
    groups = [
        (1000000, ("миллион", "миллиона", "миллионов"), False),
        (1000, ("тысяча", "тысячи", "тысяч"), True),
    ]
    words = []
    for size, forms, feminine in groups:
        count = value // size
        if count:
            words.extend(_small_number_words(count, feminine))
            words.append(_plural(count, forms))
            value %= size
    if value:
        words.extend(_small_number_words(value))
    return " ".join(words)


#: Слова, в которых Vosk ставит ударение не туда. Знак `+` перед ударной
#: гласной модель понимает штатно — это её собственный формат.
#:
#: Разбор записей 17.09.2026 (аналитик КЦ): «ремонт печ+ей» бот произносил как
#: «п+ечей», «ноутб+уков» — как «ноутбук+ов». На слух это звучит как чужой
#: язык и сбивает клиента сильнее, чем кажется.
#:
#: Список растёт по мере прослушивания. Ставить ударение в самом справочнике
#: ERP нельзя: текст там читают и люди, а `+` посреди слова им мешает.
STRESSED_WORDS = {
    "печей": "печ+ей",
    "ноутбуков": "ноутб+уков",
    "шкафов": "шкаф+ов",
    "духовых": "духов+ых",
    "звонков": "звонк+ов",
    "форсунок": "форс+унок",
    "окон": "+окон",
    "мастера": "м+астера",
    "домофонов": "домоф+онов",
    "counters": "counters",
}
STRESSED_WORDS.pop("counters", None)

_WORD_RE = re.compile(r"[а-яёА-ЯЁ]+")


def put_stress_marks(text):
    """Расставить ударения там, где модель ошибается сама."""
    def repl(match):
        word = match.group(0)
        # Регистр не сохраняем: g2p модели всё равно приводит текст к нижнему,
        # а знак ударения стоит перед буквой и заглавную из слова вытесняет.
        return STRESSED_WORDS.get(word.lower(), word)

    return _WORD_RE.sub(repl, text)


#: Что g2p Vosk принимает: кириллица, знак ударения и разделители, по которым
#: он сам режет текст на слова. Всё остальное до него доходить не должно.
_ALLOWED_PUNCTUATION = set(" ,.?!;:\"()-+\n\t")

#: Знаки, которые в этой предметной области встречаются и что-то значат.
#: Просто выбросить их мало: «скидка 20%» превратилась бы в «скидка двадцать».
_SYMBOL_READINGS = {
    "%": " процентов",
    "№": " номер ",
    "+": "+",  # знак ударения самой модели, трогать нельзя
}


def _is_cyrillic(char):
    return "а" <= char.lower() <= "я" or char.lower() == "ё"


def _read_latin(word, known_words):
    """Латинское слово -> как его произнести по-русски."""
    lowered = word.lower()
    if lowered in LATIN_READINGS:
        return LATIN_READINGS[lowered]
    if lowered in known_words:
        return word  # модель знает это слово сама и произнесёт его лучше нас
    log.warning(
        "Слово %r латиницей не разобрано; читаем по буквам. "
        "Марку лучше добавить в LATIN_READINGS (service/tts.py)", word,
    )
    return "".join(_LATIN_LETTERS.get(char, "") for char in lowered)


def normalize_for_vosk(text, known_words=frozenset()):
    """Убрать из текста всё, на чём g2p Vosk падает с KeyError.

    Латиница читается по таблице или по буквам, цифры — числом, прочие знаки
    выбрасываются. Кириллицу и знаки препинания не трогаем: паузы и интонация
    держатся именно на них.
    """
    text = put_stress_marks(text)
    out = []
    buffer = []
    kind = None  # 'latin' | 'digit'

    def flush():
        if not buffer:
            return
        word = "".join(buffer)
        out.append(_read_latin(word, known_words) if kind == "latin"
                   else number_to_words(word))
        del buffer[:]

    for char in text:
        char_kind = ("latin" if ("a" <= char.lower() <= "z")
                     else "digit" if char.isdigit() else None)
        if char_kind:
            if kind and char_kind != kind:
                flush()
            kind = char_kind
            buffer.append(char)
            continue
        # Дефис внутри латинского слова — часть слова (wi-fi), а не разделитель.
        if char == "-" and kind == "latin" and buffer:
            buffer.append(char)
            continue
        flush()
        kind = None
        if _is_cyrillic(char) or char in _ALLOWED_PUNCTUATION:
            out.append(char)
        elif char in _SYMBOL_READINGS:
            out.append(_SYMBOL_READINGS[char])
        elif char == "—":
            out.append("-")  # то же делает сам vosk_tts, но до падения не доходит
        else:
            log.warning("Символ %r синтезу Vosk неизвестен, выброшен", char)
    flush()
    return "".join(out)


class VoskSynthesizer:
    """Vosk-TTS от Alpha Cephei. Боевой синтезатор с 04.09.2026.

    Почему он, а не Silero: модель Silero v5_ru опубликована под CC BY-NC —
    некоммерческой, — а бот работает на боевой линии коммерческой компании
    (разбор лицензий 03.09.2026, UL-17568). У Vosk-TTS лицензия Apache 2.0, и
    на прослушивании 04.09.2026 диктор s3 обошёл по разборчивости всё, что
    было до него, включая тогдашний боевой голос.

    Модель качается отдельно и лежит на диске распакованной (~236 МБ):
    сама библиотека умеет её скачивать, но со станции GitHub недоступен —
    см. AIA_VOSK_TTS_MODEL_PATH.
    """

    #: Дикторы модели ru-0.7-multi в том же порядке, что и в выпадающем списке
    #: группы линий ERP: по разборчивости, лучший первым (замер 04.09.2026 —
    #: s3 49%, s4 42%, s0 41%, s1 40%, s2 37%).
    VOICES = ("s3", "s4", "s0", "s1", "s2")
    DEFAULT_VOICE = "s3"
    #: Своя и другая, не 48000: см. VOSK_SAMPLE_RATE_HZ.
    model_sample_rate = VOSK_SAMPLE_RATE_HZ

    def __init__(self, model_path: str):
        # Путь проверяем до импорта: без него пустая строка уехала бы в
        # библиотеку, и та полезла бы качать модель с GitHub, который со
        # станции недоступен. Ждать сетевого таймаута, чтобы узнать про
        # незаполненную настройку, — не то, что нужно при старте службы.
        if not model_path:
            raise ValueError(
                "Не задан путь к модели Vosk-TTS. Разверните "
                "vosk-model-tts-ru-0.7-multi и укажите папку в "
                "AIA_VOSK_TTS_MODEL_PATH."
            )
        from vosk_tts import Model, Synth

        self._synth = Synth(Model(model_path=model_path))
        #: Словарь произношений самой модели. Слово из него она читает лучше,
        #: чем любая наша транслитерация, — см. normalize_for_vosk.
        self._known_words = self._synth.model.dic
        self.model_id = self.model_id_for(model_path)

    @staticmethod
    def model_id_for(model_path: str) -> str:
        """Читается кэшем: при смене модели старые файлы обязаны стать
        недействительными. Берём имя папки, а не константу «vosk», — иначе
        следующая версия модели молча доиграет звук предыдущей."""
        return "vosk:" + os.path.basename(os.path.normpath(model_path))

    @classmethod
    def speaker_id_of(cls, voice: str) -> int:
        """`s3` -> 3. Незнакомый голос — не повод ронять звонок.

        В `LINE_GROUPS.AI_VOICE` могли остаться имена голосов Silero
        (`kseniya` и подобные): группу линий заводили до смены движка, а
        перенести значение могли и забыть. Падать на этом нельзя — клиент в
        этот момент уже в трубке, — поэтому берём голос по умолчанию и
        говорим об этом в лог погромче, чтобы расхождение нашли и поправили.
        """
        name = (voice or "").strip().lower()
        if name not in cls.VOICES:
            log.warning(
                "Голос %r модели Vosk-TTS неизвестен, говорим голосом %s. "
                "Проверьте AI_VOICE в группе линий: известны %s",
                voice, cls.DEFAULT_VOICE, ", ".join(cls.VOICES),
            )
            name = cls.DEFAULT_VOICE
        return int(name[1:])

    def synthesize_at_model_rate(self, text: str, voice: str):
        import numpy as np

        # Нормализация обязательна, а не «на всякий случай»: на латинице и
        # цифрах g2p Vosk падает с KeyError посреди звонка (см. выше).
        spoken = normalize_for_vosk(text, getattr(self, "_known_words", ()))
        # synth_audio отдаёт int16 на 22050 Гц, а вся дальнейшая обработка
        # (фильтры, нормализация) считается во float в пределах [-1, 1].
        audio = self._synth.synth_audio(spoken, speaker_id=self.speaker_id_of(voice))
        return np.asarray(audio).astype("float32") / 32768.0

    def synthesize(self, text: str, voice: str) -> bytes:
        return to_telephony_pcm(
            self.synthesize_at_model_rate(text, voice), VOSK_SAMPLE_RATE_HZ
        )


def library_key(text: str) -> str:
    """Ключ фразы в библиотеке записанных голосов.

    По тексту, а не по коду записи: у служебных фраз кодов нет, а один и тот
    же уточняющий вопрос у двух записей должен звучать одним файлом. Пробелы и
    регистр не в счёт — аналитик правит текст в ERP руками, и «Здравствуйте, чем
    могу помочь?» с двумя пробелами — та же фраза. Знаки препинания в счёт:
    «да, или нет» и «да... или нет» модель читает по-разному.
    """
    normalized = " ".join(text.split()).lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


class VoiceLibrary:
    """Заранее записанные фразы бота: <корень>/<голос>/<ключ>.wav + index.tsv.

    Файлы — уже телефонный PCM 8 кГц, как выход любого синтезатора: их кладёт
    tools/build_voice_library.py из дублей CosyVoice, отобранных распознаванием.
    index.tsv — «ключ<TAB>текст», по нему библиотека знает, какие фразы у
    голоса есть, без чтения самих файлов; он же нужен человеку, чтобы понять,
    что за файл перед ним.
    """

    INDEX_NAME = "index.tsv"

    def __init__(self, root: str):
        self.root = root
        self._texts: Dict[str, Dict[str, str]] = {}
        digest = hashlib.sha1()
        for voice in sorted(os.listdir(root)) if os.path.isdir(root) else []:
            index_path = os.path.join(root, voice, self.INDEX_NAME)
            if not os.path.isfile(index_path):
                continue
            entries: Dict[str, str] = {}
            with open(index_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.rstrip("\n")
                    if "\t" in line and not line.startswith("#"):
                        key, text = line.split("\t", 1)
                        entries[key.strip()] = text.strip()
            self._texts[voice] = entries
            digest.update(voice.encode("utf-8"))
            for key in sorted(entries):
                digest.update(key.encode("utf-8"))
        # Отпечаток входит в подпись звука: обновили библиотеку — станция
        # скачает файлы заново, иначе она играла бы прежние дубли.
        self.fingerprint = digest.hexdigest()[:12]

    @property
    def voices(self) -> List[str]:
        return list(self._texts)

    def phrase_count(self, voice: str) -> int:
        return len(self._texts.get(voice, {}))

    def path(self, text: str, voice: str) -> Optional[str]:
        """Файл фразы, если она записана этим голосом."""
        key = library_key(text)
        if key not in self._texts.get(voice, {}):
            return None
        path = os.path.join(self.root, voice, key + ".wav")
        return path if os.path.isfile(path) else None

    def missing(self, voice: str, texts: List[str]) -> List[str]:
        """Какие из фраз этим голосом не записаны. Пусто — можно включать голос."""
        return [text for text in texts if self.path(text, voice) is None]


class RecordedSynthesizer:
    """Готовые файлы библиотеки, а чего нет — синтез запасным движком.

    Голос на весь разговор выбирается снаружи (main.effective_voice): группа
    линий получает библиотечный голос только если в библиотеке есть каждая её
    фраза, иначе целиком остаётся на запасном движке. Здесь запасной путь —
    страховка на случай, если фраза всё же не нашлась (например, текст в ERP
    поправили между проверкой и звонком): лучше сказать другим голосом, чем
    промолчать.
    """

    def __init__(self, library: VoiceLibrary, fallback):
        self._library = library
        self._fallback = fallback
        self.model_id = "recorded-{0}+{1}".format(library.fingerprint, getattr(fallback, "model_id", ""))

    @property
    def library(self) -> VoiceLibrary:
        return self._library

    def synthesize(self, text: str, voice: str) -> bytes:
        path = self._library.path(text, voice)
        if path is None:
            if voice in self._library.voices:
                log.warning("Фразы %r нет в библиотеке голоса %s — синтезируем запасным движком", text, voice)
            return self._fallback.synthesize(text, voice)
        with wave.open(path, "rb") as handle:
            return handle.readframes(handle.getnframes())


def create_synthesizer(engine: str, silero_model: str = "", vosk_model_path: str = ""):
    """Синтезатор по имени движка. Боевой — vosk, silero остался запасным."""
    name = (engine or "").strip().lower()
    if name == "vosk":
        return VoskSynthesizer(vosk_model_path)
    if name == "silero":
        return SileroSynthesizer(silero_model or "v4_ru")
    raise ValueError(
        "Неизвестный движок синтеза {0!r}. Известны: vosk, silero".format(engine)
    )


class TtsCache:
    def __init__(self, synthesizer, cache_dir: str):
        self._synthesizer = synthesizer
        self._cache_dir = cache_dir
        self.misses = 0
        os.makedirs(cache_dir, exist_ok=True)

    def _path_for(self, text: str, voice: str) -> str:
        # В ключ входит и модель синтеза, а не только голос с текстом: иначе после
        # смены модели (v4_ru -> v5_ru) кэш продолжает отдавать старый звук, и
        # проверить новую модель на слух попросту невозможно — ровно на это
        # напоролись 13.08.2026 при первом живом звонке.
        #
        # И версия обработки звука — по той же причине, но своей ценой: 31.08.2026
        # её добавили только в подпись для станции. Станция послушно скачала файлы
        # под новыми именами, а сервис отдал ей старый звук из этого кэша, и ни
        # нормализация, ни эквализация не доехали до трубки. Два перезапуска
        # подряд показали «синтез прогрет: 62 из 62 фраз за 0.0 с» — все имена
        # нашлись, значит синтез не запускался вовсе. Кэшей два, и версия нужна
        # в обоих.
        model_id = getattr(self._synthesizer, "model_id", "")
        key = "{0}|{1}|{2}|{3}".format(
            model_id, AUDIO_PIPELINE_VERSION, voice, text).encode("utf-8")
        digest = hashlib.sha1(key).hexdigest()[:16]
        return os.path.join(self._cache_dir, "aia_{0}.wav".format(digest))

    def get(self, text: str, voice: str) -> str:
        path = self._path_for(text, voice)
        if os.path.exists(path):
            return path
        pcm = self._synthesizer.synthesize(text, voice)
        write_wav_8k(path, pcm)
        self.misses += 1
        return path
