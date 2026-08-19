-- ======================================================================
-- UL-18819 (подзадача UL-17568). Темы базы знаний по актуальному списку
-- телефонных направлений заказчика.
--
-- Порождён tools/expand_directions.py 19.08.2026.
-- Править руками нельзя: правки затрёт следующая генерация.
--
-- Файл в UTF-8 без BOM. Запускать с NLS_LANG=RUSSIAN_CIS.AL32UTF8,
-- иначе кириллица приедет в справочник мусором.
--
-- ЧТО ДОБАВЛЯЕТСЯ
--   сценариев:    3
--   тем:          8
--   формулировок: 120 — 112 в AI_KB_PHRASES плюс 8 каноничных в самих темах
--
-- ДОБАВЛЯЕТ, А НЕ ПЕРЕСОЗДАЁТ. Существующие записи скрипт не трогает и не
-- удаляет. Коды новых записей берутся как MAX(ID)+1 по каждой таблице:
-- последовательностей и триггеров у этих трёх таблиц нет.
--
-- ИДЕМПОТЕНТЕН. Каждая вставка обёрнута в NOT EXISTS, поэтому повторный
-- запуск не создаёт дублей:
--   сценарий     — если по этому направлению его ещё нет;
--   тема         — если такой же вопрос ещё не заведён;
--   формулировка — если такой же у этой темы ещё нет.
-- Сравнение с точностью до регистра и пробелов. Темы ищутся по тексту
-- вопроса, а не по коду: коды в боевой базе могли разъехаться.
--
-- Вставки идут одной транзакцией, COMMIT один и в самом конце;
-- на любой ошибке — откат.
--
-- НОВЫЕ ТЕМЫ
--   «нужен мастер на час для работ по дому» -> направление 5 «СЭС_разовые», номер приёма 7013
--     тип оборудования 89 «СЭС Мелкий бытовой ремонт (МБР)» (п.2 название совпало, тип есть во вкладке направления)
--     Вкладка направления снимает старое недоразумение: «СЭС_разовые» — это
--     не санобработка, а разовый мелкий бытовой ремонт (МБР, электрика,
--     сантехника, столярка, устранение засоров, сборка мебели, сейфы). В
--     sql/08 направление отложили как двойник дезинсекции — по названию, не
--     заглянув во вкладку; теперь видно, что это отдельная услуга. Номер
--     приёма 7013 уникален. Формулировки называют конкретную работу по дому
--     и ни в одной нет слова «техника»: тема 10 «нужен ремонт мелкой бытовой
--     техники» отличается от «мелкого бытового ремонта» одной перестановкой
--     слов, и подпускать их друг к другу нельзя.
--   «хочу сделать ремонт в квартире под ключ» -> направление 46 «СЭС Проекты», номер приёма 7011
--     тип оборудования 146 «СЭС Капитальный и текущий ремонт (КиТР)» (п.2 название совпало, тип есть во вкладке направления)
--     «Проекты» — это капитальный и текущий ремонт помещений: потолки, полы,
--     ванна и кухня под ключ, плитка, штукатурка, двери, балконы, коттеджи.
--     Обычная просьба клиента голосом. Номер приёма 7011 уникален.
--     Разделитель с темой направления 5 — масштаб работы: там разовая мелочь
--     на час, здесь ремонт помещения целиком, поэтому в каждой формулировке
--     есть либо «под ключ», либо название отделочной работы.
--   «сушильная машина не сушит белье» -> направление 53 «Стиральные машины», номер приёма 7021
--     тип оборудования 405 «Сушильная машина» (п.2 название совпало, тип есть во вкладке направления)
--     Бывшее направление 66 отменено, сушильные машины обслуживает
--     направление 53 «Стиральные машины» — на его вкладке тип «Сушильная
--     машина» и стоит. Отдельная тема, а не формулировки в тему 1, нужна
--     ради уточняющего вопроса: человек с сушилкой должен услышать про
--     сушильную машину, а не про стиральную. Корень «суш» есть в каждой
--     формулировке: без него они уехали бы в тему 1, а «не сушит» без
--     «белья» — в тему 3 про посудомойку. Номер частного мастера у
--     направления 53 — 7057, это направление 82 «ЧМ (СМА/ПМА/СУШ)», где
--     сушильные машины стоят прямо в названии.
--   «не работает техника дайсон» -> направление 27 «БТ-МБТ (ХД/Кофе/УБТ/Пылесосы/Швейки)», номер приёма 7005
--     тип оборудования не проставлен — «Dyson» есть в справочнике (код 907), но на вкладке направления 27 его нет — направление покрывает 10 других типов
--     Бывшее направление 68 отменено, технику Dyson обслуживает направление
--     27 — на его вкладке лежат «Фены, стайлеры, выпрямители Dyson»,
--     «Увлажнители и очистители воздуха Dyson» и «Сушилки для рук Dyson».
--     Тема заводится по бренду, поэтому название бренда — единственный
--     разделитель: без слова «дайсон» формулировка про пылесос ушла бы в
--     тему 9 (направление 55), а про фен — в тему 10. Слово стоит в каждой
--     формулировке, одна оставлена латиницей: распознавание отдаёт и
--     «дайсон», и «dyson».
--   «швейная машинка не шьет» -> направление 27 «БТ-МБТ (ХД/Кофе/УБТ/Пылесосы/Швейки)», номер приёма 7005
--     тип оборудования 252 «Швейные машинки» (п.2 название совпало, тип есть во вкладке направления)
--     Бывшее направление 69 отменено, швейные машинки обслуживает
--     направление 27 — «Швейки» стоят прямо в его названии, а тип «Швейные
--     машинки» есть на вкладке. Перевод от этого не меняется: тема 10 «нужен
--     ремонт мелкой бытовой техники» уводит туда же. Отдельная тема нужна
--     ради уточняющего вопроса — человек со швейной машинкой услышит про
--     швейную машину, а не про мелкую бытовую технику. Две формулировки у
--     темы 10 уже заняты («швейная машинка сломалась», «почините швейную
--     машину»), они здесь не повторяются — но замер показал, что после
--     досылки обе будут попадать на эту тему, а не на свою. Это ровно то,
--     что нужно: перевод у обеих тем один и тот же номер 7005, а уточняющий
--     вопрос становится точнее.
--   «не работает видеодомофон» -> направление 54 «Интернет на дачу», номер приёма 968
--     тип оборудования 922 «Установка видеодомофонов» (п.2 название совпало, тип есть во вкладке направления)
--     Бывшее направление 114 отменено, видеодомофоны обслуживает направление
--     54 «Интернет на дачу» — тип «Установка видеодомофонов» есть на его
--     вкладке рядом с видеонаблюдением и усилением связи. Корень «домофон» в
--     каждой формулировке ни с чем в базе не пересекается, в том числе с
--     темой 27 про интернет на даче, которая работает по этому же
--     направлению.
--   «нужно установить впн» -> направление 21 «ПК и нотбуки», номер приёма 7213
--     тип оборудования 942 «Установка VPN» (п.2 название совпало, тип есть во вкладке направления)
--     Бывшее направление 115 отменено, VPN обслуживает направление 21 «ПК и
--     нотбуки» — на его вкладке лежат и «Установка VPN», и все комплекты.
--     Сокращение «впн» или «vpn» стоит в каждой формулировке: без него
--     просьба про роутер или интернет ушла бы в тему 27 про интернет на
--     даче, а про компьютер — в тему 16, которая работает по этому же
--     направлению. Обе записи слова оставлены намеренно — распознавание
--     отдаёт и кириллицей, и латиницей.
--   «нужно сделать мрт животному» -> направление 106 «Ветцентр МРТ», номер приёма 7209
--     тип оборудования не проставлен — в базе знаний тип не указан
--     В sql/08 направление отложили с формулировкой «готовый кандидат на
--     следующий заход»: не было подтверждено, принимает ли линия звонки
--     клиентов. Подтверждение нашлось в самом справочнике — у направления
--     своя очередь 6193 и на пропущенные звонки, и на заявки с сайта, то
--     есть обращения идут прямо сюда. Номер приёма 7209 уникален.
--     Разделитель с темой 26 «нужен ветеринар на дом» — слово «МРТ» или
--     «томография» в каждой формулировке: названия животных есть и там, и
--     там, и только вид обследования разводит темы.
--
-- НАПРАВЛЕНИЯ, ОТМЕНЁННЫЕ ЗАКАЗЧИКОМ (5):
--   Направлений 66, 68, 69, 114 и 115 в работе больше нет: заказчик
--   отменил их создание, а технику раздал существующим направлениям. Темы
--   всё равно нужны — клиент говорит «сушилка не сушит», и бот обязан это
--   понимать, — поэтому они заведены обычными темами со своим уточняющим
--   вопросом, а сценарий указывает на принимающее направление. Несколько
--   тем на одно направление схема допускает.
--   66 «Сушильные машины» -> обслуживает направление 53 «Стиральные машины»
--   68 «Dyson» -> обслуживает направление 27 «БТ-МБТ (ХД/Кофе/УБТ/Пылесосы/Швейки)»
--   69 «Швейные машины» -> обслуживает направление 27 «БТ-МБТ (ХД/Кофе/УБТ/Пылесосы/Швейки)»
--   114 «Видеодомофоны» -> обслуживает направление 54 «Интернет на дачу»
--   115 «Установка VPN» -> обслуживает направление 21 «ПК и нотбуки»
--
-- НАПРАВЛЕНИЯ СПИСКА, ЗАКРЫТЫЕ ТЕМАМИ (29 из 52):
--   2, 4, 5, 19, 20, 21, 22, 24, 25, 27, 46, 50, 51, 52, 53, 54, 55, 59, 60, 61, 62, 67, 92, 98, 100, 101, 102, 106, 113
--
-- НАПРАВЛЕНИЯ ЧАСТНОГО МАСТЕРА, ТЕМ НЕ ЗАВОДИМ (20):
--   56, 72, 73, 74, 75, 77, 78, 80, 82, 83, 84, 85, 86, 87, 88, 89, 95, 96, 97, 120
--   Частные мастера отдельными темами не заводятся. У обычного направления
--   два номера: обычный PHONE_FOR_WEB_REQ и для частного мастера
--   PHONE_MISSED_RQ_SNGL_MSTR, и второй равен обычному номеру парного
--   направления «ЧМ_*» — например, у направления 25 «ТВ» номер частного
--   мастера 7040, и ровно 7040 — обычный номер направления 73 «ЧМ_ТВ».
--   Звонок с линии частного мастера уходит в его отдел сам: сервис
--   выбирает номер по признаку линии, а не по отдельной теме. Клиент
--   голосом не говорит «я от частного мастера», отличить такую тему от
--   обычной по речи невозможно, а две почти одинаковые темы перехватывали
--   бы звонки друг у друга.
--
-- НАПРАВЛЕНИЯ, ПРОПУЩЕННЫЕ ОСОЗНАННО (3):
--   направление 17 «Сопровождение (redirect)»
--     Служебное направление: это адресат по умолчанию, куда сервис уводит
--     звонок, когда тему не нашли или у найденного направления нет номера
--     приёма. Клиент не просит голосом «переведите на сопровождение»,
--     просить нечего — темы быть не должно.
--   направление 76 «БТ_МБТ_общее (ХД/СМА/ПМА/КОФЕ/ПЛ/)»
--     «БТ_МБТ_общее (ХД/СМА/ПМА/КОФЕ/ПЛ/)» — сборная корзина по крупной и
--     мелкой бытовой технике: холодильники, стиральные, посудомоечные,
--     кофемашины, пылесосы. Каждый из этих видов уже разобран отдельными
--     темами 1, 2, 3, 4, 9 и 10, которые уводят на свои рабочие номера.
--     Вдобавок номер приёма 76 — 7082, тот же, что у направлений 17, 23, 29,
--     31 и 94: перевод по такой теме привёл бы ровно туда же, куда и общий
--     перевод по умолчанию. Тема не дала бы ничего, кроме перехвата звонков
--     у пяти работающих тем.
--   направление 105 «ВЦ МСК»
--     «ВЦ МСК» — ветеринарный центр по Москве, региональная половина уже
--     покрытых ветеринарных услуг: очередь пропущенных звонков 6168 у него
--     та же, что одна из очередей заявок с сайта у направления 98
--     «Ветеринарные услуги», по которому работает тема 26 «нужен ветеринар
--     на дом». Тему различает регион, а не смысл просьбы, и голосом клиент
--     регион не выбирает — две ветеринарные темы просто делили бы звонки
--     между собой.
--
-- -------------------------------------------------------------------
-- СВЕРКА НОМЕРОВ ЧАСТНОГО МАСТЕРА. Ничего не меняет, только отчёт.
-- Скрипт сверяет PHONE_MISSED_RQ_SNGL_MSTR обычного направления с обычным
-- номером PHONE_FOR_WEB_REQ парного направления «ЧМ_*». Расхождения и
-- пустые номера разбирает заказчик: сервис берёт номер по признаку линии,
-- и если номер пуст, звонок частного мастера уйдёт на сопровождение.
-- -------------------------------------------------------------------
-- Номер ЧМ заполнен и пара нашлась (17). Что пара найдена,
-- ещё не значит, что она осмысленна: справочник не мешает увести пылесосы
-- на линию ТВ. Список приведён целиком, смысл проверяет заказчик.
--   2 «Вар/Дух/Электроплиты» -> 7062 -> 85 «ЧМ (ВЭД)»
--   4 «Кондиционеры» -> 7050 -> 56 «ЧМ_СЭС»
--   5 «СЭС_разовые» -> 7050 -> 56 «ЧМ_СЭС»
--   24 «Кофемашины» -> 7061 -> 84 «ЧМ (Кофе)»
--   25 «ТВ» -> 7040 -> 73 «ЧМ_ТВ»
--   27 «БТ-МБТ (ХД/Кофе/УБТ/Пылесосы/Швейки)» -> 7040 -> 73 «ЧМ_ТВ»
--   46 «СЭС Проекты» -> 7056 -> 78 «ЧМ_СЭС проекты»
--   50 «Клининг» -> 7225 -> 120 «ЧМ  Дезинсекция»
--   51 «Дезинсекция» -> 7225 -> 120 «ЧМ  Дезинсекция»
--   52 «Холодильники» -> 7060 -> 83 «ЧМ ХД»
--   53 «Стиральные машины» -> 7057 -> 82 «ЧМ (СМА/ПМА/СУШ)»
--   54 «Интернет на дачу» -> 7156 -> 80 «ЧМ ИНД»
--   55 «Пылесосы» -> 7040 -> 73 «ЧМ_ТВ»
--   60 «Установка БТ» -> 7081 -> 95 «ЧМ УБТ»
--   61 «Посудомоечные машины» -> 7057 -> 82 «ЧМ (СМА/ПМА/СУШ)»
--   62 «Водонагреватели» -> 7080 -> 96 «ЧМ (Водонагреватели)»
--   102 «Karcher» -> 7044 -> 77 «ЧМ_КМТ»
--
-- Номер ЧМ заполнен, а пары нет (12):
--   19 «Iphone» -> 7054
--     ни одно ЧМ-направление не имеет такого обычного номера — звонок
--     частного мастера уйдёт на номер без направления в ERP
--   20 «СиП» -> 7054
--     ни одно ЧМ-направление не имеет такого обычного номера — звонок
--     частного мастера уйдёт на номер без направления в ERP
--   21 «ПК и нотбуки» -> 7053
--     ни одно ЧМ-направление не имеет такого обычного номера — звонок
--     частного мастера уйдёт на номер без направления в ERP
--   22 «Оргтехника» -> 7055
--     ни одно ЧМ-направление не имеет такого обычного номера — звонок
--     частного мастера уйдёт на номер без направления в ERP
--   59 «Проектор» -> 7052
--     ни одно ЧМ-направление не имеет такого обычного номера — звонок
--     частного мастера уйдёт на номер без направления в ERP
--   67 «Ремонт окон» -> 7084
--     ни одно ЧМ-направление не имеет такого обычного номера — звонок
--     частного мастера уйдёт на номер без направления в ERP
--   76 «БТ_МБТ_общее (ХД/СМА/ПМА/КОФЕ/ПЛ/)» -> 7051
--     ни одно ЧМ-направление не имеет такого обычного номера — звонок
--     частного мастера уйдёт на номер без направления в ERP
--   92 «Ремонт Форсунок» -> 7068
--     равен своему же обычному номеру — отдельной линии ЧМ у направления нет
--   98 «Ветеринарные услуги» -> 7119
--     равен своему же обычному номеру — отдельной линии ЧМ у направления нет
--   100 «Samsung» -> 7054
--     ни одно ЧМ-направление не имеет такого обычного номера — звонок
--     частного мастера уйдёт на номер без направления в ERP
--   101 «СВЧ» -> 7052
--     ни одно ЧМ-направление не имеет такого обычного номера — звонок
--     частного мастера уйдёт на номер без направления в ERP
--   113 «Настройка каналов» -> 7216
--     равен своему же обычному номеру — отдельной линии ЧМ у направления нет
--
-- Номер ЧМ не заполнен (3) — звонок частного мастера
-- по этим направлениям уйдёт на сопровождение:
--   17 «Сопровождение (redirect)» (обычный номер: 7082)
--   105 «ВЦ МСК» (обычный номер: 7208)
--   106 «Ветцентр МРТ» (обычный номер: 7209)
--
-- ЧМ-направления, на которые никто не ссылается (8) —
-- ни одно обычное направление не указало их номер как свой номер ЧМ:
--   72 «ЧМ_БТ», номер 7039
--   74 «ЧМ_ПНС», номер 7041
--   75 «ЧМ_Apple», номер 7042
--   86 «ЧМ _», номер 7028
--   87 «ЧМ (почта БТ)», номер 7058
--   88 «ЧМ (почта СЭС)», номер 7059
--   89 «ЧМ_бланки», номер 7064
--   97 «ЧМ (Ремонт окон)», номер 7078
--
-- ОСТАЛОСЬ НЕРЕШЁННЫМ, РАЗБИРАЕТ ЧЕЛОВЕК (1):
--   направление 53 «Стиральные машины»: номер приёма 7021 делят также
--     направления 91 — перевод придёт в одно место, тему проверить руками
-- ======================================================================

