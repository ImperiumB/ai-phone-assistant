-- Шаг 3: порядок в базе знаний, одна запись на тему (UL-19020, 12.11.2026). Скрипт повторяемый.

-- 1. Прежний вопрос записи остаётся формулировкой, вопрос становится коротким.
INSERT INTO ULTIMA.AI_KB_TO_PHRASES (KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT k.ID, SUBSTR(k.QUESTION, 1, 256), 0 FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE k.ID = 56 AND k.QUESTION <> 'нужен электрик'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_TO_PHRASES p WHERE p.KNOWLEDGE_BASE_ID = k.ID AND p.PHRASE = SUBSTR(k.QUESTION, 1, 256));
UPDATE ULTIMA.AI_KNOWLEDGE_BASE SET QUESTION = 'нужен электрик' WHERE ID = 56;
INSERT INTO ULTIMA.AI_KB_TO_PHRASES (KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT k.ID, SUBSTR(k.QUESTION, 1, 256), 0 FROM ULTIMA.AI_KNOWLEDGE_BASE k
 WHERE k.ID = 177 AND k.QUESTION <> 'нужен ветеринар собаке'
   AND NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_TO_PHRASES p WHERE p.KNOWLEDGE_BASE_ID = k.ID AND p.PHRASE = SUBSTR(k.QUESTION, 1, 256));
UPDATE ULTIMA.AI_KNOWLEDGE_BASE SET QUESTION = 'нужен ветеринар собаке' WHERE ID = 177;

-- 2. Формулировки: тексты дублей и недостающие формы.
INSERT INTO ULTIMA.AI_KB_TO_PHRASES (KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT n.KB, n.PH, 0 FROM (
  SELECT 7 KB, 'ремонт электрического котла' PH FROM DUAL UNION ALL
  SELECT 7, 'электрический котел не работает' FROM DUAL UNION ALL
  SELECT 7, 'электрокотел не греет' FROM DUAL UNION ALL
  SELECT 7, 'ремонт плат электрических котлов' FROM DUAL UNION ALL
  SELECT 7, 'занимаетесь ремонтом электрических котлов' FROM DUAL UNION ALL
  SELECT 33, 'я заказывал сантехника на двенадцать прошу отменить заказ' FROM DUAL UNION ALL
  SELECT 33, 'прошу отменить заказ' FROM DUAL UNION ALL
  SELECT 33, 'отменить заказ' FROM DUAL UNION ALL
  SELECT 39, 'швейная машинка сломалась' FROM DUAL UNION ALL
  SELECT 39, 'почините швейную машину' FROM DUAL UNION ALL
  SELECT 39, 'ремонт бытовой швейной машинки' FROM DUAL UNION ALL
  SELECT 39, 'починить швейную машинку' FROM DUAL UNION ALL
  SELECT 39, 'швейная машинка' FROM DUAL UNION ALL
  SELECT 39, 'ремонт швейных машинок' FROM DUAL UNION ALL
  SELECT 56, 'снять показания со счетчика' FROM DUAL UNION ALL
  SELECT 61, 'переключить на оператора' FROM DUAL UNION ALL
  SELECT 61, 'связь с оператором' FROM DUAL UNION ALL
  SELECT 61, 'человеком говорить хочу' FROM DUAL UNION ALL
  SELECT 61, 'соедините с оператором' FROM DUAL UNION ALL
  SELECT 61, 'позовите человека' FROM DUAL UNION ALL
  SELECT 61, 'не хочу говорить с роботом' FROM DUAL UNION ALL
  SELECT 61, 'дайте живого человека' FROM DUAL UNION ALL
  SELECT 61, 'переведите на оператора' FROM DUAL UNION ALL
  SELECT 61, 'можно с человеком поговорить' FROM DUAL UNION ALL
  SELECT 177, 'мне бы починить собаку' FROM DUAL UNION ALL
  SELECT 177, 'мне бы вылечить собаку' FROM DUAL
) n
WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_TO_PHRASES p WHERE p.KNOWLEDGE_BASE_ID = n.KB AND p.PHRASE = n.PH);

