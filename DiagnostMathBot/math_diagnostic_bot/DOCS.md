# DiagnostMathBot — документация

## Что делает бот

Родитель заполняет анкету → ребёнок проходит 18 задач по математике → бот строит отчёт с главным пробелом → предлагает курс → warmup-серия сообщений.

Воронка: `new → questionnaire_done → diagnosis_done → report_sent → waitlist → subscribed → purchased`

---

## Быстрый старт (локально)

```bash
cd DiagnostMathBot/math_diagnostic_bot
cp .env.example .env
# заполнить .env
pip install -r requirements.txt
python main.py
```

---

## Переменные окружения (.env)

| Переменная | Описание |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен бота от @BotFather |
| `NOTION_TOKEN` | Internal integration token из Notion |
| `NOTION_TASKS_DB_ID` | ID базы задач (write) |
| `NOTION_TASKS_DS_ID` | Data Source ID базы задач (read) |
| `NOTION_CRM_DB_ID` | ID CRM базы пользователей |
| `NOTION_CRM_DS_ID` | Data Source ID CRM |
| `NOTION_KANBAN_DB_ID` | ID Kanban базы |
| `NOTION_KANBAN_DS_ID` | Data Source ID Kanban |
| `NOTION_CONFIG_DB_ID` | ID Config базы (warmup, файлы) |
| `NOTION_CONFIG_DS_ID` | Data Source ID Config |
| `TELEGRAM_CHANNEL_ID` | ID или @username канала |
| `ADMIN_CHAT_ID` | telegram_id администратора |
| `DB_PATH` | Путь к SQLite (по умолчанию `data/bot.db`) |

---

## Notion Config DB — схема

База данных конфигурации. Каждая строка — одна настройка.

### Свойства базы

| Свойство | Тип Notion | Описание |
|---|---|---|
| `config_name` | Title | Название строки |
| `config_type` | Select | `bot_config` / `topic_file` / `warmup_step` |
| `topic_code` | Text | Код темы (A1, G2…) или строковое значение bot_config |
| `step_index` | Number | Индекс шага warmup (0,1,2,3) или числовое значение bot_config |
| `delay_hours` | Number | Задержка warmup в часах |
| `file_url` | URL | Ссылка на PDF-файл (опционально) |
| `message` | Text | Текст сообщения для обычных пользователей |
| `message_waitlist` | Text | Текст для пользователей в листе ожидания |

### config_type = bot_config

Переопределяет настройки бота:

| config_name | Где хранится | Описание |
|---|---|---|
| `channel_id` | topic_code | @username или ID канала |
| `admin_chat_id` | topic_code | telegram_id администратора |
| `task_time_limit_sec` | step_index | Время на задачу (сек) |
| `timer_update_interval_sec` | step_index | Интервал обновления таймера |

### config_type = topic_file

Файл-чеклист для конкретной темы. Отправляется после подписки на канал.

| Поле | Значение |
|---|---|
| topic_code | Код темы (A1, G2…) |
| file_url | Прямая ссылка на PDF |

### config_type = warmup_step

Один шаг warmup-серии. Индекс 0 = сразу после отчёта.

| Поле | Описание |
|---|---|
| step_index | 0 / 1 / 2 / 3 |
| delay_hours | 0 / 24 / 72 / 168 |
| file_url | PDF-файл (опционально; если пусто — шлётся только текст) |
| message | Текст для пользователей НЕ в листе ожидания |
| message_waitlist | Текст для пользователей В листе ожидания (если пусто — используется message) |

**Плейсхолдеры в message / message_waitlist:**
- `{child_name}` — имя ребёнка
- `{parent_name}` — имя родителя
- `{weak_topic}` — название слабой темы

---

## Структура файлов