SET DEFINE OFF
WHENEVER SQLERROR EXIT FAILURE ROLLBACK


-- Проверка: темы ищутся по тексту вопроса, поэтому вопросы обязаны быть
-- уникальными. Если это не так — досылать нельзя, формулировки уедут не туда.
DECLARE
  v_dups NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_dups FROM (
    SELECT 1
      FROM ULTIMA.AI_KNOWLEDGE_BASE
     GROUP BY LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' ')))
    HAVING COUNT(*) > 1
  );
  IF v_dups > 0 THEN
    RAISE_APPLICATION_ERROR(-20002,
      'В ULTIMA.AI_KNOWLEDGE_BASE есть повторяющиеся вопросы (' || v_dups ||
      ' шт). Досылка отменена, скрипт ничего не менял.');
  END IF;
END;
/


-- ----------------------------------------------------------------------
-- Сценарии. Тип действия 1 — перевод звонка.
-- Номер для перевода здесь не хранится: он берётся из направления.
-- ----------------------------------------------------------------------
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_SCENARIOS), 'СЭС_разовые', 1, 5, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 5);

INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_SCENARIOS), 'СЭС Проекты', 1, 46, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 46);

INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_SCENARIOS), 'Ветцентр МРТ', 1, 106, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 106);


-- ----------------------------------------------------------------------
-- Новые темы базы знаний.
-- ----------------------------------------------------------------------
-- нужен мастер на час для работ по дому
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'нужен мастер на час для работ по дому',
       'Правильно понимаю, что вас интересует вызов мастера для мелкого ремонта по дому — сантехника, электрика, мебель? Ответьте, пожалуйста, да или нет',
       'Соединяю вас со специалистом по мелкому бытовому ремонту, оставайтесь на линии',
       (SELECT MIN(ID) FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 5),
       89, 0, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KNOWLEDGE_BASE
                     WHERE LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому');

