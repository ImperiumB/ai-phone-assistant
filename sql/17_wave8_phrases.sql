-- ======================================================================
-- UL-19020. Разбор 8-й волны (12.10.2026): пропущенные, бренды, блендер.
--
-- Файл в UTF-8 без BOM. Запускать с NLS_LANG=RUSSIAN_CIS.AL32UTF8.
--
-- ЗАЧЕМ
--   14:33 «так у меня пропущенный» — клиент перезванивает по пропущенному
--   от нас, бот просит переформулировать (строка 301 ещё 5-й волны).
--   Запись 61 без вопроса: перевод на сопровождение сразу.
--
--   13:34 «техники браун», «блендер марка браун» — ушло в Karcher. Бренд
--   Braun и блендеры — мелкая бытовая техника (запись 10).
--
--   15:49 «ремонт техники эпл» — ушло в Dyson. Apple без названного
--   устройства — айфон (запись 18), самое частое; айпад уточнит оператор.
--
-- Дублей не создаёт. COMMIT один в конце, проверочный SELECT после него.
-- ======================================================================

SET DEFINE OFF;

-- 61 «с оператором соедините с живым человеком» — перезвон по пропущенному
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
    -- 15:06 «купить стиральную машину», 16:39 «надо купить» — покупка не наш профиль, объяснит человек
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

-- 10 «нужен ремонт мелкой бытовой техники» — Braun, блендеры
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 10, v.PHRASE, 0
  FROM (
    SELECT 'ремонт блендера' AS PHRASE FROM DUAL UNION ALL
    SELECT 'блендер браун' FROM DUAL UNION ALL
    SELECT 'ремонт техники браун' FROM DUAL UNION ALL
    SELECT 'техника браун' FROM DUAL UNION ALL
    SELECT 'ремонт миксера' FROM DUAL UNION ALL
    SELECT 'ремонт мясорубки' FROM DUAL UNION ALL
    SELECT 'ремонт кухонного комбайна' FROM DUAL UNION ALL
    SELECT 'кухонный комбайн не работает' FROM DUAL UNION ALL
    SELECT 'ремонт фена' FROM DUAL UNION ALL
    SELECT 'ремонт электрочайника' FROM DUAL UNION ALL
    SELECT 'ремонт мультиварки' FROM DUAL UNION ALL
    -- 6-я волна, 313: длинная фраза про обогреватель корпус тянет в водонагреватели (0.733 < 0.74)
    SELECT 'вы занимаетесь ремонтом обогревателей' FROM DUAL UNION ALL
    SELECT 'ремонт электрообогревателей' FROM DUAL UNION ALL
    SELECT 'масляный электрообогреватель' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 10
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

-- 18 «айфон не включается» — Apple без названного устройства
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 18, v.PHRASE, 0
  FROM (
    SELECT 'ремонт техники эпл' AS PHRASE FROM DUAL UNION ALL
    SELECT 'техника эпл' FROM DUAL UNION ALL
    SELECT 'ремонт эпл' FROM DUAL UNION ALL
    SELECT 'ремонт apple' FROM DUAL UNION ALL
    SELECT 'техника apple' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 18
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

COMMIT;

-- Проверка: 61 → +19, 10 → +14, 18 → +5 к текущим.
SELECT KNOWLEDGE_BASE_ID, COUNT(*) FROM ULTIMA.AI_KB_PHRASES WHERE KNOWLEDGE_BASE_ID IN (61, 10, 18) GROUP BY KNOWLEDGE_BASE_ID ORDER BY 1;

-- ----------------------------------------------------------------------
-- НЕ ВЫПОЛНЯТЬ без решения: газовые котлы (14:59 «мастер по регулированию
-- котла газового» → бот спросил про газовую плиту). Если котлы ведёт
-- направление водонагревателей (запись 7) — раскомментировать; если нет —
-- сказать, куда, и блок переписать.
-- ----------------------------------------------------------------------
-- INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
-- SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 7, v.PHRASE, 0
--   FROM (
--     SELECT 'газовый котел' AS PHRASE FROM DUAL UNION ALL
--     SELECT 'ремонт газового котла' FROM DUAL UNION ALL
--     SELECT 'настройка газового котла' FROM DUAL UNION ALL
--     SELECT 'регулировка газового котла' FROM DUAL UNION ALL
--     SELECT 'котел не греет' FROM DUAL
--   ) v
--  WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
--                     WHERE p.KNOWLEDGE_BASE_ID = 7
--                       AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);
-- COMMIT;