```
math_diagnostic_bot/
├── main.py                    # точка входа
├── config.yaml                # темы, воронка, warmup-шаги по умолчанию
├── .env                       # секреты (не коммитить)
├── .env.example               # шаблон
├── requirements.txt
├── Dockerfile
├── railway.toml
├── bot/
│   ├── config.py              # dataclasses + load_config()
│   ├── states.py              # FSM-состояния
│   ├── keyboards.py           # inline-клавиатуры
│   ├── messages.py            # тексты сообщений
│   ├── handlers/
│   │   ├── start.py           # /start, session menu
│   │   ├── questionnaire.py   # анкета (4 шага)
│   │   ├── test.py            # тест (18 задач + таймер)
│   │   ├── report.py          # отчёт + CTA к воронке
│   │   ├── cta.py             # waitlist + channel подписка
│   │   ├── session.py         # повторный визит
│   │   └── admin.py           # команды администратора
│   ├── services/
│   │   ├── notion.py          # Notion API (CRM, Kanban, Config)
│   │   ├── scheduler.py       # APScheduler warmup очередь
│   │   ├── scoring.py         # алгоритм подсчёта очков
│   │   ├── file_upload.py     # кэш файлов → Telegram file_id
│   │   └── timer.py           # таймер задач
│   └── database/
│       ├── db.py              # init_db() + миграции
│       └── models.py          # DDL таблиц
├── data/
│   ├── bot.db                 # SQLite (создаётся автоматически)
│   ├── downloads/             # скачанные HTTP-файлы
│   └── stubs/                 # тестовые PDF
└── scripts/
    ├── check_deploy.py        # проверка перед деплоем
    ├── seed_tasks.py          # заполнение задач в Notion
    ├── seed_bot_config.py     # заполнение bot_config в Notion
    └── test_notion.py         # тест Notion API
```

---

## Команды администратора

Доступны только с `ADMIN_CHAT_ID`. Отправить боту:

| Команда | Действие |
|---|---|
| `/admin` | Показать это меню |
| `/stats` | Воронка + статус warmup очереди |
| `/warmup_status` | Последние 20 записей очереди |
| `/reset <telegram_id>` | Сброс пользователя → stage=new, удалить pending warmup |
| `/update_tasks` | Перезагрузить задачи из Notion (обновить кэш) |
| `/update_config_checklists` | Перезагрузить файлы чеклистов из Notion Config DB |
| `/update_config_warmup` | Пересобрать warmup-очереди для всех пользователей |

---

## Warmup — как работает

1. После отправки отчёта `report.py` вызывает `scheduler.schedule_warmup()`
2. Шаги загружаются из Notion Config DB (override config.yaml)
3. Каждый шаг записывается в `warmup_queue` с `scheduled_for = completed_at + delay_hours`
4. Каждую минуту `_process_pending()` проверяет очередь
5. Если у шага есть `message_waitlist` — проверяется текущий `funnel_stage` пользователя в Notion
   - `waitlist / subscribed / purchased` → отправляется `message_waitlist`
   - иначе → `message`
6. Если у шага есть `file_url` — отправляется документ (PDF) с текстом как caption
7. Если `file_url` пустой — отправляется только текстовое сообщение

---

## Лист ожидания — логика

Пользователь попадает в waitlist двумя путями:

**1. Во время диагностики (CTA):**
- После отчёта показывается кнопка "Записаться в лист ожидания"
- При нажатии — **все** карточки с этим `telegram_id` получают `funnel_stage = waitlist`

**2. Через меню /start (повторный визит):**
- Если у пользователя есть завершённая диагностика (stage = diagnosis_done / report_sent)
- В меню появляется кнопка "📋 Записаться в лист ожидания"
- При нажатии — аналогично, все карточки → waitlist

---

## Деплой на Railway

### Требования
- Аккаунт на [railway.app](https://railway.app)
- Все переменные окружения заполнены

### Через GitHub
1. Подключить репозиторий в Railway
2. `git push` → деплой автоматический
3. Проверить логи: `Starting polling...`

### Через Railway CLI
```bash
npm install -g @railway/cli
railway login
cd DiagnostMathBot/math_diagnostic_bot
railway up
```

### Проверка после деплоя
```
/admin           → должно прийти меню
/update_tasks    → "Загружено: 18"
/stats           → статистика воронки
```

---

## SQLite — таблицы

### warmup_queue
| Колонка | Описание |
|---|---|
| telegram_id | ID пользователя |
| trigger | Событие (report_delivered) |
| delay_hours | Задержка от completed_at |
| scheduled_for | Время отправки (UTC) |
| message_template | Текст для обычных пользователей (уже подставлены имена) |
| message_waitlist_template | Текст для waitlist (или NULL) |
| content_url | URL/путь файла или NULL |
| content_type | pdf / text |
| status | pending / sent / failed |

### file_cache / url_cache
Кэш Telegram file_id для локальных файлов и HTTP URL. Заполняется при старте. Обновляется командой `/update_config_checklists`.

---

## Алгоритм оценки (scoring.py)

Для каждой темы считается score:
- base: 0 (верно) или -1 (неверно/пропуск/таймаут)
- +/- 1-hop соседи: ×0.25 / -0.5
- +/- 2-hop соседи: ×0.125 / -0.25

Перевод в проценты: ≤-1 → 0%, ≥0 → 100%, иначе `(1+score)*100%`

Слабая тема = BFS от A1+G1, первый слой с pct<50%. Fallback: глобальный минимум.