-- хочу сделать ремонт в квартире под ключ
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'хочу сделать ремонт в квартире под ключ',
       'Правильно понимаю, что вас интересует ремонт помещения под ключ? Ответьте, пожалуйста, да или нет',
       'Соединяю вас со специалистом по ремонту под ключ, оставайтесь на линии',
       (SELECT MIN(ID) FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 46),
       146, 0, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KNOWLEDGE_BASE
                     WHERE LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ');

-- сушильная машина не сушит белье
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'сушильная машина не сушит белье',
       'Правильно понимаю, что вас интересует ремонт сушильной машины? Ответьте, пожалуйста, да или нет',
       'Соединяю вас со специалистом по ремонту сушильных машин, оставайтесь на линии',
       (SELECT MIN(ID) FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 53),
       405, 0, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KNOWLEDGE_BASE
                     WHERE LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье');

-- не работает техника дайсон
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'не работает техника дайсон',
       'Правильно понимаю, что вас интересует ремонт техники Dyson? Ответьте, пожалуйста, да или нет',
       'Соединяю вас со специалистом по технике Dyson, оставайтесь на линии',
       (SELECT MIN(ID) FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 27),
       NULL, 0, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KNOWLEDGE_BASE
                     WHERE LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон');

-- швейная машинка не шьет
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'швейная машинка не шьет',
       'Правильно понимаю, что вас интересует ремонт швейной машины? Ответьте, пожалуйста, да или нет',
       'Соединяю вас со специалистом по ремонту швейных машин, оставайтесь на линии',
       (SELECT MIN(ID) FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 27),
       252, 0, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KNOWLEDGE_BASE
                     WHERE LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет');

