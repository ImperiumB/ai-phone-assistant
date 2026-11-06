-- ======================================================================
-- UL-19020. Разбор 6-й волны (06.10.2026): формулировки «оператор»,
-- розетки у электрика, «ок» как согласие.
--
-- Файл в UTF-8 без BOM. Запускать с NLS_LANG=RUSSIAN_CIS.AL32UTF8.
--
-- ЗАЧЕМ
--   269460604, 269464771: клиент говорит «с оператором» / «оператор» —
--   бот просит переформулировать. У записи 61 формулировка «оператор» есть,
--   но эмбеддер даёт для неё лишь 0.67 (запрос и документ кодируются с
--   разными префиксами) — ниже порога перевода без вопроса 0.72. В сервисе
--   добавлено дословное совпадение (knowledge.py, exact), сюда — короткие
--   варианты просьбы, чтобы совпадение срабатывало слово в слово.
--   Тексты, которые уже стоят вопросом у других записей сценария 35
--   («соедините с оператором» — 63, «переведите на оператора» — 67,
--   «позовите человека» — 64 и т.д.), сюда намеренно не включены: одна и
--   та же формулировка у двух записей дословно не решает.
--
--   269464554: «греется розетка, хочу заменить» — корпус верно назвал
--   направление 5, но запись внутри направления выбирается по близости
--   формулировок, и «нужен сантехник» (0.596) обошёл электрика. Розеток у
--   электрика (56) почти нет — одна формулировка.
--
--   269454427: на вопрос про ноутбук клиент ответил «ок» (распознано «ока»),
--   бот переспросил «да или нет», клиент положил трубку. В списках согласия
--   есть «окей», но нет «ок».
--
-- Дублей не создаёт: каждая формулировка вставляется, только если у записи
-- её ещё нет. COMMIT один в конце, проверочный SELECT после него.
-- ======================================================================

SET DEFINE OFF;

-- 61 «с оператором соедините с живым человеком» (сценарий 35, направление 17)
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 61, v.PHRASE, 0
  FROM (
    SELECT 'с оператором' AS PHRASE FROM DUAL UNION ALL
    SELECT 'можно оператора' FROM DUAL UNION ALL
    SELECT 'дайте оператора' FROM DUAL UNION ALL
    SELECT 'оператора пожалуйста' FROM DUAL UNION ALL
    SELECT 'позовите оператора' FROM DUAL UNION ALL
    SELECT 'переключите на оператора' FROM DUAL UNION ALL
    SELECT 'хочу поговорить с оператором' FROM DUAL UNION ALL
    SELECT 'с живым человеком' FROM DUAL UNION ALL
    SELECT 'живого человека' FROM DUAL UNION ALL
    SELECT 'соедините с человеком' FROM DUAL UNION ALL
    SELECT 'хочу поговорить с человеком' FROM DUAL UNION ALL
    SELECT 'переведите на человека' FROM DUAL UNION ALL
    SELECT 'мне нужен человек' FROM DUAL UNION ALL
    SELECT 'менеджера' FROM DUAL UNION ALL
    SELECT 'мне нужен менеджер' FROM DUAL UNION ALL
    SELECT 'с менеджером' FROM DUAL UNION ALL
    SELECT 'консультанта' FROM DUAL UNION ALL
    SELECT 'с консультантом' FROM DUAL UNION ALL
    SELECT 'соедините с кем нибудь' FROM DUAL UNION ALL
    SELECT 'девушку позовите' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 61
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

-- 56 «снять показания со счетчика» — электрик (сценарий 32, направление 5)
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 56, v.PHRASE, 0
  FROM (
    SELECT 'греется розетка' AS PHRASE FROM DUAL UNION ALL
    SELECT 'заменить розетку' FROM DUAL UNION ALL
    SELECT 'поменять розетку' FROM DUAL UNION ALL
    SELECT 'установить розетку' FROM DUAL UNION ALL
    SELECT 'розетка искрит' FROM DUAL UNION ALL
    SELECT 'розетки не работают' FROM DUAL UNION ALL
    SELECT 'нужно поставить розетки' FROM DUAL UNION ALL
    SELECT 'нет света в квартире' FROM DUAL UNION ALL
    SELECT 'выбивает автомат' FROM DUAL UNION ALL
    SELECT 'пропало электричество' FROM DUAL UNION ALL
    SELECT 'поменять выключатель' FROM DUAL UNION ALL
    SELECT 'установить выключатель' FROM DUAL UNION ALL
    SELECT 'подключить светильник' FROM DUAL UNION ALL
    SELECT 'нужно провести проводку' FROM DUAL UNION ALL
    SELECT 'искрит проводка' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 56
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

-- Согласие «ок» / «ока» (так GigaAM слышит «ок») во всех группах линий.
-- Сейчас списки по 294 символа, лимит поля 1000.
UPDATE ULTIMA.LINE_GROUPS
   SET AI_POSITIVE_ANSWERS = AI_POSITIVE_ANSWERS || CHR(10) || 'ок' || CHR(10) || 'ока'
 WHERE AI_POSITIVE_ANSWERS IS NOT NULL
   AND INSTR(CHR(10) || AI_POSITIVE_ANSWERS || CHR(10), CHR(10) || 'ок' || CHR(10)) = 0;

COMMIT;

-- Проверка: 61 → 28 формулировок, 56 → 27, групп с «ок» → 12.
SELECT KNOWLEDGE_BASE_ID, COUNT(*) FROM ULTIMA.AI_KB_PHRASES WHERE KNOWLEDGE_BASE_ID IN (61, 56) GROUP BY KNOWLEDGE_BASE_ID;
SELECT COUNT(*) FROM ULTIMA.LINE_GROUPS WHERE INSTR(CHR(10) || AI_POSITIVE_ANSWERS || CHR(10), CHR(10) || 'ока' || CHR(10)) > 0;

-- ----------------------------------------------------------------------
-- НЕ ВЫПОЛНЯТЬ без решения, ремонтируем ли утюги и обогреватели.
-- 269456167 (утюг → микроволновка, итог «Не ремонтируем») и 269460604
-- (масляный обогреватель → водонагреватель). В корпусе таких звонков нет
-- (4 и 6 реплик на 56 тысяч), корпус голосует по похожим словам. Если МБТ
-- (запись 10) их берёт — раскомментировать; если нет — нужна отдельная
-- запись «не ремонтируем» на сопровождение, её текст согласовать.
-- ----------------------------------------------------------------------
-- INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
-- SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 10, v.PHRASE, 0
--   FROM (
--     SELECT 'ремонт утюга' AS PHRASE FROM DUAL UNION ALL
--     SELECT 'утюги ремонтируете' FROM DUAL UNION ALL
--     SELECT 'утюг сломался' FROM DUAL UNION ALL
--     SELECT 'парогенератор не работает' FROM DUAL UNION ALL
--     SELECT 'ремонт обогревателя' FROM DUAL UNION ALL
--     SELECT 'масляный обогреватель не греет' FROM DUAL UNION ALL
--     SELECT 'ремонт масляного обогревателя' FROM DUAL UNION ALL
--     SELECT 'обогреватель сломался' FROM DUAL UNION ALL
--     SELECT 'конвектор не работает' FROM DUAL UNION ALL
--     SELECT 'тепловентилятор не греет' FROM DUAL
--   ) v
--  WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
--                     WHERE p.KNOWLEDGE_BASE_ID = 10
--                       AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);
-- COMMIT;
