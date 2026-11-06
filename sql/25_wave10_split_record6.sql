-- ======================================================================
-- UL-19020. Разбивка перечисляющей записи на конкретные (пункт Борца 21.10.2026):
-- ассистент должен спрашивать про то, что назвал клиент, а не про всё сразу.
-- ОБРАЗЕЦ на записи 6 (ТН 2). После сверки тем же способом пойдут 82, 24, 35.
--
-- Было: запись 6, ТО «Варочные панели» (355), вопрос
--   «…ремонт варочной панели, духового шкафа или электроплиты?».
-- Станет три записи одного направления 2 (сценарий 6), каждая со своим ТО и
-- конкретным вопросом:
--   6   варочная панель  → ТО 355
--   нов духовой шкаф      → ТО 356
--   нов электроплита      → ТО 357
-- Фразы записи 6 раскидываются по приборам; перечисляющие фразы (859-866)
-- удаляются — именно они и заставляли спрашивать «про всё сразу».
-- Файл в UTF-8 без BOM. Выполнять целиком. В конце проверочные SELECT.
-- ======================================================================
SET DEFINE OFF;

-- 1. Запись 6 перенаводим на варочную панель (ТО не меняется, 355).
UPDATE ULTIMA.AI_KNOWLEDGE_BASE
   SET QUESTION            = 'варочная панель не работает',
       CLARIFYING_QUESTION = 'Правильно понимаю, что вас интересует ремонт варочной панели?',
       POSITIVE_REPLY      = 'Соединяю вас со специалистом по ремонту варочных панелей, оставайтесь на линии'
 WHERE ID = 6;

-- 2. Новая запись: духовой шкаф (ТО 356), то же направление/сценарий, что у 6.
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'духовой шкаф не нагревается',
       'Правильно понимаю, что вас интересует ремонт духового шкафа?',
       'Соединяю вас со специалистом по ремонту духовых шкафов, оставайтесь на линии',
       SCENARIO_ID, 356, 0, 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE WHERE ID = 6;

-- 3. Новая запись: электроплита (ТО 357).
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'электроплита не работает',
       'Правильно понимаю, что вас интересует ремонт электроплиты?',
       'Соединяю вас со специалистом по ремонту электроплит, оставайтесь на линии',
       SCENARIO_ID, 357, 0, 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE WHERE ID = 6;

-- 4. Переносим существующие фразы записи 6 по приборам.
--    Духовой шкаф:
UPDATE ULTIMA.AI_KB_PHRASES
   SET KNOWLEDGE_BASE_ID = (SELECT ID FROM ULTIMA.AI_KNOWLEDGE_BASE WHERE QUESTION = 'духовой шкаф не нагревается')
 WHERE ID IN (62, 65, 68, 71, 393, 594, 595);
--    Электроплита:
UPDATE ULTIMA.AI_KB_PHRASES
   SET KNOWLEDGE_BASE_ID = (SELECT ID FROM ULTIMA.AI_KNOWLEDGE_BASE WHERE QUESTION = 'электроплита не работает')
 WHERE ID IN (61, 63, 67, 69, 394, 395);
--    Варочная панель остаётся на записи 6: фразы 60, 64, 66, 70 не трогаем.

-- 5. Удаляем перечисляющие фразы (они заставляли спрашивать «про всё сразу»).
DELETE FROM ULTIMA.AI_KB_PHRASES WHERE ID IN (859, 861, 862, 863, 864, 865, 866);

COMMIT;

-- Проверки: у трёх записей свои ТО и свои вопросы, перечисляющих фраз нет.
SELECT ID, EQUIPMENT_TYPE_ID, CLARIFYING_QUESTION FROM ULTIMA.AI_KNOWLEDGE_BASE
 WHERE ID = 6 OR QUESTION IN ('духовой шкаф не нагревается', 'электроплита не работает') ORDER BY ID;
SELECT KNOWLEDGE_BASE_ID, COUNT(*) FROM ULTIMA.AI_KB_PHRASES
 WHERE KNOWLEDGE_BASE_ID = 6 OR KNOWLEDGE_BASE_ID IN
   (SELECT ID FROM ULTIMA.AI_KNOWLEDGE_BASE WHERE QUESTION IN ('духовой шкаф не нагревается','электроплита не работает'))
 GROUP BY KNOWLEDGE_BASE_ID ORDER BY 1;
SELECT COUNT(*) AS ENUM_LEFT FROM ULTIMA.AI_KB_PHRASES WHERE PHRASE LIKE '%варочной панели, духового шкафа%';