-- не работает видеодомофон
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'не работает видеодомофон',
       'Правильно понимаю, что вас интересует ремонт или установка видеодомофона? Ответьте, пожалуйста, да или нет',
       'Соединяю вас со специалистом по видеодомофонам, оставайтесь на линии',
       (SELECT MIN(ID) FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 54),
       922, 0, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KNOWLEDGE_BASE
                     WHERE LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон');

-- нужно установить впн
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'нужно установить впн',
       'Правильно понимаю, что вас интересует установка и настройка VPN? Ответьте, пожалуйста, да или нет',
       'Соединяю вас со специалистом по установке VPN, оставайтесь на линии',
       (SELECT MIN(ID) FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 21),
       942, 0, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KNOWLEDGE_BASE
                     WHERE LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн');

-- нужно сделать мрт животному
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'нужно сделать мрт животному',
       'Правильно понимаю, что вас интересует запись животного на МРТ? Ответьте, пожалуйста, да или нет',
       'Соединяю вас со специалистом ветцентра по МРТ, оставайтесь на линии',
       (SELECT MIN(ID) FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 106),
       NULL, 0, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KNOWLEDGE_BASE
                     WHERE LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному');


-- ----------------------------------------------------------------------
-- Формулировки. Тема ищется по тексту вопроса: если её нет, вставка
-- просто не найдёт строку и ничего не добавит.
-- ----------------------------------------------------------------------

