-- ======================================================================
-- UL-19020. Прогон 13.10.2026 15:20–15:36: утюги и магазин.
--
--   «Здравствуйте, а утюги ремонтируете?» — корпус тянет в микроволновки
--   (0.545), формулировка «утюги ремонтируете» не дотягивает до планки
--   перебивания корпуса; одиночное «утюги» в ответ на «что вас интересует?»
--   даёт 0.60 — ниже порога. Нужны формы живой речи и одиночные слова.
--   «В магазин» (начало «нужен» срезано линией) — 0.49, переспрос.
--
-- Файл в UTF-8 без BOM. Запускать с NLS_LANG=RUSSIAN_CIS.AL32UTF8.
-- Дублей не создаёт. Проверка: 10 → +7, 61 → +4, 38 → +4, 21 → +4 к текущим.
--   Бренды с ошибками распознавания («дальсон», «перфер», 13.10.2026): варианты как слышит модель.
-- ======================================================================

SET DEFINE OFF;

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 10, v.PHRASE, 0
  FROM (
    SELECT 'утюги' AS PHRASE FROM DUAL UNION ALL
    SELECT 'утюг' FROM DUAL UNION ALL
    SELECT 'а утюги ремонтируете' FROM DUAL UNION ALL
    SELECT 'вы утюги ремонтируете' FROM DUAL UNION ALL
    SELECT 'утюги чините' FROM DUAL UNION ALL
    SELECT 'ремонт утюгов' FROM DUAL UNION ALL
    SELECT 'здравствуйте а утюги ремонтируете' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 10
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 61, v.PHRASE, 0
  FROM (
    SELECT 'в магазин' AS PHRASE FROM DUAL UNION ALL
    SELECT 'магазин' FROM DUAL UNION ALL
    SELECT 'мне нужен магазин' FROM DUAL UNION ALL
    SELECT 'где у вас магазин' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 61
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 38, v.PHRASE, 0
  FROM (
    SELECT 'ремонт техники дальсон' AS PHRASE FROM DUAL UNION ALL
    SELECT 'дальсон не работает' FROM DUAL UNION ALL
    SELECT 'ремонт дайсана' FROM DUAL UNION ALL
    SELECT 'пылесос дайсон сломался' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 38
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 21, v.PHRASE, 0
  FROM (
    SELECT 'перфер не включается' AS PHRASE FROM DUAL UNION ALL
    SELECT 'ремонт перфера' FROM DUAL UNION ALL
    SELECT 'кэрхер не включается' FROM DUAL UNION ALL
    SELECT 'ремонт кэрхера' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 21
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

COMMIT;

SELECT KNOWLEDGE_BASE_ID, COUNT(*) FROM ULTIMA.AI_KB_PHRASES WHERE KNOWLEDGE_BASE_ID IN (10, 61, 38, 21) GROUP BY KNOWLEDGE_BASE_ID ORDER BY 1;
