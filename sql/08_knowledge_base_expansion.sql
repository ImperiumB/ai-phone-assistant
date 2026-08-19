-- ======================================================================
-- UL-17568, этап 3. Расширение базы знаний виртуального AI-помощника.
--
-- Порождён tools/expand_knowledge_base.py 19.08.2026.
-- Править руками нельзя: правки затрёт следующая генерация.
--
-- Файл в UTF-8 без BOM. Запускать с NLS_LANG=RUSSIAN_CIS.AL32UTF8,
-- иначе кириллица приедет в справочник мусором.
--
-- ЧТО ДОБАВЛЯЕТСЯ
--   сценариев:    4
--   тем:          4
--   формулировок: 160 — 156 в AI_KB_PHRASES плюс 4 каноничных в самих темах
--     из них к новым темам:        56
--     из них к существующим темам: 100
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
--   «нужен ремонт форсунок» -> направление 92, номер приёма 7068
--     тип оборудования 962 «Ремонт форсунок» (п.2 название совпало, тип есть во вкладке направления)
--     Направление названо однозначно, номер приёма 7068 больше нигде не
--     встречается, на вкладке направления есть тип «Ремонт форсунок». Все
--     формулировки содержат корень «форсун» — перетянуть чужую тему нечем.
--   «хочу пожаловаться на ремонт бытовой техники» -> направление 48, номер приёма 6023
--     тип оборудования не проставлен — в базе знаний тип не указан
--     БТ — выездной ремонт бытовой техники на дому. Номер приёма 6023
--     уникален. Каждая формулировка несёт два признака сразу: слово жалобы и
--     выездной ремонт крупной бытовой техники. Голого «хочу пожаловаться»
--     здесь нет намеренно — см. шапку SQL.
--   «хочу пожаловаться на сервисный центр» -> направление 47, номер приёма 6021
--     тип оборудования не проставлен — в базе знаний тип не указан
--     СЦ — стационарный сервисный центр, куда технику сдают и откуда
--     забирают. Номер приёма 6021 уникален. Разделитель с темой «Жалобы БТ»
--     — не слово жалобы, а способ обслуживания: сюда идут те, кто сдавал
--     технику в сервис, туда — те, к кому приезжал мастер.
--   «вопрос по оформленному заказу на кофемашину или оргтехнику» -> направление 90, номер приёма 7049
--     тип оборудования не проставлен — в базе знаний тип не указан
--     Саппорт — сопровождение уже оформленного заказа, КМТ —
--     копировально-множительная техника, она же оргтехника. Каждая
--     формулировка обязана нести и признак уже оформленного заказа, и
--     название техники: без первого она уедет в темы 4 и 17 про поломку, без
--     второго — в тему 28 про общее сопровождение.
--
-- Направление годится под перевод по одному признаку: непустой номер приёма
-- PHONE_FOR_WEB_REQ. Именно его подставляет боевой астербот (обработчик
-- 13161: redirectExten = telDir[0].PWR). Признак AVAIL_FOR_REDIRECT и поле
-- EXTEN_FOR_REDIRECT_ID в переводе не участвуют — на них не смотрим.
--
-- ОСТАЛОСЬ НЕРЕШЁННЫМ, РАЗБИРАЕТ ЧЕЛОВЕК (1):
--   направление 90 «Саппорт Кофе/КМТ»: номер приёма 7049 делят также
--     направления 13, 35 — перевод придёт в одно место, тему проверить
--     руками
--
-- НАПРАВЛЕНИЯ, ОТЛОЖЕННЫЕ ОСОЗНАННО (6):
--   направление 29 «Саппорт ПНС+Apple» (номер приёма 7082) — Номер приёма
--     7082 делят шесть направлений сразу: 17 «Сопровождение (redirect)», 23
--     «Саппорт БТ», 29, 31 «Аналитики Тест 2», 76 «БТ_МБТ_общее», 94
--     «Сопровождение целевое». Перевод по такой теме приведёт клиента ровно
--     туда же, куда и общий перевод по умолчанию, — отдельная тема не даёт
--     ничего, кроме риска перехватить чужие звонки. ПНС расшифровано (ПК +
--     Ноутбуки + Сети, ULTIMA.EQUIPMENT_TYPES 49), вопрос не в расшифровке,
--     а в номере.
--   направление 91 «Apple Watch» (номер приёма 7021) — Номер приёма 7021
--     совпадает с направлением 53 «Стиральные машины», по которому уже
--     работает тема 1. Тема про часы уводила бы звонки на приём стиральных
--     машин.
--   направление 71 «Саппорт ТВ» (номер приёма 7001) — Номер приёма 7001
--     делят направления 58 «Мониторы» и 59 «Проектор», по которым уже
--     работают темы 15 и 14. Плюс тема 12 про телевизор уже забирает «хочу
--     узнать статус заказа на ремонт телевизора».
--   направление 106 «Ветцентр МРТ» (номер приёма 7209) — Номер приёма 7209
--     уникален, направление клиентское — тема прошла бы. Отложено только
--     потому, что не подтверждено, принимает ли эта линия звонки клиентов
--     напрямую или это канал направлений от ветклиник. Готовый кандидат на
--     следующий заход.
--   направление 108 «Пылесосы» (номер приёма 7073) — Полный дубль
--     направления 55 «Пылесосы» — то же название, тот же номер приёма. Тема
--     9 уже работает по 55.
--   направление 5 «СЭС_разовые» (номер приёма 7013) — Разовая санобработка
--     — то же, что уже покрывает тема 24 «нужна обработка от тараканов» по
--     направлению 51 «Дезинсекция». Две темы на одно и то же начали бы
--     делить звонки между собой.
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
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_SCENARIOS), 'Ремонт Форсунок', 1, 92, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 92);

INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_SCENARIOS), 'Жалобы БТ', 1, 48, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 48);

INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_SCENARIOS), 'Жалобы СЦ', 1, 47, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 47);

INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_SCENARIOS), 'Саппорт Кофе/КМТ', 1, 90, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 90);


-- ----------------------------------------------------------------------
-- Новые темы базы знаний.
-- ----------------------------------------------------------------------
-- нужен ремонт форсунок
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'нужен ремонт форсунок',
       'Правильно я понял, что вас интересует ремонт топливных форсунок? Ответьте, пожалуйста, да или нет',
       'Соединяю вас со специалистом по ремонту форсунок, оставайтесь на линии',
       (SELECT MIN(ID) FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 92),
       962, 0, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KNOWLEDGE_BASE
                     WHERE LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок');

-- хочу пожаловаться на ремонт бытовой техники
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'хочу пожаловаться на ремонт бытовой техники',
       'Правильно я понял, что вы хотите оставить жалобу на ремонт бытовой техники? Ответьте, пожалуйста, да или нет',
       'Соединяю вас с отделом качества по бытовой технике, оставайтесь на линии',
       (SELECT MIN(ID) FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 48),
       NULL, 0, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KNOWLEDGE_BASE
                     WHERE LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники');

-- хочу пожаловаться на сервисный центр
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'хочу пожаловаться на сервисный центр',
       'Правильно я понял, что вы хотите оставить жалобу на работу сервисного центра? Ответьте, пожалуйста, да или нет',
       'Соединяю вас с отделом качества сервисного центра, оставайтесь на линии',
       (SELECT MIN(ID) FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 47),
       NULL, 0, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KNOWLEDGE_BASE
                     WHERE LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр');

