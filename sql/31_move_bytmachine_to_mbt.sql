-- ======================================================================
-- UL-19020. Финальная правка по волнам (решение заказчика 23.10.2026):
-- «бытовая машинка» пусть будет мелкой бытовой техникой, а не саппортом.
-- В sql/30 размытую «бытовую машинку» клали в запись оператора #63 (саппорт),
-- но из-за общего «бытов… машинк…» туда же липла «бытовая ШВЕЙНАЯ машинка».
-- Переносим «бытовую машинку» из #63 в #10 (мелкая): тогда и бытовая, и
-- швейная уезжают в мелкую, без перетягивания друг друга.
-- Проверено инъекцией на свежей посылке: обе → мелкая, контроли целы
-- (оператор→саппорт, стиралка→стиралка, водонагреватель→водонагреватель).
-- Файл UTF-8 без BOM. После заливки перегенерить посылку.
-- ======================================================================
SET DEFINE OFF;

-- 1) убрать «бытовую машинку» из записи оператора #63 (это добавляла sql/30)
DELETE FROM ULTIMA.AI_KB_PHRASES
 WHERE KNOWLEDGE_BASE_ID = 63
   AND LOWER(TRIM(REGEXP_REPLACE(PHRASE, '[[:space:]]+', ' '))) IN
       ('ремонт бытовой машинки', 'бытовая машинка', 'ремонт бытовой машинки нужен');

-- 2) положить «бытовую машинку» в мелкую бытовую технику #10
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 10, v.PHRASE, 0
  FROM (
    SELECT 'ремонт бытовой машинки' AS PHRASE FROM DUAL UNION ALL
    SELECT 'бытовая машинка' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 10
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

COMMIT;

-- Проверка после заливки:
-- SELECT KNOWLEDGE_BASE_ID, COUNT(*) FROM ULTIMA.AI_KB_PHRASES
--  WHERE KNOWLEDGE_BASE_ID IN (10,63) GROUP BY KNOWLEDGE_BASE_ID;
