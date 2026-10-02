-- ======================================================================
-- UL-17568. Короткие формулировки «ремонт <техника>» в темах базы знаний.
--
-- Порождён tools/expand_bare_repair.py 20.08.2026.
-- Править руками нельзя: правки затрёт следующая генерация.
--
-- Файл в UTF-8 без BOM. Запускать с NLS_LANG=RUSSIAN_CIS.AL32UTF8,
-- иначе кириллица приедет в справочник мусором.
--
-- ЗАЧЕМ
--   Живой звонок 20.08.2026, 16:13: «ремонт стиральной машины» — 0.6768,
--   ниже порога, клиент уехал на сопровождение. Замер показал, что дело не
--   только в пороге: короткий запрос ремонта у четырёх тем забирают себе
--   чужие темы, потому что в их длинных формулировках есть и слово
--   «ремонт», и название техники:
--
--     'ремонт холодильника'  0.7098 -> «хочу пожаловаться на ремонт бытовой техники»
--                            0.6914 -> «холодильник не морозит» (своя тема)
--     'ремонт кофемашины'    0.7270 -> «вопрос по оформленному заказу...»
--                            0.7089 -> «кофемашина не варит кофе» (своя тема)
--     'ремонт ноутбука'      0.6809 -> «хочу пожаловаться на сервисный центр»
--     'ремонт духовки'       0.6848 -> «хочу пожаловаться на ремонт бытовой техники»
--
--   Ни при каком пороге это не чинится: чужая тема выигрывает у своей.
--   Точное короткое совпадение в своей теме забирает такой запрос себе и на
--   чужие запросы не влияет — жалобы по-прежнему уходят в жалобы, там свои
--   слова («жалоба», «пожаловаться», «недоволен»).
--
-- ЧТО ДОБАВЛЯЕТСЯ
--   тем не создаётся ни одной, только формулировки к существующим
--   тем затронуто: 24
--   формулировок:  41
--
-- ДОБАВЛЯЕТ, А НЕ ПЕРЕСОЗДАЁТ. Существующие записи не трогаются.
-- ИДЕМПОТЕНТЕН: каждая вставка обёрнута в NOT EXISTS, повторный запуск
-- дублей не создаёт. Темы ищутся по тексту вопроса, а не по коду.
--
-- Если темы с таким вопросом в базе нет, её формулировки просто не
-- вставятся — молча и без ошибки. Проверить, что доехало, можно запросом в
-- конце файла.
--
-- Вставки идут одной транзакцией, COMMIT один и в самом конце.
-- ======================================================================

SET DEFINE OFF;

-- айпад не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт айпада', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'айпад не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт айпада');

-- айфон не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт айфона', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'айфон не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт айфона');

-- водонагреватель не греет воду
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт водонагревателя', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'водонагреватель не греет воду'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт водонагревателя');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт бойлера', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'водонагреватель не греет воду'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт бойлера');

-- духовка не греет
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт духовки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'духовка не греет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт духовки');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт духового шкафа', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'духовка не греет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт духового шкафа');

-- керхер не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт керхера', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'керхер не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт керхера');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт мойки высокого давления', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'керхер не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт мойки высокого давления');

-- кондиционер не охлаждает
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт кондиционера', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'кондиционер не охлаждает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт кондиционера');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт сплит системы', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'кондиционер не охлаждает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт сплит системы');

-- кофемашина не варит кофе
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт кофемашины', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'кофемашина не варит кофе'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт кофемашины');

-- микроволновка не греет
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт микроволновки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'микроволновка не греет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт микроволновки');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт свч печи', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'микроволновка не греет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт свч печи');

-- монитор не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт монитора', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'монитор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт монитора');

-- не работает видеодомофон
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт видеодомофона', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает видеодомофон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт видеодомофона');

-- не работает техника дайсон
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт дайсона', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт дайсона');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт техники дайсон', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'не работает техника дайсон'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт техники дайсон');

-- ноутбук не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт ноутбука', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'ноутбук не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт ноутбука');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт ноута', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'ноутбук не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт ноута');

-- окно не закрывается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт окна', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'окно не закрывается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт окна');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт окон', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'окно не закрывается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт окон');

-- посудомоечная машина не моет посуду
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт посудомоечной машины', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'посудомоечная машина не моет посуду'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт посудомоечной машины');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт посудомойки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'посудомоечная машина не моет посуду'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт посудомойки');

-- принтер не печатает
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт принтера', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'принтер не печатает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт принтера');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт оргтехники', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'принтер не печатает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт оргтехники');

-- проектор не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт проектора', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'проектор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт проектора');

-- пылесос не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт пылесоса', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'пылесос не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт пылесоса');

-- стиральная машина не отжимает
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт стиральной машины', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'стиральная машина не отжимает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт стиральной машины');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт стиралки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'стиральная машина не отжимает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт стиралки');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'отремонтировать стиральную машину', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'стиральная машина не отжимает'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'отремонтировать стиральную машину');

-- сушильная машина не сушит белье
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт сушильной машины', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт сушильной машины');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт сушилки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'сушильная машина не сушит белье'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт сушилки');

-- телевизор не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт телевизора', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телевизор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт телевизора');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт телека', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телевизор не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт телека');

-- телефон самсунг не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт самсунга', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телефон самсунг не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт самсунга');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт телефона самсунг', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телефон самсунг не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт телефона самсунг');

-- телефон сломался
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт телефона', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телефон сломался'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт телефона');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт смартфона', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'телефон сломался'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт смартфона');

-- холодильник не морозит
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт холодильника', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'холодильник не морозит'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт холодильника');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'отремонтировать холодильник', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'холодильник не морозит'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'отремонтировать холодильник');

-- швейная машинка не шьет
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'ремонт швейной машинки', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'швейная машинка не шьет'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'ремонт швейной машинки');

COMMIT;

-- Проверка: сколько коротких формулировок доехало до каждой темы.
SELECT k.QUESTION, COUNT(*) AS КОРОТКИХ_ФРАЗ
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
  JOIN ULTIMA.AI_KB_PHRASES p ON p.KNOWLEDGE_BASE_ID = k.ID
 WHERE LOWER(TRIM(p.PHRASE)) LIKE 'ремонт %'
    OR LOWER(TRIM(p.PHRASE)) LIKE 'отремонтировать %'
 GROUP BY k.QUESTION
 ORDER BY k.QUESTION;