-- вопрос по оформленному заказу на кофемашину или оргтехнику
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'вопрос по оформленному заказу на кофемашину или оргтехнику',
       'Правильно я понял, что у вас вопрос по уже оформленному заказу на ремонт кофемашины или оргтехники? Ответьте, пожалуйста, да или нет',
       'Соединяю вас с отделом сопровождения по кофемашинам и оргтехнике, оставайтесь на линии',
       (SELECT MIN(ID) FROM ULTIMA.AI_SCENARIOS WHERE TELEPHONE_DIRECTION_ID = 90),
       NULL, 0, 0
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KNOWLEDGE_BASE
                     WHERE LOWER(TRIM(REGEXP_REPLACE(QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику');


-- ----------------------------------------------------------------------
-- Формулировки. Тема ищется по тексту вопроса: если её нет, вставка
-- просто не найдёт строку и ничего не добавит.
-- ----------------------------------------------------------------------

-- тема: нужен ремонт форсунок
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'форсунки надо почистить', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'форсунки надо почистить');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужна промывка форсунок', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужна промывка форсунок');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте нужна чистка форсунок', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте нужна чистка форсунок');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'форсунки льют топливо', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'форсунки льют топливо');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'замена форсунок на дизеле', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'замена форсунок на дизеле');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужна диагностика форсунок', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужна диагностика форсунок');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'проверить форсунки на стенде', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'проверить форсунки на стенде');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'дизельные форсунки не держат давление', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'дизельные форсунки не держат давление');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'форсунка подтекает соляркой', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'форсунка подтекает соляркой');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен ремонт топливных форсунок', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен ремонт топливных форсунок');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'закоксовались форсунки на двигателе', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'закоксовались форсунки на двигателе');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'отремонтировать форсунки на машине', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'отремонтировать форсунки на машине');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ультразвуковая чистка форсунок', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ультразвуковая чистка форсунок');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сколько стоит переборка форсунок', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сколько стоит переборка форсунок');

-- тема: хочу пожаловаться на ремонт бытовой техники
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу пожаловаться на мастера по стиральной машине', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу пожаловаться на мастера по стиральной машине');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'жалоба на ремонт холодильника', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'жалоба на ремонт холодильника');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте хочу оставить жалобу на мастера по бытовой технике', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте хочу оставить жалобу на мастера по бытовой технике');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'мастер плохо починил стиралку хочу пожаловаться', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'мастер плохо починил стиралку хочу пожаловаться');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'недоволен ремонтом холодильника хочу оставить жалобу', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'недоволен ремонтом холодильника хочу оставить жалобу');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу пожаловаться на качество ремонта бытовой техники', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу пожаловаться на качество ремонта бытовой техники');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'мастер по посудомойке нахамил хочу пожаловаться', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'мастер по посудомойке нахамил хочу пожаловаться');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'жалоба на мастера который чинил плиту', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'жалоба на мастера который чинил плиту');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'с меня взяли лишнее за ремонт стиральной машины это жалоба', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'с меня взяли лишнее за ремонт стиральной машины это жалоба');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу написать жалобу на ремонт кондиционера', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу написать жалобу на ремонт кондиционера');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'мастер сломал холодильник хочу пожаловаться', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'мастер сломал холодильник хочу пожаловаться');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'претензия по ремонту бытовой техники на дому', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'претензия по ремонту бытовой техники на дому');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу пожаловаться на ремонт варочной панели', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт варочной панели');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'жалоба на мастера который приезжал чинить духовку', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на ремонт бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'жалоба на мастера который приезжал чинить духовку');

-- тема: хочу пожаловаться на сервисный центр
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'жалоба на сервисный центр', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'жалоба на сервисный центр');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте хочу пожаловаться на сервисный центр', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте хочу пожаловаться на сервисный центр');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сдал телефон в сервисный центр и недоволен ремонтом', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сдал телефон в сервисный центр и недоволен ремонтом');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'в сервисном центре нахамили хочу оставить жалобу', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'в сервисном центре нахамили хочу оставить жалобу');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'претензия к работе сервисного центра', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'претензия к работе сервисного центра');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу пожаловаться на сроки ремонта в сервисном центре', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сроки ремонта в сервисном центре');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'телефон из сервисного центра вернули нерабочим это жалоба', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'телефон из сервисного центра вернули нерабочим это жалоба');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ноутбук после сервисного центра снова сломался хочу пожаловаться', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ноутбук после сервисного центра снова сломался хочу пожаловаться');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'жалоба на приемщика в сервисном центре', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'жалоба на приемщика в сервисном центре');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сервисный центр задерживает ремонт хочу пожаловаться', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сервисный центр задерживает ремонт хочу пожаловаться');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'недоволен качеством ремонта в сервисном центре', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'недоволен качеством ремонта в сервисном центре');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу оставить жалобу на сотрудника сервисного центра', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу оставить жалобу на сотрудника сервисного центра');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'в сервисном центре потеряли мою технику это жалоба', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'в сервисном центре потеряли мою технику это жалоба');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'жалоба на стоимость ремонта в сервисном центре', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'хочу пожаловаться на сервисный центр'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'жалоба на стоимость ремонта в сервисном центре');