-- тема: нужен мастер на час для работ по дому
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен сантехник на дом', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен сантехник на дом');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'засорилась раковина на кухне', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'засорилась раковина на кухне');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'течет труба под ванной', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'течет труба под ванной');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужно поменять смеситель', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужно поменять смеситель');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'не работает розетка в комнате', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'не работает розетка в комнате');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен электрик поменять проводку', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен электрик поменять проводку');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужно собрать шкаф', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужно собрать шкаф');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'повесить люстру', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'повесить люстру');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'унитаз подтекает', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'унитаз подтекает');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер на час', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер на час');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужно повесить жалюзи', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужно повесить жалюзи');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'не открывается сейф', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'не открывается сейф');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'просверлить стену и повесить полку', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'просверлить стену и повесить полку');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужно заменить выключатель света', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен мастер на час для работ по дому'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужно заменить выключатель света');

-- тема: хочу сделать ремонт в квартире под ключ
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен ремонт ванной под ключ', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен ремонт ванной под ключ');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу заказать натяжные потолки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу заказать натяжные потолки');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужно положить плитку в ванной', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужно положить плитку в ванной');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сделать ремонт кухни под ключ', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сделать ремонт кухни под ключ');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен капитальный ремонт квартиры', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен капитальный ремонт квартиры');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу выровнять и покрасить стены', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу выровнять и покрасить стены');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужна отделка балкона', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужна отделка балкона');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сколько стоит ремонт комнаты', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сколько стоит ремонт комнаты');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен ремонт офиса под ключ', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен ремонт офиса под ключ');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу перестелить полы в квартире', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу перестелить полы в квартире');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужна механизированная штукатурка стен', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужна механизированная штукатурка стен');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен косметический ремонт коридора', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен косметический ремонт коридора');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу поставить металлическую дверь', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу поставить металлическую дверь');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен ремонт под ключ в коттедже', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу сделать ремонт в квартире под ключ'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен ремонт под ключ в коттедже');

