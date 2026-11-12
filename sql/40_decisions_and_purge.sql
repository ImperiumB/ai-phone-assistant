-- Шаг 3, завершение: решения заказчика по последним заготовкам и удаление всего нерабочего
-- из базы знаний (UL-19020, 12.11.2026). Скрипт повторяемый.
--
-- Решение заказчика (передано руководителем проекта, 12.11.2026 16:37): всё на сопровождение, кроме
-- «кабель для стиральной машины» (в стиральные) и «телемастерская» (в ТВ).
--
-- Решение заказчика 12.11.2026: бот больше не складывает неузнанные реплики в базу знаний
-- (обработчик 15422), а всё нерабочее из справочника удаляется. Остаются только темы.

-- 1. Формулировки в существующие темы.
INSERT INTO ULTIMA.AI_KB_TO_PHRASES (KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT n.KB, n.PH, 0 FROM (
  SELECT 1 KB, 'проконсультироваться по кабелю для стиральной машины' PH FROM DUAL UNION ALL
  SELECT 1, 'кабель для стиральной машины' FROM DUAL UNION ALL
  SELECT 12, 'это телемастерская' FROM DUAL UNION ALL
  SELECT 12, 'телемастерская' FROM DUAL UNION ALL
  SELECT 85, 'вам инженер требуется по ремонту' FROM DUAL UNION ALL
  SELECT 85, 'вам инженера по ремонту требуются' FROM DUAL UNION ALL
  SELECT 85, 'вам требуются инженеры' FROM DUAL UNION ALL
  SELECT 85, 'есть ли у вас вакансии' FROM DUAL UNION ALL
  SELECT 85, 'ищу работу' FROM DUAL
) n
WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_TO_PHRASES p WHERE p.KNOWLEDGE_BASE_ID = n.KB AND p.PHRASE = n.PH);

-- 2. Заготовка 188 «ремонт радиоаппаратуры» становится рабочей записью без уточняющего
--    вопроса: техника и услуги, которые ведём сразу на сопровождение.
UPDATE ULTIMA.AI_KNOWLEDGE_BASE
   SET SCENARIO_ID = 35,
       POSITIVE_REPLY = 'Соединяю вас с отделом сопровождения, оставайтесь на линии',
       IS_FROM_BOT = 0,
       NOT_ACTIVE = 0
 WHERE ID = 188;

INSERT INTO ULTIMA.AI_KB_TO_PHRASES (KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT 188, n.PH, 0 FROM (
  SELECT 'ремонт видеорегистраторов' PH FROM DUAL UNION ALL
  SELECT 'меня интересует ремонт видеорегистраторов' FROM DUAL UNION ALL
  SELECT 'ремонт музыкального центра' FROM DUAL UNION ALL
  SELECT 'музыкальный центр не читает диски' FROM DUAL UNION ALL
  SELECT 'ремонт стереоусилителей' FROM DUAL UNION ALL
  SELECT 'занимаетесь ремонтом стереоусилителей' FROM DUAL UNION ALL
  SELECT 'ремонт акустических систем' FROM DUAL UNION ALL
  SELECT 'вы занимаетесь ремонтом акустических систем' FROM DUAL UNION ALL
  SELECT 'установить электромагнитные замки на калитке' FROM DUAL UNION ALL
  SELECT 'электромагнитный замок' FROM DUAL UNION ALL
  SELECT 'настольные часы' FROM DUAL UNION ALL
  SELECT 'ремонт настольных часов' FROM DUAL
) n
WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_TO_PHRASES p WHERE p.KNOWLEDGE_BASE_ID = 188 AND p.PHRASE = n.PH);

-- 3. Замки: эти слова ведут сразу к человеку (запись без уточняющего вопроса).
INSERT INTO ULTIMA.AI_KB_TO_GATES (KNOWLEDGE_BASE_ID, GATE_WORDS)
SELECT n.KB, n.W FROM (
  SELECT 188 KB, 'видеорегистратор' W FROM DUAL UNION ALL
  SELECT 188, 'радиоаппаратур' FROM DUAL UNION ALL
  SELECT 188, 'стереоусилит' FROM DUAL UNION ALL
  SELECT 188, 'усилител' FROM DUAL UNION ALL
  SELECT 188, 'акустическ' FROM DUAL UNION ALL
  SELECT 188, 'музыкальн центр' FROM DUAL UNION ALL
  SELECT 188, 'электромагнит' FROM DUAL UNION ALL
  SELECT 85, 'ваканс' FROM DUAL UNION ALL
  SELECT 85, 'инженер требу' FROM DUAL
) n
WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_TO_GATES g WHERE g.KNOWLEDGE_BASE_ID = n.KB AND g.GATE_WORDS = n.W);

-- 4. Удаление нерабочего: выключенные записи и неразмеченные заготовки бота.
--    Строки разметки остаются, у них только обнуляется ссылка на удаляемую запись;
--    сам вопрос клиента хранится в строке разметки (RECOGNIZED_TEXT).
UPDATE ULTIMA.AI_REQUEST_REVIEW r
   SET r.KNOWLEDGE_BASE_ID = NULL
 WHERE r.KNOWLEDGE_BASE_ID IN (SELECT k.ID FROM ULTIMA.AI_KNOWLEDGE_BASE k
                                WHERE NVL(k.NOT_ACTIVE, 0) = 1
                                   OR (k.IS_FROM_BOT = 1 AND k.CLARIFYING_QUESTION IS NULL));

DELETE FROM ULTIMA.AI_KB_TO_PHRASES p
 WHERE p.KNOWLEDGE_BASE_ID IN (SELECT k.ID FROM ULTIMA.AI_KNOWLEDGE_BASE k
                                WHERE NVL(k.NOT_ACTIVE, 0) = 1
                                   OR (k.IS_FROM_BOT = 1 AND k.CLARIFYING_QUESTION IS NULL));

DELETE FROM ULTIMA.AI_KB_TO_GATES g
 WHERE g.KNOWLEDGE_BASE_ID IN (SELECT k.ID FROM ULTIMA.AI_KNOWLEDGE_BASE k
                                WHERE NVL(k.NOT_ACTIVE, 0) = 1
                                   OR (k.IS_FROM_BOT = 1 AND k.CLARIFYING_QUESTION IS NULL));

DELETE FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE NVL(k.NOT_ACTIVE, 0) = 1
    OR (k.IS_FROM_BOT = 1 AND k.CLARIFYING_QUESTION IS NULL);

COMMIT;

-- Проверка.
SELECT COUNT(*) AS RECORDS FROM ULTIMA.AI_KNOWLEDGE_BASE;                      -- ждём 55
SELECT COUNT(*) AS NOT_WORKING FROM ULTIMA.AI_KNOWLEDGE_BASE
 WHERE NVL(NOT_ACTIVE, 0) = 1 OR (IS_FROM_BOT = 1 AND CLARIFYING_QUESTION IS NULL);  -- ждём 0
SELECT COUNT(*) AS GATES FROM ULTIMA.AI_KB_TO_GATES;                           -- ждём 102