-- тема: вопрос по оформленному заказу на кофемашину или оргтехнику
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу узнать статус заказа на ремонт кофемашины', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу узнать статус заказа на ремонт кофемашины');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте я по заказу на ремонт кофемашины', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте я по заказу на ремонт кофемашины');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'когда приедет мастер по кофемашине заявка уже оформлена', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'когда приедет мастер по кофемашине заявка уже оформлена');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сдал кофемашину в ремонт хочу узнать что с ней', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сдал кофемашину в ремонт хочу узнать что с ней');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'когда будет готова кофемашина которую я сдал в ремонт', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'когда будет готова кофемашина которую я сдал в ремонт');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'уточнить сроки ремонта кофемашины по моей заявке', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'уточнить сроки ремонта кофемашины по моей заявке');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хочу узнать статус заказа на ремонт принтера', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хочу узнать статус заказа на ремонт принтера');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'сдал мфу в ремонт когда смогу забрать', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'сдал мфу в ремонт когда смогу забрать');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'вопрос по оформленной заявке на ремонт оргтехники', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'вопрос по оформленной заявке на ремонт оргтехники');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'когда приедет мастер по принтеру я уже оставлял заявку', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'когда приедет мастер по принтеру я уже оставлял заявку');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'звоню по заказу на обслуживание оргтехники', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'звоню по заказу на обслуживание оргтехники');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'уточнить сроки ремонта принтера по моему заказу', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'уточнить сроки ремонта принтера по моему заказу');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'заявка на ремонт кофемашины оформлена хочу уточнить сроки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'заявка на ремонт кофемашины оформлена хочу уточнить сроки');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'я по поводу своего заказа на ремонт мфу', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'вопрос по оформленному заказу на кофемашину или оргтехнику'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'я по поводу своего заказа на ремонт мфу');

-- тема: стиральная машина не отжимает
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте у меня стиралка не крутит белье', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'стиральная машина не отжимает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте у меня стиралка не крутит белье');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'стиральная машина не набирает воду', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'стиральная машина не отжимает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'стиральная машина не набирает воду');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по стиральным машинам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'стиральная машина не отжимает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по стиральным машинам');

-- тема: холодильник не морозит
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте холодос сломался нужен мастер', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'холодильник не морозит'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте холодос сломался нужен мастер');

-- тема: посудомоечная машина не моет посуду
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте посудомойка не работает', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'посудомоечная машина не моет посуду'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте посудомойка не работает');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'посудомойка не набирает воду', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'посудомоечная машина не моет посуду'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'посудомойка не набирает воду');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по посудомоечным машинам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'посудомоечная машина не моет посуду'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по посудомоечным машинам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'посудомойка не сушит посуду', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'посудомоечная машина не моет посуду'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'посудомойка не сушит посуду');

-- тема: кофемашина не варит кофе
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте кофемашина сломалась', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'кофемашина не варит кофе'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте кофемашина сломалась');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'кофемашина не набирает воду', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'кофемашина не варит кофе'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'кофемашина не набирает воду');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по кофемашинам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'кофемашина не варит кофе'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по кофемашинам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'кофемашина не выдает кофе только воду', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'кофемашина не варит кофе'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'кофемашина не выдает кофе только воду');

-- тема: микроволновка не греет
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте микроволновка сломалась', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'микроволновка не греет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте микроволновка сломалась');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по микроволновкам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'микроволновка не греет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по микроволновкам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'микроволновка гудит очень громко', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'микроволновка не греет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'микроволновка гудит очень громко');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'свч не нагревает еду', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'микроволновка не греет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'свч не нагревает еду');

-- тема: духовка не греет
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте духовка не работает', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'духовка не греет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте духовка не работает');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по электроплитам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'духовка не греет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по электроплитам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'стеклокерамика на плите треснула', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'духовка не греет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'стеклокерамика на плите треснула');

