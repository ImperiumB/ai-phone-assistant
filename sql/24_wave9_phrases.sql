-- ======================================================================
-- UL-19020. Формулировки по разбору 9-й волны (19.10.2026).
--   84 «нужно собрать мебель» (Сборка мебели, ТН 5): 270048783 — «кухонный
--      уголок надо собрать» корпус отнёс к холодильникам (0.79).
--   40 «не работает видеодомофон» (Установка видеодомофонов, ТН 54): 270053135 —
--      «установить видеоглазок», «замена видеоглазка» без своих формулировок.
--   56 «снять показания со счетчика» (Электрика, ТН 5): 270051685 — «установить
--      свет в ванной» ушло сантехнику по слову «ванной».
-- Файл в UTF-8 без BOM. Дублей не создаёт. Проверка: 84 → +5, 40 → +7, 56 → +5.
-- ======================================================================
SET DEFINE OFF;

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 84, v.PHRASE, 0
  FROM (
    SELECT 'кухонный уголок' AS PHRASE FROM DUAL UNION ALL
    SELECT 'собрать кухонный уголок' FROM DUAL UNION ALL
    SELECT 'кухонный уголок надо собрать' FROM DUAL UNION ALL
    SELECT 'собрать уголок' FROM DUAL UNION ALL
    SELECT 'сборка кухонного уголка' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 84
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 40, v.PHRASE, 0
  FROM (
    SELECT 'видеоглазок' AS PHRASE FROM DUAL UNION ALL
    SELECT 'видео глазок' FROM DUAL UNION ALL
    SELECT 'установить видеоглазок' FROM DUAL UNION ALL
    SELECT 'установить видео глазок' FROM DUAL UNION ALL
    SELECT 'замена видеоглазка' FROM DUAL UNION ALL
    SELECT 'замена видео глазка' FROM DUAL UNION ALL
    SELECT 'поменять видеоглазок' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 40
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 56, v.PHRASE, 0
  FROM (
    SELECT 'свет в ванной' AS PHRASE FROM DUAL UNION ALL
    SELECT 'установить свет в ванной' FROM DUAL UNION ALL
    SELECT 'провести свет' FROM DUAL UNION ALL
    SELECT 'сделать свет' FROM DUAL UNION ALL
    SELECT 'повесить светильник в ванной' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 56
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

COMMIT;
SELECT KNOWLEDGE_BASE_ID, COUNT(*) FROM ULTIMA.AI_KB_PHRASES WHERE KNOWLEDGE_BASE_ID IN (84, 40, 56) GROUP BY KNOWLEDGE_BASE_ID ORDER BY 1;