-- тема: сушильная машина не сушит белье
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сушильная машина не сушит', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сушильная машина не сушит');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сушилка для белья сломалась', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сушилка для белья сломалась');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен ремонт сушильной машины', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен ремонт сушильной машины');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сушильная машина не включается', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сушильная машина не включается');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сушильный автомат гудит и не крутит', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сушильный автомат гудит и не крутит');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'белье после сушки остается влажным', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'белье после сушки остается влажным');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сушильная машина выдает ошибку', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сушильная машина выдает ошибку');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'мастера вызвать по сушильной машине', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'мастера вызвать по сушильной машине');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'почините сушильную машину', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'почините сушильную машину');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сушильная машина не греет воздух', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сушильная машина не греет воздух');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сушилка перестала нагревать белье', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сушилка перестала нагревать белье');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте сломалась сушильная машина', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте сломалась сушильная машина');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по сушильным машинам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по сушильным машинам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сушильная машина сильно шумит при работе', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сушильная машина сильно шумит при работе');

-- тема: не работает техника дайсон
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'пылесос дайсон не включается', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'пылесос дайсон не включается');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сломался фен дайсон', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сломался фен дайсон');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'дайсон не держит заряд', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'дайсон не держит заряд');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'пылесос дайсон нужно отремонтировать', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'пылесос дайсон нужно отремонтировать');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'стайлер дайсон перестал работать', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'стайлер дайсон перестал работать');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'дайсон плохо всасывает', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'дайсон плохо всасывает');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'увлажнитель воздуха дайсон не работает', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'увлажнитель воздуха дайсон не работает');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'мастера вызвать по технике дайсон', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'мастера вызвать по технике дайсон');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'почините дайсон пожалуйста', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'почините дайсон пожалуйста');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'аккумулятор дайсона сел и не заряжается', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'аккумулятор дайсона сел и не заряжается');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'выпрямитель дайсон не греется', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'выпрямитель дайсон не греется');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте сломался дайсон', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте сломался дайсон');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по технике дайсон', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по технике дайсон');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сломался пылесос dyson', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сломался пылесос dyson');

