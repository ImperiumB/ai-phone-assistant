-- ======================================================================
-- UL-19020. Разбивка/расперечисление по пункту Борца (21.10.2026), продолжение
-- sql/25. Спрашивать про то, что назвал клиент, а не списком.
--
--  82  «газовой плиты или газовой духовки» (ТН 2) → 2 записи:
--        82  газовая плита   (ТО 794, как было)
--        нов газовая духовка (ТО 793)
--  24  «насекомых или грызунов, дезинсекция» (ТН 51) → 2 записи:
--        24  насекомые/дезинсекция (ТО 915, как было)
--        нов грызуны/дератизация   (ТО 320 «Плесень, грызуны, деза прочее»)
--  35  «…сантехника, электрика, мебель» — НЕ разбиваем: сантехник (83),
--        электрик (56) и мебель (84) уже есть отдельными записями, а 35 это
--        «мастер на час / мелкий ремонт». Убираем перечисление из вопроса.
--
-- Файл в UTF-8 без BOM. Выполнять целиком. В конце проверки.
-- ======================================================================
SET DEFINE OFF;

-- ---- 82: газовая плита (оставляем) + газовая духовка (новая) ----
UPDATE ULTIMA.AI_KNOWLEDGE_BASE
   SET CLARIFYING_QUESTION = 'Правильно понимаю, что вас интересует ремонт газовой плиты?',
       POSITIVE_REPLY      = 'Соединяю вас со специалистом по ремонту газовых плит, оставайтесь на линии'
 WHERE ID = 82;

INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'газовая духовка не греет',
       'Правильно понимаю, что вас интересует ремонт газовой духовки?',
       'Соединяю вас со специалистом по ремонту газовых духовок, оставайтесь на линии',
       SCENARIO_ID, 793, 0, 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE WHERE ID = 82;

UPDATE ULTIMA.AI_KB_PHRASES
   SET KNOWLEDGE_BASE_ID = (SELECT ID FROM ULTIMA.AI_KNOWLEDGE_BASE WHERE QUESTION = 'газовая духовка не греет')
 WHERE ID IN (694, 696, 699);

-- ---- 24: насекомые (оставляем) + грызуны (новая) ----
UPDATE ULTIMA.AI_KNOWLEDGE_BASE
   SET CLARIFYING_QUESTION = 'Правильно понимаю, что вас интересует обработка от насекомых, дезинсекция?'
 WHERE ID = 24;

INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE)
SELECT (SELECT NVL(MAX(ID), 0) + 1 FROM ULTIMA.AI_KNOWLEDGE_BASE),
       'нужна дератизация от грызунов',
       'Правильно понимаю, что вас интересует обработка от грызунов, дератизация?',
       'Соединяю вас со специалистом по дератизации, оставайтесь на линии',
       SCENARIO_ID, 320, 0, 0
  FROM ULTIMA.AI_KNOWLEDGE_BASE WHERE ID = 24;

UPDATE ULTIMA.AI_KB_PHRASES
   SET KNOWLEDGE_BASE_ID = (SELECT ID FROM ULTIMA.AI_KNOWLEDGE_BASE WHERE QUESTION = 'нужна дератизация от грызунов')
 WHERE ID IN (272, 273, 274, 275, 276, 277, 278);

-- Удаляем перечисляющие фразы записи 24 (они и заставляли спрашивать списком).
DELETE FROM ULTIMA.AI_KB_PHRASES WHERE ID IN (885, 886, 887, 888, 889, 890);

-- ---- 35: убрать перечисление из вопроса (не разбиваем) ----
UPDATE ULTIMA.AI_KNOWLEDGE_BASE
   SET CLARIFYING_QUESTION = 'Правильно понимаю, что вам нужен мастер для мелкого ремонта по дому?'
 WHERE ID = 35;

COMMIT;

-- Проверки
SELECT ID, EQUIPMENT_TYPE_ID AS EQ, CLARIFYING_QUESTION FROM ULTIMA.AI_KNOWLEDGE_BASE
 WHERE ID IN (82, 24, 35) OR QUESTION IN ('газовая духовка не греет', 'нужна дератизация от грызунов') ORDER BY ID;
SELECT KNOWLEDGE_BASE_ID, COUNT(*) FROM ULTIMA.AI_KB_PHRASES
 WHERE KNOWLEDGE_BASE_ID IN (82, 24)
    OR KNOWLEDGE_BASE_ID IN (SELECT ID FROM ULTIMA.AI_KNOWLEDGE_BASE WHERE QUESTION IN ('газовая духовка не греет','нужна дератизация от грызунов'))
 GROUP BY KNOWLEDGE_BASE_ID ORDER BY 1;
SELECT COUNT(*) AS ENUM_LEFT FROM ULTIMA.AI_KB_PHRASES
 WHERE PHRASE LIKE '%насекомых или грызунов%' OR PHRASE LIKE '%газовой плиты или газовой духовки%';
