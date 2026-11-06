-- ======================================================================
-- UL-19020. Три неоднозначные фразы из прогона 10 волн (решения заказчика 23.10.2026).
--   «ремонт бытовой швейной машинки» шло в стиралку → в мелкую бытовую (#10).
--     заказчик: «швейную на мелкую, там разберутся».
--   «ремонт бытовой машинки» (размыто, прибор неясен) шло в стиралку → на
--     саппорт: добавляем в запись оператора #63 «соедините с оператором»
--     (сценарий 35, прямой перевод на сопровождение). заказчик: «на саппорт».
--   «проконсультироваться, девушка доверила» — правка НЕ нужна, уже уходит
--     на саппорт (проверено движком).
-- Формы проверены инъекцией на живой базе: цели встают верно, контроли целы
-- (стиральная машина/машинку стиральную остаются в стиралке, «проконсультируйте
-- по электрике» остаётся электриком). Файл UTF-8 без BOM, дублей не создаёт.
-- Проверка: #10 → +5, #63 → +3. После заливки перегенерить посылку.
-- ======================================================================
SET DEFINE OFF;

-- #10 мелкая бытовая техника — швейные машинки
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 10, v.PHRASE, 0
  FROM (
    SELECT 'ремонт швейной машинки' AS PHRASE FROM DUAL UNION ALL
    SELECT 'ремонт бытовой швейной машинки' FROM DUAL UNION ALL
    SELECT 'швейная машинка' FROM DUAL UNION ALL
    SELECT 'ремонт швейных машинок' FROM DUAL UNION ALL
    SELECT 'починить швейную машинку' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 10
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

-- #63 «соедините с оператором» (саппорт) — размытая «бытовая машинка»
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 63, v.PHRASE, 0
  FROM (
    SELECT 'ремонт бытовой машинки' AS PHRASE FROM DUAL UNION ALL
    SELECT 'бытовая машинка' FROM DUAL UNION ALL
    SELECT 'ремонт бытовой машинки нужен' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 63
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

COMMIT;

-- Проверка после заливки:
-- SELECT KNOWLEDGE_BASE_ID, COUNT(*) FROM ULTIMA.AI_KB_PHRASES
--  WHERE KNOWLEDGE_BASE_ID IN (10,63) GROUP BY KNOWLEDGE_BASE_ID;