-- тема: швейная машинка не шьет
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'швейная машина не шьет', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'швейная машина не шьет');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен ремонт швейной машины', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен ремонт швейной машины');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'швейная машинка не включается', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'швейная машинка не включается');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'швейная машина рвет нитку', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'швейная машина рвет нитку');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'машинка пропускает стежки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'машинка пропускает стежки');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'в швейной машине заклинило челнок', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'в швейной машине заклинило челнок');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'швейная машина не захватывает нижнюю нить', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'швейная машина не захватывает нижнюю нить');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'мастера вызвать по швейной машине', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'мастера вызвать по швейной машине');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'швейная машинка гудит но игла не двигается', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'швейная машинка гудит но игла не двигается');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по швейным машинам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по швейным машинам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сломалась игла в швейной машине', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сломалась игла в швейной машине');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте не работает швейная машинка', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте не работает швейная машинка');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'оверлок перестал работать', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'оверлок перестал работать');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'швейная машина петляет снизу', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'швейная машина петляет снизу');

-- тема: не работает видеодомофон
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужно установить видеодомофон', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужно установить видеодомофон');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'видеодомофон не показывает картинку', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'видеодомофон не показывает картинку');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'домофон не открывает дверь', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'домофон не открывает дверь');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен ремонт видеодомофона', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен ремонт видеодомофона');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'трубка домофона молчит', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'трубка домофона молчит');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'вызывная панель домофона не работает', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'вызывная панель домофона не работает');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'поставить домофон с камерой в квартиру', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'поставить домофон с камерой в квартиру');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'мастера вызвать по домофону', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'мастера вызвать по домофону');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'почините домофон', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'почините домофон');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'видеодомофон не звонит при вызове', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'видеодомофон не звонит при вызове');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по видеодомофонам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по видеодомофонам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте не работает домофон', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте не работает домофон');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу поменять домофон в частном доме', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу поменять домофон в частном доме');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'камера домофона показывает темный экран', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'камера домофона показывает темный экран');