-- тема: водонагреватель не греет воду
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте бойлер не греет', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'водонагреватель не греет воду'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте бойлер не греет');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по водонагревателям', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'водонагреватель не греет воду'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по водонагревателям');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'бойлер очень долго нагревает воду', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'водонагреватель не греет воду'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'бойлер очень долго нагревает воду');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'из бойлера идет ржавая вода', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'водонагреватель не греет воду'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'из бойлера идет ржавая вода');

-- тема: кондиционер не охлаждает
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте кондиционер сломался', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'кондиционер не охлаждает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте кондиционер сломался');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по кондиционерам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'кондиционер не охлаждает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по кондиционерам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'кондиционер капает в комнату', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'кондиционер не охлаждает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'кондиционер капает в комнату');

-- тема: пылесос не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте пылесос сдох', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'пылесос не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте пылесос сдох');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по пылесосам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'пылесос не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по пылесосам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'пылесос плохо всасывает пыль', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'пылесос не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'пылесос плохо всасывает пыль');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'пылесос гудит но не всасывает', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'пылесос не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'пылесос гудит но не всасывает');

-- тема: нужен ремонт мелкой бытовой техники
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте сломалась мелкая бытовая техника', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт мелкой бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте сломалась мелкая бытовая техника');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'соковыжималка не работает', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт мелкой бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'соковыжималка не работает');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'хлебопечка не печет хлеб', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт мелкой бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'хлебопечка не печет хлеб');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'отпариватель для одежды сломался', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт мелкой бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'отпариватель для одежды сломался');

-- тема: нужна установка бытовой техники
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте нужно подключить технику', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужна установка бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте нужно подключить технику');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по установке бытовой техники', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужна установка бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по установке бытовой техники');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'подключить стиральную машину к водопроводу', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужна установка бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'подключить стиральную машину к водопроводу');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'установить и подключить посудомойку', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужна установка бытовой техники'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'установить и подключить посудомойку');

-- тема: телевизор не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте телевизор сломался', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телевизор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте телевизор сломался');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по телевизорам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телевизор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по телевизорам');

-- тема: нужно настроить каналы на телевизоре
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте нужно настроить телеканалы', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно настроить каналы на телевизоре'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте нужно настроить телеканалы');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'каналы показывают с помехами нужна настройка', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно настроить каналы на телевизоре'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'каналы показывают с помехами нужна настройка');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'настроить каналы на новом телевизоре', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно настроить каналы на телевизоре'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'настроить каналы на новом телевизоре');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужно отсортировать каналы по порядку', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно настроить каналы на телевизоре'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужно отсортировать каналы по порядку');

-- тема: проектор не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте проектор сломался', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'проектор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте проектор сломался');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по проекторам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'проектор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по проекторам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'проектор не фокусирует изображение', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'проектор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'проектор не фокусирует изображение');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'проектор перегревается и отключается', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'проектор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'проектор перегревается и отключается');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'на изображении проектора пятна', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'проектор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'на изображении проектора пятна');

-- тема: монитор не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте монитор сломался', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'монитор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте монитор сломался');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по мониторам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'монитор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по мониторам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'на мониторе битые пиксели', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'монитор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'на мониторе битые пиксели');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'монитор пишет нет сигнала', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'монитор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'монитор пишет нет сигнала');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'подсветка монитора не работает', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'монитор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'подсветка монитора не работает');

-- тема: ноутбук не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте ноутбук сломался', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'ноутбук не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте ноутбук сломался');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по ноутбукам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'ноутбук не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по ноутбукам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'залил ноутбук жидкостью', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'ноутбук не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'залил ноутбук жидкостью');

-- тема: принтер не печатает
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте принтер сломался', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'принтер не печатает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте принтер сломался');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по оргтехнике', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'принтер не печатает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по оргтехнике');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'принтер печатает бледно', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'принтер не печатает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'принтер печатает бледно');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'мфу не сканирует на компьютер', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'принтер не печатает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'мфу не сканирует на компьютер');

-- тема: айфон не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте разбил айфон нужен ремонт', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'айфон не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте разбил айфон нужен ремонт');

-- тема: айпад не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте айпад сломался', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'айпад не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте айпад сломался');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по айпадам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'айпад не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по айпадам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'айпад не заряжается от кабеля', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'айпад не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'айпад не заряжается от кабеля');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'тачскрин на айпаде не реагирует', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'айпад не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'тачскрин на айпаде не реагирует');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'айпад греется и быстро разряжается', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'айпад не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'айпад греется и быстро разряжается');

