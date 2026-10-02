-- ======================================================================
-- UL-17568. Формулировки «нужен мастер по <техника>» в темах базы знаний.
--
-- Порождён tools/expand_bare_repair.py 20.08.2026.
-- Править руками нельзя: правки затрёт следующая генерация.
--
-- Файл в UTF-8 без BOM. Запускать с NLS_LANG=RUSSIAN_CIS.AL32UTF8,
-- иначе кириллица приедет в справочник мусором.
--
-- ЗАЧЕМ
--   Та же дыра, что и у семейства «ремонт <техника>», найденная тем же
--   замером сразу после его доливки:
--
--     'нужен мастер по холодильникам'  0.7067 -> «посудомоечная машина не моет посуду»
--
--   У посудомойки формулировка «нужен мастер по посудомоечным машинам» есть,
--   у холодильника не было — и клиент, спросивший про холодильник, получал
--   уверенный вопрос про посудомойку. Здесь добавляются недостающие: у
--   большинства тем такая формулировка уже была, дыра осталась ровно у пяти.
--
-- ЧТО ДОБАВЛЯЕТСЯ
--   тем не создаётся ни одной, только формулировки к существующим
--   тем затронуто: 5
--   формулировок:  7
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

-- айфон не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по айфонам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'айфон не включается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по айфонам');

-- нужен ремонт форсунок
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по форсункам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужен ремонт форсунок'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по форсункам');

-- нужно настроить каналы на телевизоре
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по настройке телевизора', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'нужно настроить каналы на телевизоре'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по настройке телевизора');

-- окно не закрывается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по окнам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'окно не закрывается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по окнам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'вызвать мастера по окнам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'окно не закрывается'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'вызвать мастера по окнам');

-- холодильник не морозит
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'нужен мастер по холодильникам', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'холодильник не морозит'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'нужен мастер по холодильникам');
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KB_PHRASES), k.ID, 'вызвать мастера по холодильнику', 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE LOWER(TRIM(REGEXP_REPLACE(k.QUESTION, '[[:space:]]+', ' '))) = 'холодильник не морозит'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = k.ID
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = 'вызвать мастера по холодильнику');

COMMIT;

-- Проверка: сколько коротких формулировок доехало до каждой темы.
SELECT k.QUESTION, COUNT(*) AS КОРОТКИХ_ФРАЗ
  FROM ULTIMA.AI_KNOWLEDGE_BASE k
  JOIN ULTIMA.AI_KB_PHRASES p ON p.KNOWLEDGE_BASE_ID = k.ID
 WHERE LOWER(TRIM(p.PHRASE)) LIKE 'ремонт %'
    OR LOWER(TRIM(p.PHRASE)) LIKE 'отремонтировать %'
 GROUP BY k.QUESTION
 ORDER BY k.QUESTION;
