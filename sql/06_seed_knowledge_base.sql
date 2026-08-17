-- ======================================================================
-- UL-17568, этап 2. Перенос базы знаний виртуального AI-помощника
-- в справочники ERP: сценарии, записи, формулировки.
--
-- Порождён tools/export_knowledge_base.py 17.08.2026.
-- Править руками нельзя: правки затрёт следующая генерация.
--
-- Источник данных:   ai_assistant/knowledge_base.json
-- Снимок справочников: tools/erp_dictionaries.json от 2026-08-17 (ULTIMA.EQUIPMENT_TYPES, ULTIMA.TELEPHONE_DIRECTIONS, ULTIMA.TELDDIR_TO_EQUIPTYPES)
--
-- Файл в UTF-8 без BOM. Запускать с NLS_LANG=RUSSIAN_CIS.AL32UTF8,
-- иначе кириллица приедет в справочник мусором.
--
-- Сценариев:    27 (по одному на телефонное направление)
-- Записей:      28
-- Формулировок: 348 — 320 в AI_KB_PHRASES плюс 28 каноничных в самих записях
--
-- ОДНОРАЗОВЫЙ. Скрипт наполняет только пустые справочники: коды записей
-- в нём проставлены числами, и досыпать их поверх ручных правок нельзя —
-- получились бы дубли и чужие ссылки. Первый блок проверяет, что все три
-- таблицы пусты, и если это не так — останавливает выполнение с ORA-20001,
-- ничего не вставив. Поэтому повторный запуск безопасен: он не создаёт
-- дублей, а сообщает, что переносить уже некуда. Вставки идут одной
-- транзакцией, COMMIT один и в самом конце; на любой ошибке — откат.
--
-- Тип оборудования берётся с вкладки «Типы оборудования» телефонного
-- направления (ULTIMA.TELDDIR_TO_EQUIPTYPES). Правила по порядку:
--   п.1 единственный тип во вкладке направления;
--   п.2 название совпало, тип есть во вкладке направления;
--   п.3 иначе пусто.
-- Пусто — это решение, а не недоработка: если направление покрывает два
-- десятка типов, бот не знает, о каком именно речь. В обращении будет
-- «Неизвестное оборудование», человек уточнит.
--
-- ТИП ПРОСТАВЛЕН (15):
--   запись 1 «стиральная машина не отжимает» -> тип 119 «Стиральные машины» (п.2 название совпало, тип есть во вкладке направления)
--   запись 2 «холодильник не морозит» -> тип 116 «Холодильники» (п.2 название совпало, тип есть во вкладке направления)
--   запись 3 «посудомоечная машина не моет посуду» -> тип 135 «Посудомоечные машины» (п.2 название совпало, тип есть во вкладке направления)
--   запись 4 «кофемашина не варит кофе» -> тип 505 «Кофемашины» (п.2 название совпало, тип есть во вкладке направления)
--   запись 7 «водонагреватель не греет воду» -> тип 219 «Водонагреватели» (п.2 название совпало, тип есть во вкладке направления)
--   запись 8 «кондиционер не охлаждает» -> тип 262 «Кондиционеры» (п.2 название совпало, тип есть во вкладке направления)
--   запись 13 «нужно настроить каналы на телевизоре» -> тип 934 «Настройка каналов ТВ» (п.1 единственный тип во вкладке направления)
--   запись 14 «проектор не включается» -> тип 43 «Проектор» (п.1 единственный тип во вкладке направления)
--   запись 15 «монитор не включается» -> тип 21 «Мониторы» (п.2 название совпало, тип есть во вкладке направления)
--   запись 19 «айпад не включается» -> тип 52 «iPad» (п.2 название совпало, тип есть во вкладке направления)
--   запись 21 «керхер не включается» -> тип 879 «Karcher» (п.2 название совпало, тип есть во вкладке направления)
--   запись 23 «окно не закрывается» -> тип 721 «Ремонт окон (разовые)» (п.1 единственный тип во вкладке направления)
--   запись 24 «нужна обработка от тараканов» -> тип 915 «Дезинсекция» (п.2 название совпало, тип есть во вкладке направления)
--   запись 26 «нужен ветеринар на дом» -> тип 800 «Ветеринарные услуги» (п.2 название совпало, тип есть во вкладке направления)
--   запись 27 «нужен интернет на дачу» -> тип 656 «Интернет на дачу» (п.2 название совпало, тип есть во вкладке направления)
--
-- БЕЗ ТИПА ОБОРУДОВАНИЯ (13) — пройти руками:
--   запись 5 «микроволновка не греет» — «СВЧ»: нет в справочнике
--   запись 6 «духовка не греет» — «Вар/Дух/Электроплиты»: нет в справочнике
--   запись 9 «пылесос не включается» — «Пылесосы»: нет в справочнике
--   запись 10 «нужен ремонт мелкой бытовой техники» — «БТ-МБТ (ХД/Кофе/УБТ/Пылесосы/Швейки)»: нет в справочнике
--   запись 11 «нужна установка бытовой техники» — «Установка БТ»: нет в справочнике
--   запись 12 «телевизор не включается» — «ТВ»: нет в справочнике
--   запись 16 «ноутбук не включается» — «ПК и нотбуки»: нет в справочнике
--   запись 17 «принтер не печатает» — «Оргтехника»: нет в справочнике
--   запись 18 «айфон не включается» — «Iphone»: нет в справочнике
--   запись 20 «телефон самсунг не включается» — «Samsung» есть в справочнике (код 392), но на вкладке направления 100 его нет — направление покрывает 10 других типов
--   запись 22 «телефон сломался» — «СиП»: нет в справочнике
--   запись 25 «нужна уборка квартиры» — «Клининг»: нет в справочнике
--   запись 28 «ко мне приезжал мастер но техника снова не работает» — в базе знаний тип не указан
--
-- ПРОЧЕЕ, РАЗБИРАЕТ ЧЕЛОВЕК (1):
--   запись 28 «ко мне приезжал мастер но техника снова не работает» — сценарий не проставлен: телефонное направление не указано
-- ======================================================================

