-- ======================================================================
-- UL-17568. Фраза при неразборчивом ответе на уточняющий вопрос.
--
-- Произносится, когда на «да или нет» второй раз подряд пришла тишина.
-- Первую пустую попытку бот проглатывает молча — это щелчок в линии, а не
-- ответ. Молчать дальше нельзя: клиент только что ответил на прямой вопрос
-- и решит, что бот сломался. Поймано на живом звонке 18.08.2026, где два
-- «нет» подряд распознались пустотой.
--
-- Значение по умолчанию проставляется тут же, чтобы фраза заработала сразу,
-- не дожидаясь, пока её кто-нибудь заполнит руками. Форма без рода: голос
-- выбирается в справочнике и может быть как женским, так и мужским.
--
-- Колонки добавляются NULLABLE, существующие строки не страдают.
-- Скрипт идемпотентен: колонки создаются, только если их ещё нет.
-- ======================================================================

SET DEFINE OFF

DECLARE
  PROCEDURE add_col(p_name VARCHAR2, p_type VARCHAR2) IS
    v_cnt NUMBER;
  BEGIN
    SELECT COUNT(*) INTO v_cnt FROM ALL_TAB_COLUMNS
     WHERE OWNER = 'ULTIMA' AND TABLE_NAME = 'LINE_GROUPS' AND COLUMN_NAME = p_name;
    IF v_cnt = 0 THEN
      EXECUTE IMMEDIATE 'ALTER TABLE ULTIMA.LINE_GROUPS ADD (' || p_name || ' ' || p_type || ')';
    END IF;
  END;
BEGIN
  add_col('AI_CONFIRM_NOT_HEARD',      'VARCHAR2(256)');
  add_col('AI_CONFIRM_NOT_HEARD_PATH', 'VARCHAR2(256)');
END;
/

-- Значение по умолчанию — только там, где фраза ещё не задана.
UPDATE ULTIMA.LINE_GROUPS
   SET AI_CONFIRM_NOT_HEARD = 'Простите, не слышу вас. Скажите, пожалуйста, да или нет'
 WHERE ID = 9060
   AND AI_CONFIRM_NOT_HEARD IS NULL;

COMMIT;


-- ----------------------------------------------------------------------
-- Проверка: две колонки и заполненная фраза у группы 9060.
-- ----------------------------------------------------------------------
SELECT COLUMN_NAME, DATA_TYPE, DATA_LENGTH
  FROM ALL_TAB_COLUMNS
 WHERE OWNER = 'ULTIMA' AND TABLE_NAME = 'LINE_GROUPS'
   AND COLUMN_NAME LIKE 'AI_CONFIRM_NOT_HEARD%'
 ORDER BY COLUMN_NAME;

SELECT AI_CONFIRM_NOT_HEARD FROM ULTIMA.LINE_GROUPS WHERE ID = 9060;
