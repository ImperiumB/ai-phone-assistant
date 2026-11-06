-- ======================================================================
-- UL-19020. Короткие формы живой речи, не находящие свою запись: сгенерировано
-- tools/short_forms_check.py 13.10.2026 по всем записям базы (387 форм, 99 мимо у 19 записей).
-- Дословное совпадение решает без эмбеддера. Формы с длинной конструкцией через тире
-- и латинские названия брендов убраны (бренды ловят ворота).
-- Файл в UTF-8 без BOM. Запускать с NLS_LANG=RUSSIAN_CIS.AL32UTF8. Дублей не создаёт.
-- ======================================================================
SET DEFINE OFF;

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 4, v.PHRASE, 0
  FROM (
    SELECT 'здравствуйте ремонт кофемашины' AS PHRASE FROM DUAL UNION ALL
    SELECT 'здравствуйте скажите пожалуйста ремонт кофемашины делаете' FROM DUAL UNION ALL
    SELECT 'мне нужен ремонт кофемашины' FROM DUAL UNION ALL
    SELECT 'по поводу ремонт кофемашины' FROM DUAL UNION ALL
    SELECT 'у меня вопрос по ремонт кофемашины' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 4
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 6, v.PHRASE, 0
  FROM (
    SELECT 'а ремонт варочной панели, духового шкафа или электроплиты вы делаете' AS PHRASE FROM DUAL UNION ALL
    SELECT 'здравствуйте ремонт варочной панели, духового шкафа или электроплиты' FROM DUAL UNION ALL
    SELECT 'здравствуйте скажите пожалуйста ремонт варочной панели, духового шкафа или электроплиты делаете' FROM DUAL UNION ALL
    SELECT 'нужно ремонт варочной панели, духового шкафа или электроплиты' FROM DUAL UNION ALL
    SELECT 'по поводу ремонт варочной панели, духового шкафа или электроплиты' FROM DUAL UNION ALL
    SELECT 'ремонт варочной панели, духового шкафа или электроплиты' FROM DUAL UNION ALL
    SELECT 'скажите вы занимаетесь ремонт варочной панели, духового шкафа или электроплиты' FROM DUAL UNION ALL
    SELECT 'у меня вопрос по ремонт варочной панели, духового шкафа или электроплиты' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 6
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 8, v.PHRASE, 0
  FROM (
    SELECT 'скажите вы занимаетесь ремонт кондиционера' AS PHRASE FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 8
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 13, v.PHRASE, 0
  FROM (
    SELECT 'скажите вы занимаетесь настройка телевизионных каналов' AS PHRASE FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 13
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 14, v.PHRASE, 0
  FROM (
    SELECT 'а ремонт проектора вы делаете' AS PHRASE FROM DUAL UNION ALL
    SELECT 'здравствуйте скажите пожалуйста ремонт проектора делаете' FROM DUAL UNION ALL
    SELECT 'скажите вы занимаетесь ремонт проектора' FROM DUAL UNION ALL
    SELECT 'у меня вопрос по ремонт проектора' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 14
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 15, v.PHRASE, 0
  FROM (
    SELECT 'а ремонт монитора вы делаете' AS PHRASE FROM DUAL UNION ALL
    SELECT 'скажите вы занимаетесь ремонт монитора' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 15
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 16, v.PHRASE, 0
  FROM (
    SELECT 'мне нужен ремонт компьютера или ноутбука' AS PHRASE FROM DUAL UNION ALL
    SELECT 'нужно ремонт компьютера или ноутбука' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 16
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 17, v.PHRASE, 0
  FROM (
    SELECT 'а ремонт оргтехники вы делаете' AS PHRASE FROM DUAL UNION ALL
    SELECT 'здравствуйте ремонт оргтехники' FROM DUAL UNION ALL
    SELECT 'здравствуйте скажите пожалуйста ремонт оргтехники делаете' FROM DUAL UNION ALL
    SELECT 'мне нужен ремонт оргтехники' FROM DUAL UNION ALL
    SELECT 'нужно ремонт оргтехники' FROM DUAL UNION ALL
    SELECT 'по поводу ремонт оргтехники' FROM DUAL UNION ALL
    SELECT 'скажите вы занимаетесь ремонт оргтехники' FROM DUAL UNION ALL
    SELECT 'у меня вопрос по ремонт оргтехники' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 17
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 24, v.PHRASE, 0
  FROM (
    SELECT 'а обработка от насекомых или грызунов, дезинсекция вы делаете' AS PHRASE FROM DUAL UNION ALL
    SELECT 'здравствуйте обработка от насекомых или грызунов, дезинсекция' FROM DUAL UNION ALL
    SELECT 'здравствуйте скажите пожалуйста обработка от насекомых или грызунов, дезинсекция делаете' FROM DUAL UNION ALL
    SELECT 'мне нужен обработка от насекомых или грызунов, дезинсекция' FROM DUAL UNION ALL
    SELECT 'обработка от насекомых или грызунов, дезинсекция' FROM DUAL UNION ALL
    SELECT 'скажите вы занимаетесь обработка от насекомых или грызунов, дезинсекция' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 24
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 25, v.PHRASE, 0
  FROM (
    SELECT 'а заказ клининговых услуг вы делаете' AS PHRASE FROM DUAL UNION ALL
    SELECT 'заказ клининговых услуг' FROM DUAL UNION ALL
    SELECT 'здравствуйте заказ клининговых услуг' FROM DUAL UNION ALL
    SELECT 'здравствуйте скажите пожалуйста заказ клининговых услуг делаете' FROM DUAL UNION ALL
    SELECT 'мне нужен заказ клининговых услуг' FROM DUAL UNION ALL
    SELECT 'нужно заказ клининговых услуг' FROM DUAL UNION ALL
    SELECT 'по поводу заказ клининговых услуг' FROM DUAL UNION ALL
    SELECT 'скажите вы занимаетесь заказ клининговых услуг' FROM DUAL UNION ALL
    SELECT 'у меня вопрос по заказ клининговых услуг' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 25
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 26, v.PHRASE, 0
  FROM (
    SELECT 'а ветеринарные услуги вы делаете' AS PHRASE FROM DUAL UNION ALL
    SELECT 'ветеринарные услуги' FROM DUAL UNION ALL
    SELECT 'здравствуйте ветеринарные услуги' FROM DUAL UNION ALL
    SELECT 'здравствуйте скажите пожалуйста ветеринарные услуги делаете' FROM DUAL UNION ALL
    SELECT 'мне нужен ветеринарные услуги' FROM DUAL UNION ALL
    SELECT 'нужно ветеринарные услуги' FROM DUAL UNION ALL
    SELECT 'по поводу ветеринарные услуги' FROM DUAL UNION ALL
    SELECT 'скажите вы занимаетесь ветеринарные услуги' FROM DUAL UNION ALL
    SELECT 'у меня вопрос по ветеринарные услуги' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 26
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 30, v.PHRASE, 0
  FROM (
    SELECT 'а ремонт топливных форсунок вы делаете' AS PHRASE FROM DUAL UNION ALL
    SELECT 'здравствуйте ремонт топливных форсунок' FROM DUAL UNION ALL
    SELECT 'здравствуйте скажите пожалуйста ремонт топливных форсунок делаете' FROM DUAL UNION ALL
    SELECT 'ремонт топливных форсунок' FROM DUAL UNION ALL
    SELECT 'скажите вы занимаетесь ремонт топливных форсунок' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 30
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 36, v.PHRASE, 0
  FROM (
    SELECT 'а ремонт помещения под ключ вы делаете' AS PHRASE FROM DUAL UNION ALL
    SELECT 'ремонт помещения под ключ' FROM DUAL UNION ALL
    SELECT 'скажите вы занимаетесь ремонт помещения под ключ' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 36
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 39, v.PHRASE, 0
  FROM (
    SELECT 'по поводу ремонт швейной машины' AS PHRASE FROM DUAL UNION ALL
    SELECT 'ремонт швейной машины' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 39
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 41, v.PHRASE, 0
  FROM (
    SELECT 'здравствуйте установка и настройка vpn' AS PHRASE FROM DUAL UNION ALL
    SELECT 'у меня вопрос по установка и настройка vpn' FROM DUAL UNION ALL
    SELECT 'установка и настройка vpn' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 41
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT)
SELECT (SELECT NVL(MAX(ID), 0) FROM ULTIMA.AI_KB_PHRASES) + ROWNUM, 42, v.PHRASE, 0
  FROM (
    SELECT 'а запись животного на мрт вы делаете' AS PHRASE FROM DUAL UNION ALL
    SELECT 'запись животного на мрт' FROM DUAL UNION ALL
    SELECT 'здравствуйте запись животного на мрт' FROM DUAL UNION ALL
    SELECT 'здравствуйте скажите пожалуйста запись животного на мрт делаете' FROM DUAL UNION ALL
    SELECT 'нужно запись животного на мрт' FROM DUAL UNION ALL
    SELECT 'по поводу запись животного на мрт' FROM DUAL UNION ALL
    SELECT 'скажите вы занимаетесь запись животного на мрт' FROM DUAL
  ) v
 WHERE NOT EXISTS (SELECT 1 FROM ULTIMA.AI_KB_PHRASES p
                    WHERE p.KNOWLEDGE_BASE_ID = 42
                      AND LOWER(TRIM(REGEXP_REPLACE(p.PHRASE, '[[:space:]]+', ' '))) = v.PHRASE);

COMMIT;

SELECT COUNT(*) FROM ULTIMA.AI_KB_PHRASES;