-- 3. Швейные формулировки уходят с записи 10: их тема это запись 39.
DELETE FROM ULTIMA.AI_KB_TO_PHRASES WHERE KNOWLEDGE_BASE_ID = 10 AND PHRASE IN ('швейная машинка сломалась', 'почините швейную машину', 'ремонт швейной машинки', 'ремонт бытовой швейной машинки', 'починить швейную машинку', 'швейная машинка', 'ремонт швейных машинок', 'ремонт бытовой машинки', 'бытовая машинка');

-- 4. Замки.
INSERT INTO ULTIMA.AI_KB_TO_GATES (KNOWLEDGE_BASE_ID, GATE_WORDS)
SELECT n.KB, n.W FROM (
  SELECT 6 KB, 'варочн' W FROM DUAL UNION ALL
  SELECT 7, 'электрокот' FROM DUAL UNION ALL
  SELECT 7, 'электрич котел' FROM DUAL UNION ALL
  SELECT 7, 'электрич котла' FROM DUAL UNION ALL
  SELECT 14, 'проектор' FROM DUAL UNION ALL
  SELECT 18, 'айфон' FROM DUAL UNION ALL
  SELECT 19, 'айпад' FROM DUAL UNION ALL
  SELECT 23, 'стеклопакет' FROM DUAL UNION ALL
  SELECT 25, 'уборк' FROM DUAL UNION ALL
  SELECT 25, 'клининг' FROM DUAL UNION ALL
  SELECT 30, 'форсунк' FROM DUAL UNION ALL
  SELECT 56, 'электрик' FROM DUAL UNION ALL
  SELECT 56, 'розетк' FROM DUAL UNION ALL
  SELECT 56, 'проводк' FROM DUAL UNION ALL
  SELECT 56, 'выключател' FROM DUAL UNION ALL
  SELECT 56, 'светильник' FROM DUAL UNION ALL
  SELECT 56, 'люстр' FROM DUAL UNION ALL
  SELECT 61, 'обращал' FROM DUAL UNION ALL
  SELECT 61, 'звонили' FROM DUAL UNION ALL
  SELECT 61, 'пропущенн' FROM DUAL UNION ALL
  SELECT 82, 'газов плита' FROM DUAL UNION ALL
  SELECT 82, 'газов плиту' FROM DUAL UNION ALL
  SELECT 82, 'газов плиты' FROM DUAL UNION ALL
  SELECT 82, 'газов плите' FROM DUAL UNION ALL
  SELECT 83, 'смесител' FROM DUAL UNION ALL
  SELECT 83, 'унитаз' FROM DUAL UNION ALL
  SELECT 83, 'раковин' FROM DUAL UNION ALL
  SELECT 84, 'мебел' FROM DUAL UNION ALL
  SELECT 101, 'котел' FROM DUAL UNION ALL
  SELECT 101, 'котла' FROM DUAL UNION ALL
  SELECT 101, 'котлы' FROM DUAL UNION ALL
  SELECT 101, 'котлов' FROM DUAL UNION ALL
  SELECT 137, 'электроплит' FROM DUAL UNION ALL
  SELECT 138, 'газов духов' FROM DUAL
) n
WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_TO_GATES g WHERE g.KNOWLEDGE_BASE_ID = n.KB AND g.GATE_WORDS = n.W);

-- 5. Дубли рабочих записей и заготовки без темы гасятся (не удаляются: на них ссылается разметка).
UPDATE ULTIMA.AI_KNOWLEDGE_BASE SET NOT_ACTIVE = 1 WHERE ID IN (47, 55, 57, 63, 64, 65, 66, 67, 68, 58, 131);
UPDATE ULTIMA.AI_KNOWLEDGE_BASE SET NOT_ACTIVE = 1 WHERE ID IN (182, 183, 186, 189, 192, 196, 197, 198, 199, 203, 205, 207, 211, 216, 217, 223, 227, 230)
   AND IS_FROM_BOT = 1 AND CLARIFYING_QUESTION IS NULL;

-- 6. Размеченные темы больше не «добавлено ботом».
UPDATE ULTIMA.AI_KNOWLEDGE_BASE SET IS_FROM_BOT = 0 WHERE ID IN (56, 101, 132, 177);

COMMIT;
