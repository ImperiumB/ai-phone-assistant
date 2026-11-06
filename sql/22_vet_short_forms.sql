-- ======================================================================
-- UL-19020. Ветеринар: короткие формы (14.10.2026, 1791970647: «нужен ветеринар
-- на дом» распознано как «ветеринарная» — 0.61, ниже порога, два переспроса).
-- Файл в UTF-8 без BOM. Дублей не создаёт. Проверка: 26 → +8 к текущим.
-- ======================================================================
SET DEFINE OFF;

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 26, v.PHRASE, 0
  FROM (
    SELECT 'ветеринар' AS PHRASE FROM DUAL UNION ALL
    SELECT 'ветеринара' FROM DUAL UNION ALL
    SELECT 'ветеринарная' FROM DUAL UNION ALL
    SELECT 'ветеринарный' FROM DUAL UNION ALL
    SELECT 'ветеринар на дом' FROM DUAL UNION ALL
    SELECT 'вызвать ветеринара' FROM DUAL UNION ALL
    SELECT 'ветеринарная помощь' FROM DUAL UNION ALL
    SELECT 'ветеринарная клиника' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 26
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

COMMIT;
SELECT COUNT(*) FROM ULTIMA.AI_KB_PHRASES WHERE KNOWLEDGE_BASE_ID = 26;
