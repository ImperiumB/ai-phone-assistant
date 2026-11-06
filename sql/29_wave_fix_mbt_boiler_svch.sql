-- ======================================================================
-- UL-19020. Правка базы знаний по прогону всех 10 волн (23.10.2026).
-- Широкая запись «мелкая бытовая техника» (#10) перетягивала к себе
-- водонагреватели и микроволновки, а «масляный электрообогреватель»
-- наоборот уходил в водонагреватели (0.733, давний кейс regress_waves).
-- Лечим накоплением формулировок у ВЕРНЫХ записей, как sql/17 и sql/24.
--   #7  Водонагреватели      — «вы водонагреватели ремонтируете» и формы.
--   #5  СВЧ (Микроволновка)  — «ремонт микроволновых печей» (мн.ч.).
--   #10 мелкая бытовая тех.  — масляный электрообогреватель и формы.
-- Файл в UTF-8 без BOM. Дублей не создаёт (NOT EXISTS по нормализованной
-- форме). После заливки перегенерить посылку базы знаний.
-- Проверка: #7 → +5, #5 → +4, #10 → +5.
-- ======================================================================
SET DEFINE OFF;

-- #7 Водонагреватели
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 7, v.PHRASE, 0
  FROM (
    SELECT 'вы водонагреватели ремонтируете' AS PHRASE FROM DUAL UNION ALL
    SELECT 'водонагреватели ремонтируете' FROM DUAL UNION ALL
    SELECT 'ремонт водонагревателей' FROM DUAL UNION ALL
    SELECT 'вы ремонтируете водонагреватели' FROM DUAL UNION ALL
    SELECT 'ремонтируете ли вы водонагреватели' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 7
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

-- #5 СВЧ (Микроволновка)
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 5, v.PHRASE, 0
  FROM (
    SELECT 'ремонт микроволновых печей' AS PHRASE FROM DUAL UNION ALL
    SELECT 'ремонтом микроволновых печей' FROM DUAL UNION ALL
    SELECT 'вы занимаетесь ремонтом микроволновых печей' FROM DUAL UNION ALL
    SELECT 'микроволновые печи' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 5
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

-- #10 мелкая бытовая техника (масляный электрообогреватель уходил в водонагреватели)
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 10, v.PHRASE, 0
  FROM (
    SELECT 'масляный электрообогреватель' AS PHRASE FROM DUAL UNION ALL
    SELECT 'ремонт масляных электрообогревателей' FROM DUAL UNION ALL
    SELECT 'ремонтом масляных электрообогревателей' FROM DUAL UNION ALL
    SELECT 'электрообогреватель' FROM DUAL UNION ALL
    SELECT 'масляный обогреватель' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 10
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

COMMIT;

-- Проверка после заливки:
-- SELECT KNOWLEDGE_BASE_ID, COUNT(*) FROM ULTIMA.AI_KB_PHRASES
--  WHERE KNOWLEDGE_BASE_ID IN (5,7,10) GROUP BY KNOWLEDGE_BASE_ID;