-- тема: телефон самсунг не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте самсунг сломался', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телефон самсунг не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте самсунг сломался');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по самсунгу', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телефон самсунг не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по самсунгу');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'самсунг не видит зарядку', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телефон самсунг не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'самсунг не видит зарядку');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'на самсунге не работает сенсор', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телефон самсунг не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'на самсунге не работает сенсор');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'разбил экран на телефоне самсунг', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телефон самсунг не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'разбил экран на телефоне самсунг');

-- тема: керхер не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте керхер сломался', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'керхер не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте керхер сломался');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по керхеру', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'керхер не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по керхеру');

-- тема: телефон сломался
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте разбил экран на телефоне', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телефон сломался'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте разбил экран на телефоне');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по смартфонам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телефон сломался'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по смартфонам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'планшет андроид не заряжается', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телефон сломался'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'планшет андроид не заряжается');

-- тема: окно не закрывается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте нужен ремонт пластикового окна', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'окно не закрывается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте нужен ремонт пластикового окна');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'окно дует из под уплотнителя', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'окно не закрывается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'окно дует из под уплотнителя');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужно отрегулировать пластиковое окно', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'окно не закрывается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужно отрегулировать пластиковое окно');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'заменить стеклопакет в окне', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'окно не закрывается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'заменить стеклопакет в окне');

-- тема: нужна обработка от тараканов
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте нужна дезинсекция квартиры', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужна обработка от тараканов'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте нужна дезинсекция квартиры');

-- тема: нужна уборка квартиры
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте нужна уборка в квартире', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужна уборка квартиры'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте нужна уборка в квартире');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужна уборка после пожара', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужна уборка квартиры'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужна уборка после пожара');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужна уборка коттеджа', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужна уборка квартиры'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужна уборка коттеджа');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'химчистка ковров на дому', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужна уборка квартиры'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'химчистка ковров на дому');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужна уборка после переезда', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужна уборка квартиры'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужна уборка после переезда');

-- тема: нужен ветеринар на дом
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте нужен ветеринар', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ветеринар на дом'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте нужен ветеринар');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'вызвать ветврача на дом к собаке', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ветеринар на дом'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'вызвать ветврача на дом к собаке');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужна вакцинация кошки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ветеринар на дом'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужна вакцинация кошки');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен ветеринар для попугая', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ветеринар на дом'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен ветеринар для попугая');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужно сдать анализы животному', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ветеринар на дом'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужно сдать анализы животному');

-- тема: нужен интернет на дачу
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте нужен интернет на даче', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен интернет на дачу'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте нужен интернет на даче');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'установить антенну для интернета на даче', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен интернет на дачу'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'установить антенну для интернета на даче');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен интернет в деревне', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен интернет на дачу'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен интернет в деревне');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'настроить роутер на даче', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен интернет на дачу'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'настроить роутер на даче');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен спутниковый интернет за городом', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен интернет на дачу'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен спутниковый интернет за городом');

-- тема: ко мне приезжал мастер но техника снова не работает
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'здравствуйте я по поводу уже оформленной заявки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'ко мне приезжал мастер но техника снова не работает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'здравствуйте я по поводу уже оформленной заявки');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'мастер приезжал но проблема не решилась', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'ко мне приезжал мастер но техника снова не работает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'мастер приезжал но проблема не решилась');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'обращаюсь повторно по своему заказу', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'ко мне приезжал мастер но техника снова не работает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'обращаюсь повторно по своему заказу');


COMMIT;


-- ----------------------------------------------------------------------
-- Проверка после заливки.
-- ----------------------------------------------------------------------
SELECT (SELECT COUNT(*) FROM ULTIMA.AI_SCENARIOS)      AS SCENARIOS,
       (SELECT COUNT(*) FROM ULTIMA.AI_KNOWLEDGE_BASE) AS RECORDS,
       (SELECT COUNT(*) FROM ULTIMA.AI_KB_PHRASES)     AS PHRASES
  FROM DUAL;
