-- ======================================================================
-- UL-19020. Бренды как их слышит распознавание на плохой линии (14.10.2026,
-- 1791974722: «ремонт техники апл», «аппл»; 1791974748: «дайса»). Варианты
-- добавлены и в ворота брендов сервиса (BRAND_GATES).
-- Файл в UTF-8 без BOM. Дублей не создаёт. Проверка: 18 → +3, 38 → +2.
-- ======================================================================
SET DEFINE OFF;

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 18, v.PHRASE, 0
  FROM (
    SELECT 'ремонт техники апл' AS PHRASE FROM DUAL UNION ALL
    SELECT 'ремонт техники аппл' FROM DUAL UNION ALL
    SELECT 'техника апл' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 18
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 38, v.PHRASE, 0
  FROM (
    SELECT 'ремонт техники дайса' AS PHRASE FROM DUAL UNION ALL
    SELECT 'ремонт техники дайс' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 38
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

COMMIT;
SELECT KNOWLEDGE_BASE_ID, COUNT(*) FROM ULTIMA.AI_KB_PHRASES WHERE KNOWLEDGE_BASE_ID IN (18, 38) GROUP BY KNOWLEDGE_BASE_ID ORDER BY 1;