SET DEFINE OFF
WHENEVER SQLERROR EXIT FAILURE ROLLBACK


-- Проверка: переносим только в пустые справочники.
DECLARE
  v_rows NUMBER;
BEGIN
  SELECT (SELECT COUNT(*) FROM ULTIMA.AI_SCENARIOS)
       + (SELECT COUNT(*) FROM ULTIMA.AI_KNOWLEDGE_BASE)
       + (SELECT COUNT(*) FROM ULTIMA.AI_KB_PHRASES)
    INTO v_rows FROM DUAL;
  IF v_rows > 0 THEN
    RAISE_APPLICATION_ERROR(-20001,
      'Справочники AI-помощника не пусты: перенос уже выполнен или записи'
      || ' заведены руками. Скрипт ничего не менял.');
  END IF;
END;
/


-- ----------------------------------------------------------------------
-- Сценарии. Тип действия 1 — перевод звонка.
-- Номер для перевода здесь не хранится: он берётся из направления.
-- ----------------------------------------------------------------------
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (1, 'Стиральные машины', 1, 53, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (2, 'Холодильники', 1, 52, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (3, 'Посудомоечные машины', 1, 61, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (4, 'Кофемашины', 1, 24, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (5, 'СВЧ', 1, 101, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (6, 'Вар/Дух/Электроплиты', 1, 2, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (7, 'Водонагреватели', 1, 62, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (8, 'Кондиционеры', 1, 4, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (9, 'Пылесосы', 1, 55, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (10, 'БТ-МБТ (ХД/Кофе/УБТ/Пылесосы/Швейки)', 1, 27, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (11, 'Установка БТ', 1, 60, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (12, 'ТВ', 1, 25, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (13, 'Настройка каналов', 1, 113, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (14, 'Проектор', 1, 59, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (15, 'Мониторы', 1, 58, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (16, 'ПК и нотбуки', 1, 21, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (17, 'Оргтехника', 1, 22, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (18, 'Iphone', 1, 19, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (19, 'Ipad', 1, 57, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (20, 'Samsung', 1, 100, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (21, 'Karcher', 1, 102, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (22, 'СиП', 1, 20, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (23, 'Ремонт окон', 1, 67, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (24, 'Дезинсекция', 1, 51, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (25, 'Клининг', 1, 50, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (26, 'Ветеринарные услуги', 1, 98, 0);
INSERT INTO ULTIMA.AI_SCENARIOS (ID, NAME, ACTION_TYPE, TELEPHONE_DIRECTION_ID, NOT_ACTIVE) VALUES (27, 'Интернет на дачу', 1, 54, 0);


-- ----------------------------------------------------------------------
-- Записи базы знаний.
-- ----------------------------------------------------------------------
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (1, 'стиральная машина не отжимает', 'Правильно я понял, что вас интересует ремонт стиральной машины? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту стиральных машин, оставайтесь на линии', 1, 119, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (2, 'холодильник не морозит', 'Правильно я понял, что вас интересует ремонт холодильника? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту холодильников, оставайтесь на линии', 2, 116, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (3, 'посудомоечная машина не моет посуду', 'Правильно я понял, что вас интересует ремонт посудомоечной машины? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту посудомоечных машин, оставайтесь на линии', 3, 135, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (4, 'кофемашина не варит кофе', 'Правильно я понял, что вас интересует ремонт кофемашины? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту кофемашин, оставайтесь на линии', 4, 505, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (5, 'микроволновка не греет', 'Правильно я понял, что вас интересует ремонт микроволновой печи? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту микроволновых печей, оставайтесь на линии', 5, NULL, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (6, 'духовка не греет', 'Правильно я понял, что вас интересует ремонт варочной панели, духового шкафа или электроплиты? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту варочных панелей и духовых шкафов, оставайтесь на линии', 6, NULL, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (7, 'водонагреватель не греет воду', 'Правильно я понял, что вас интересует ремонт водонагревателя? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту водонагревателей, оставайтесь на линии', 7, 219, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (8, 'кондиционер не охлаждает', 'Правильно я понял, что вас интересует ремонт кондиционера? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту кондиционеров, оставайтесь на линии', 8, 262, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (9, 'пылесос не включается', 'Правильно я понял, что вас интересует ремонт пылесоса? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту пылесосов, оставайтесь на линии', 9, NULL, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (10, 'нужен ремонт мелкой бытовой техники', 'Правильно я понял, что вас интересует ремонт мелкой бытовой техники? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту мелкой бытовой техники, оставайтесь на линии', 10, NULL, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (11, 'нужна установка бытовой техники', 'Правильно я понял, что вам нужна установка бытовой техники? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по установке бытовой техники, оставайтесь на линии', 11, NULL, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (12, 'телевизор не включается', 'Правильно я понял, что вас интересует ремонт телевизора или вопрос по уже оформленному заказу на ремонт телевизора? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по телевизорам, оставайтесь на линии', 12, NULL, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (13, 'нужно настроить каналы на телевизоре', 'Правильно я понял, что вам нужна настройка телевизионных каналов? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по настройке телеканалов, оставайтесь на линии', 13, 934, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (14, 'проектор не включается', 'Правильно я понял, что вас интересует ремонт проектора? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту проекторов, оставайтесь на линии', 14, 43, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (15, 'монитор не включается', 'Правильно я понял, что вас интересует ремонт монитора? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту мониторов, оставайтесь на линии', 15, 21, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (16, 'ноутбук не включается', 'Правильно я понял, что вас интересует ремонт компьютера или ноутбука? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту компьютеров и ноутбуков, оставайтесь на линии', 16, NULL, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (17, 'принтер не печатает', 'Правильно я понял, что вас интересует ремонт оргтехники? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту оргтехники, оставайтесь на линии', 17, NULL, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (18, 'айфон не включается', 'Правильно я понял, что вас интересует ремонт айфона? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту айфонов, оставайтесь на линии', 18, NULL, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (19, 'айпад не включается', 'Правильно я понял, что вас интересует ремонт айпада? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту айпадов, оставайтесь на линии', 19, 52, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (20, 'телефон самсунг не включается', 'Правильно я понял, что вас интересует ремонт устройства Samsung? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту техники Samsung, оставайтесь на линии', 20, NULL, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (21, 'керхер не включается', 'Правильно я понял, что вас интересует ремонт техники Karcher? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту техники Karcher, оставайтесь на линии', 21, 879, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (22, 'телефон сломался', 'Правильно я понял, что вас интересует ремонт смартфона или планшета? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту смартфонов и планшетов, оставайтесь на линии', 22, NULL, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (23, 'окно не закрывается', 'Правильно я понял, что вас интересует ремонт окна? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ремонту окон, оставайтесь на линии', 23, 721, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (24, 'нужна обработка от тараканов', 'Правильно я понял, что вас интересует обработка от насекомых или грызунов, дезинсекция? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по дезинсекции и дезинфекции, оставайтесь на линии', 24, 915, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (25, 'нужна уборка квартиры', 'Правильно я понял, что вас интересует заказ клининговых услуг? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по клинингу, оставайтесь на линии', 25, NULL, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (26, 'нужен ветеринар на дом', 'Правильно я понял, что вам нужны ветеринарные услуги? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по ветеринарным услугам, оставайтесь на линии', 26, 800, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (27, 'нужен интернет на дачу', 'Правильно я понял, что вам нужно подключение интернета на даче? Ответьте, пожалуйста, да или нет', 'Соединяю вас со специалистом по подключению интернета на даче, оставайтесь на линии', 27, 656, 0, 0);
INSERT INTO ULTIMA.AI_KNOWLEDGE_BASE (ID, QUESTION, CLARIFYING_QUESTION, POSITIVE_REPLY, SCENARIO_ID, EQUIPMENT_TYPE_ID, IS_FROM_BOT, NOT_ACTIVE) VALUES (28, 'ко мне приезжал мастер но техника снова не работает', 'Правильно я понял, что вы обращаетесь по ранее оформленному заказу? Ответьте, пожалуйста, да или нет', 'Соединяю вас с отделом сопровождения, оставайтесь на линии', NULL, NULL, 0, 0);


-- ----------------------------------------------------------------------
-- Формулировки. Каноничной формулировки здесь нет — она в самой записи.
-- ----------------------------------------------------------------------
-- запись 1: стиральная машина не отжимает
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (1, 1, 'стиралка машинка сломалась', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (2, 1, 'стиральная машинка не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (3, 1, 'стиральная машина не включается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (4, 1, 'стиралка течет вода', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (5, 1, 'машинка стиральная гудит и не крутит барабан', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (6, 1, 'нужен ремонт стиральной машины', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (7, 1, 'мастера вызвать по стиральной машине', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (8, 1, 'почините стиралку пожалуйста', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (9, 1, 'стиральная машина выбивает автомат', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (10, 1, 'барабан в стиралке заклинило', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (11, 1, 'машинка не сливает воду', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (12, 1, 'стиралка стучит при отжиме', 0);
-- запись 2: холодильник не морозит
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (13, 2, 'холодос подтекает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (14, 2, 'холодильник течет', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (15, 2, 'холодильник не холодит', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (16, 2, 'морозилка не морозит', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (17, 2, 'холодильник шумит сильно', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (18, 2, 'нужен ремонт холодильника', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (19, 2, 'мастера вызвать по холодильнику', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (20, 2, 'почините холодильник', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (21, 2, 'холодильник не включается совсем', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (22, 2, 'в холодильнике лужа воды', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (23, 2, 'холодильник постоянно работает не выключается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (24, 2, 'иней в морозильной камере', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (25, 2, 'холодильник подтекает снизу', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (26, 2, 'вода скапливается под холодильником', 0);
-- запись 3: посудомоечная машина не моет посуду
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (27, 3, 'посудомойка сломалась', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (28, 3, 'посудомоечная не включается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (29, 3, 'посудомойка течет', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (30, 3, 'машина для посуды не греет воду', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (31, 3, 'посудомойка не сливает воду', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (32, 3, 'нужен ремонт посудомоечной машины', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (33, 3, 'мастера вызвать по посудомойке', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (34, 3, 'почините посудомоечную машину', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (35, 3, 'посудомойка выдает ошибку', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (36, 3, 'посуда после мойки остается грязной', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (37, 3, 'посудомоечная машина гудит и не запускается', 0);
-- запись 4: кофемашина не варит кофе
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (38, 4, 'кофемашинка сломалась', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (39, 4, 'кофе машина не включается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (40, 4, 'кофемашина течет', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (41, 4, 'кофемашина не мелет зерна', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (42, 4, 'кофемашина не греет воду', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (43, 4, 'нужен ремонт кофемашины', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (44, 4, 'мастера вызвать по кофемашине', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (45, 4, 'почините кофемашину', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (46, 4, 'кофемашина выдает ошибку на экране', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (47, 4, 'кофемашина сильно шумит', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (48, 4, 'капучинатор не взбивает молоко', 0);
-- запись 5: микроволновка не греет
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (49, 5, 'свч сломалась', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (50, 5, 'микроволновая печь не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (51, 5, 'микроволновка искрит внутри', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (52, 5, 'микроволновка не включается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (53, 5, 'свч печь гудит но не греет', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (54, 5, 'нужен ремонт микроволновки', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (55, 5, 'мастера вызвать по свч печи', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (56, 5, 'почините микроволновку', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (57, 5, 'тарелка в микроволновке не крутится', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (58, 5, 'микроволновка щелкает и выключается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (59, 5, 'дверца микроволновки не закрывается', 0);
-- запись 6: духовка не греет
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (60, 6, 'варочная панель не включается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (61, 6, 'электроплита не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (62, 6, 'духовой шкаф не нагревается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (63, 6, 'плита электрическая искрит', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (64, 6, 'конфорка на варочной панели не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (65, 6, 'нужен ремонт духового шкафа', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (66, 6, 'мастера вызвать по варочной панели', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (67, 6, 'почините электроплиту', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (68, 6, 'духовка не выключается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (69, 6, 'плита выбивает автомат', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (70, 6, 'сенсор на варочной панели не реагирует', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (71, 6, 'духовка дымит внутри', 0);
-- запись 7: водонагреватель не греет воду
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (72, 7, 'бойлер сломался', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (73, 7, 'водонагреватель течет', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (74, 7, 'бойлер не включается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (75, 7, 'горячая вода еле теплая из бойлера', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (76, 7, 'водонагреватель выбивает автомат', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (77, 7, 'нужен ремонт водонагревателя', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (78, 7, 'мастера вызвать по бойлеру', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (79, 7, 'почините водонагреватель', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (80, 7, 'бойлер шумит и гудит', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (81, 7, 'бак водонагревателя протекает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (82, 7, 'бойлер бьет током', 0);
-- запись 8: кондиционер не охлаждает
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (83, 8, 'кондер сломался', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (84, 8, 'кондиционер не включается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (85, 8, 'кондиционер течет вода из блока', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (86, 8, 'кондиционер шумит сильно', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (87, 8, 'сплит система не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (88, 8, 'нужен ремонт кондиционера', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (89, 8, 'мастера вызвать по кондиционеру', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (90, 8, 'почините кондиционер', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (91, 8, 'кондиционер дует теплым воздухом', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (92, 8, 'нужна заправка кондиционера фреоном', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (93, 8, 'кондиционер пахнет неприятно', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (94, 8, 'внешний блок кондиционера гудит', 0);
-- запись 9: пылесос не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (95, 9, 'пылесос перестал всасывать', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (96, 9, 'пылесос сломался', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (97, 9, 'робот пылесос не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (98, 9, 'пылесос сильно шумит', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (99, 9, 'пылесос дымится', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (100, 9, 'нужен ремонт пылесоса', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (101, 9, 'мастера вызвать по пылесосу', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (102, 9, 'почините пылесос', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (103, 9, 'пылесос пахнет гарью', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (104, 9, 'аккумулятор пылесоса не держит заряд', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (105, 9, 'щетка пылесоса не крутится', 0);
-- запись 10: нужен ремонт мелкой бытовой техники
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (106, 10, 'швейная машинка сломалась', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (107, 10, 'почините швейную машину', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (108, 10, 'утюг не греет', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (109, 10, 'фен не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (110, 10, 'блендер не включается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (111, 10, 'миксер сломался', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (112, 10, 'мясорубка не крутит', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (113, 10, 'тостер не греет', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (114, 10, 'мультиварка не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (115, 10, 'нужен мастер по мелкой бытовой технике', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (116, 10, 'электрочайник не выключается', 0);
-- запись 11: нужна установка бытовой техники
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (117, 11, 'подключить стиральную машину', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (118, 11, 'установить холодильник', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (119, 11, 'нужен мастер для установки техники', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (120, 11, 'подключить посудомоечную машину', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (121, 11, 'повесить кондиционер', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (122, 11, 'установить варочную панель', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (123, 11, 'подключить духовой шкаф', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (124, 11, 'нужна установка новой техники после покупки', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (125, 11, 'монтаж бытовой техники', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (126, 11, 'установить вытяжку', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (127, 11, 'подключить водонагреватель после покупки', 0);
-- запись 12: телевизор не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (128, 12, 'телек сломался', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (129, 12, 'телевизор не показывает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (130, 12, 'нет изображения на телевизоре', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (131, 12, 'тв не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (132, 12, 'телевизор показывает с полосами', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (133, 12, 'полосы на экране телевизора', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (134, 12, 'нет звука на телевизоре', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (135, 12, 'пропал звук на телевизоре', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (136, 12, 'мастера вызвать по телевизору', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (137, 12, 'почините телевизор', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (138, 12, 'экран телевизора треснул', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (139, 12, 'телевизор мигает и гаснет', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (140, 12, 'хочу узнать статус заказа на ремонт телевизора', 0);
-- запись 13: нужно настроить каналы на телевизоре
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (141, 13, 'нужен поиск каналов на телевизоре', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (142, 13, 'сбились каналы на телевизоре', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (143, 13, 'пропали каналы после отключения света', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (144, 13, 'помогите настроить каналы на приставке', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (145, 13, 'нужна перенастройка каналов после переезда', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (146, 13, 'не находит цифровые каналы при поиске', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (147, 13, 'нужно заново прописать каналы', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (148, 13, 'настройка цифрового телевидения', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (149, 13, 'мало каналов ловит нужно настроить', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (150, 13, 'перенастроить каналы после смены антенны', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (151, 13, 'нужен специалист по настройке каналов', 0);
-- запись 14: проектор не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (152, 14, 'проектор сломался', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (153, 14, 'проектор не показывает изображение', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (154, 14, 'нужен ремонт проектора', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (155, 14, 'мастера вызвать по проектору', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (156, 14, 'почините проектор', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (157, 14, 'проектор мигает и гаснет', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (158, 14, 'лампа в проекторе перегорела', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (159, 14, 'проектор показывает размыто', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (160, 14, 'проектор шумит сильно', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (161, 14, 'у проектора нет звука', 0);
-- запись 15: монитор не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (162, 15, 'монитор компьютера сломался', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (163, 15, 'монитор не показывает изображение', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (164, 15, 'нужен ремонт монитора', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (165, 15, 'мастера вызвать по монитору', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (166, 15, 'почините монитор', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (167, 15, 'экран монитора мигает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (168, 15, 'на мониторе полосы', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (169, 15, 'монитор гаснет через пару секунд', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (170, 15, 'монитор искажает цвета', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (171, 15, 'монитор не реагирует на кабель', 0);
-- запись 16: ноутбук не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (172, 16, 'комп сломался', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (173, 16, 'компьютер тормозит', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (174, 16, 'ноут не заряжается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (175, 16, 'нужен ремонт компьютера', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (176, 16, 'мастера вызвать по ноутбуку', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (177, 16, 'почините ноутбук', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (178, 16, 'компьютер синий экран', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (179, 16, 'ноутбук перегревается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (180, 16, 'компьютер не видит жесткий диск', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (181, 16, 'клавиатура ноутбука не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (182, 16, 'нужна чистка компьютера от пыли', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (183, 16, 'переустановить windows на ноутбуке', 0);
-- запись 17: принтер не печатает
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (184, 17, 'мфу сломался', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (185, 17, 'принтер не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (186, 17, 'сканер не сканирует', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (187, 17, 'копир не копирует', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (188, 17, 'принтер мнет бумагу', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (189, 17, 'нужен ремонт принтера', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (190, 17, 'мастера вызвать по мфу', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (191, 17, 'почините принтер', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (192, 17, 'принтер печатает полосами', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (193, 17, 'нужна заправка картриджа', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (194, 17, 'принтер не видит компьютер', 0);
-- запись 18: айфон не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (195, 18, 'iphone разбился экран', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (196, 18, 'разбил экран на айфоне', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (197, 18, 'разбил стекло на айфоне', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (198, 18, 'уронил айфон и разбил экран', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (199, 18, 'не заряжается айфон', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (200, 18, 'села батарея на айфоне', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (201, 18, 'айфон не включается после падения', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (202, 18, 'телефон айфон сломался', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (203, 18, 'мастера вызвать по айфону', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (204, 18, 'почините айфон', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (205, 18, 'айфон не видит сим карту', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (206, 18, 'камера на айфоне не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (207, 18, 'айфон завис на яблоке', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (208, 18, 'разбит экран на iphone', 0);
-- запись 19: айпад не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (209, 19, 'ipad разбился экран', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (210, 19, 'планшет айпад не заряжается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (211, 19, 'айпад сломался', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (212, 19, 'нужен ремонт айпада', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (213, 19, 'мастера вызвать по айпаду', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (214, 19, 'почините айпад', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (215, 19, 'айпад завис и не реагирует', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (216, 19, 'разбит экран на ipad', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (217, 19, 'айпад не держит зарядку', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (218, 19, 'кнопка домой на айпаде не работает', 0);
-- запись 20: телефон самсунг не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (219, 20, 'самсунг разбился экран', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (220, 20, 'планшет самсунг сломался', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (221, 20, 'самсунг не заряжается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (222, 20, 'нужен ремонт самсунга', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (223, 20, 'мастера вызвать по самсунгу', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (224, 20, 'почините самсунг', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (225, 20, 'самсунг завис не реагирует', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (226, 20, 'разбит экран на samsung', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (227, 20, 'самсунг не включается после воды', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (228, 20, 'камера на самсунге не работает', 0);
-- запись 21: керхер не включается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (229, 21, 'мойка керхер сломалась', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (230, 21, 'мойка керхер не включается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (231, 21, 'пылесос керхер не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (232, 21, 'керхер не подаёт воду', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (233, 21, 'керхер не набирает давление', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (234, 21, 'керхер протекает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (235, 21, 'керхер потёк', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (236, 21, 'мастера вызвать по керхеру', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (237, 21, 'почините керхер', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (238, 21, 'моющий пылесос керхер не всасывает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (239, 21, 'у керхера не крутится шланг', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (240, 21, 'керхер искрит', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (241, 21, 'нужен ремонт керхера', 0);
-- запись 22: телефон сломался
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (242, 22, 'планшет сяоми не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (243, 22, 'ксиоми не включается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (244, 22, 'хуавей не заряжается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (245, 22, 'сяоми телефон завис', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (246, 22, 'разбит экран на андроид телефоне', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (247, 22, 'планшет не включается андроид', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (248, 22, 'телефон хонор сломался', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (249, 22, 'редми завис не реагирует', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (250, 22, 'реалми не заряжается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (251, 22, 'хуавей планшет не включается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (252, 22, 'сяоми не видит сим карту', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (253, 22, 'андроид телефон не заряжается', 0);
-- запись 23: окно не закрывается
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (254, 23, 'пластиковое окно сломалось', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (255, 23, 'окно продувает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (256, 23, 'ручка на окне не крутится', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (257, 23, 'стеклопакет треснул', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (258, 23, 'окно не открывается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (259, 23, 'нужен ремонт окон', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (260, 23, 'мастера вызвать по окну', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (261, 23, 'почините окно пожалуйста', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (262, 23, 'окно провисло и цепляет раму', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (263, 23, 'москитная сетка сломалась', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (264, 23, 'фурнитура окна разболталась', 0);
-- запись 24: нужна обработка от тараканов
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (265, 24, 'травят клопов', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (266, 24, 'в квартире появились тараканы', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (267, 24, 'тараканы завелись на кухне', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (268, 24, 'тараканы бегают по кухне', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (269, 24, 'нужна обработка от клопов', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (270, 24, 'заказать травлю муравьев', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (271, 24, 'избавиться от блох в квартире', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (272, 24, 'крысы в подвале', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (273, 24, 'мыши на кухне', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (274, 24, 'завелись грызуны в доме', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (275, 24, 'потравить крыс', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (276, 24, 'нужна дератизация от грызунов', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (277, 24, 'нужна обработка от плесени и запаха', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (278, 24, 'обработка квартиры после животных', 0);
-- запись 25: нужна уборка квартиры
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (279, 25, 'закажите клининг', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (280, 25, 'нужна генеральная уборка', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (281, 25, 'помыть окна и полы после ремонта', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (282, 25, 'нужна уборка офиса', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (283, 25, 'химчистка мягкой мебели', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (284, 25, 'нужна уборка после ремонта', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (285, 25, 'заказать мойку окон', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (286, 25, 'нужна регулярная уборка квартиры', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (287, 25, 'почистить ковры и диван', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (288, 25, 'нужен клининг для дома', 0);
-- запись 26: нужен ветеринар на дом
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (289, 26, 'заболела кошка нужен врач', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (290, 26, 'собаке нужна прививка', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (291, 26, 'нужен осмотр животного ветеринаром', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (292, 26, 'питомцу плохо нужна помощь', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (293, 26, 'вызвать ветеринара на дом', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (294, 26, 'нужна стрижка когтей животному', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (295, 26, 'кот не ест нужен ветеринар', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (296, 26, 'нужна кастрация кота', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (297, 26, 'собака поранилась нужна помощь врача', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (298, 26, 'нужен осмотр щенка', 0);
-- запись 27: нужен интернет на дачу
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (299, 27, 'подключить интернет на даче', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (300, 27, 'нужен вайфай на даче', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (301, 27, 'интернет на дачу не ловит', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (302, 27, 'хочу провести интернет за городом', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (303, 27, 'нужен роутер для дачи', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (304, 27, 'плохой сигнал интернета на даче', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (305, 27, 'подключить wifi на дачном участке', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (306, 27, 'нужен мобильный интернет для дачи', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (307, 27, 'интернет на даче постоянно отключается', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (308, 27, 'хочу подключить интернет в загородном доме', 0);
-- запись 28: ко мне приезжал мастер но техника снова не работает
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (309, 28, 'у меня уже был мастер но не помогло', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (310, 28, 'снова сломалось после ремонта', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (311, 28, 'опять не работает после того как уже чинили', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (312, 28, 'это гарантийный случай, мастер уже приезжал', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (313, 28, 'уже вызывал мастера но проблема осталась', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (314, 28, 'техника второй раз ломается после ремонта', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (315, 28, 'хочу обратиться по ранее оформленному заказу', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (316, 28, 'звоню уточнить по уже открытой заявке на повторный визит', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (317, 28, 'мастер приезжал а техника опять не работает', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (318, 28, 'повторный вызов мастера по гарантии', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (319, 28, 'чинили но снова сломалось', 0);
INSERT INTO ULTIMA.AI_KB_PHRASES (ID, KNOWLEDGE_BASE_ID, PHRASE, IS_FROM_BOT) VALUES (320, 28, 'звоню по уже оформленной заявке насчет мастера', 0);


COMMIT;


-- ----------------------------------------------------------------------
-- Проверка: должно получиться 27 / 28 / 320.
-- ----------------------------------------------------------------------
SELECT (SELECT COUNT(*) FROM ULTIMA.AI_SCENARIOS)      AS SCENARIOS,
       (SELECT COUNT(*) FROM ULTIMA.AI_KNOWLEDGE_BASE) AS RECORDS,
       (SELECT COUNT(*) FROM ULTIMA.AI_KB_PHRASES)     AS PHRASES
  FROM DUAL;