-- тема: нужно установить впн
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужно настроить впн', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужно настроить впн');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу подключить vpn', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу подключить vpn');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'установите мне впн на телефон', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'установите мне впн на телефон');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен впн на компьютер', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен впн на компьютер');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'не работает впн подключение', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'не работает впн подключение');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'подключите vpn на роутер', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'подключите vpn на роутер');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сколько стоит установка впн', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сколько стоит установка впн');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужна помощь с настройкой vpn', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужна помощь с настройкой vpn');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу заказать комплект впн', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу заказать комплект впн');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'мастера вызвать для настройки впн', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'мастера вызвать для настройки впн');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по установке vpn', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по установке vpn');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте нужен впн', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте нужен впн');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'настроить впн на всю квартиру', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'настроить впн на всю квартиру');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'впн перестал подключаться', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно установить впн'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'впн перестал подключаться');

-- тема: нужно сделать мрт животному
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужно мрт собаке', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужно мрт собаке');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу записать кошку на мрт', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу записать кошку на мрт');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сделать томографию животному', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сделать томографию животному');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сколько стоит мрт для собаки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сколько стоит мрт для собаки');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужна магнитно резонансная томография коту', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужна магнитно резонансная томография коту');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'запишите питомца на мрт', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'запишите питомца на мрт');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ветеринар направил на мрт', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ветеринар направил на мрт');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужно мрт позвоночника собаке', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужно мрт позвоночника собаке');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'где сделать мрт животному', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'где сделать мрт животному');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу сделать мрт головы коту', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу сделать мрт головы коту');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужна томография для питомца', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужна томография для питомца');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте нужно мрт для собаки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте нужно мрт для собаки');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'запись на мрт в ветцентр', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'запись на мрт в ветцентр');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужно обследование мрт для кошки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно сделать мрт животному'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужно обследование мрт для кошки');


COMMIT;


-- ----------------------------------------------------------------------
-- Проверка после заливки.
-- ----------------------------------------------------------------------
SELECT (SELECT COUNT(*) FROM ULTIMA.AI_SCENARIOS)      AS SCENARIOS,
       (SELECT COUNT(*) FROM ULTIMA.AI_KNOWLEDGE_BASE) AS RECORDS,
       (SELECT COUNT(*) FROM ULTIMA.AI_KB_PHRASES)     AS PHRASES
  FROM DUAL;
