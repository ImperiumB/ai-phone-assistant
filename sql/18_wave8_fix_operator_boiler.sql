-- ======================================================================
-- UL-19020. Добивка после прогона 13.10.2026: блок записи 61 из sql/17 в базу
-- не попал (в AI_KB_PHRASES нет ни «у меня пропущенный», ни «нужен магазин»),
-- и газовый котёл: «мастер по регулированию котла газового» эмбеддер тянет к
-- «мастер по газовым плитам» (0.70), фразы котла нужны в той же форме.
--
-- Файл в UTF-8 без BOM. Запускать с NLS_LANG=RUSSIAN_CIS.AL32UTF8.
-- Дублей не создаёт. Выполнять ОДНИМ скриптом целиком, после — проверочный
-- SELECT: у 61 должно стать 33 + 19 = 52, у 7 — 22 + 8 = 30.
-- ======================================================================

SET DEFINE OFF;

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 61, v.PHRASE, 0
  FROM (
    SELECT 'у меня пропущенный' AS PHRASE FROM DUAL UNION ALL
    SELECT 'пропущенный звонок' FROM DUAL UNION ALL
    SELECT 'пропущенный от вас' FROM DUAL UNION ALL
    SELECT 'вы мне звонили' FROM DUAL UNION ALL
    SELECT 'мне звонили с этого номера' FROM DUAL UNION ALL
    SELECT 'перезваниваю по пропущенному' FROM DUAL UNION ALL
    SELECT 'кто мне звонил' FROM DUAL UNION ALL
    SELECT 'мне только что звонили' FROM DUAL UNION ALL
    SELECT 'оператора мне' FROM DUAL UNION ALL
    SELECT 'мне оператора' FROM DUAL UNION ALL
    SELECT 'соедините с мастером' FROM DUAL UNION ALL
    SELECT 'хочу поговорить с мастером' FROM DUAL UNION ALL
    SELECT 'хочу купить' FROM DUAL UNION ALL
    SELECT 'купить стиральную машину' FROM DUAL UNION ALL
    SELECT 'купить холодильник' FROM DUAL UNION ALL
    SELECT 'у вас можно купить' FROM DUAL UNION ALL
    SELECT 'продаете ли вы' FROM DUAL UNION ALL
    SELECT 'нужен магазин' FROM DUAL UNION ALL
    SELECT 'покупка техники' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 61
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 7, v.PHRASE, 0
  FROM (
    SELECT 'нужен мастер по газовому котлу' AS PHRASE FROM DUAL UNION ALL
    SELECT 'мастер по регулированию газового котла' FROM DUAL UNION ALL
    SELECT 'регулирование газового котла' FROM DUAL UNION ALL
    SELECT 'мастер по котлам' FROM DUAL UNION ALL
    SELECT 'газовый котел не работает' FROM DUAL UNION ALL
    SELECT 'настроить газовый котел' FROM DUAL UNION ALL
    SELECT 'котел отопления не включается' FROM DUAL UNION ALL
    SELECT 'мастер по газовому котлу на дом' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 7
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

COMMIT;

SELECT KNOWLEDGE_BASE_ID, COUNT(*) FROM ULTIMA.AI_KB_PHRASES WHERE KNOWLEDGE_BASE_ID IN (61, 7) GROUP BY KNOWLEDGE_BASE_ID ORDER BY 1;
