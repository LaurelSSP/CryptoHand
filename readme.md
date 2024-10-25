# CryptoHand
Telegram: @multi_coder 

CryptoHand — это Telegram-бот для ручного обмена криптовалюты, предоставляющий пользователям удобную и безопасную платформу для обмена. Администраторы получают полный контроль над настройками обменника, управлением реквизитами, доступом и статистикой.

## Основные возможности

### Для пользователей:
- **Регистрация**: Простая процедура регистрации с проверкой капчи для повышения безопасности.
- **Покупка криптовалюты**: Поддержка популярных криптовалют (Bitcoin, Litecoin) с актуальными курсами.
- **Различные способы оплаты**: Выбор банковских реквизитов для удобной оплаты.
- **Личный кабинет**: Просмотр истории обменов, общей суммы и другой полезной информации.
- **Уведомления**: Получение оповещений о статусе заявок.

### Для администраторов:
- **Управление комиссией**: Установка и изменение комиссии за обмен.
- **Управление реквизитами оплаты**: Добавление, удаление и просмотр доступных реквизитов.
- **Статистика**: Просмотр общей статистики, количества пользователей и других ключевых показателей.
- **Управление пользователями**: Просмотр и управление списком заблокированных пользователей.
- **Логирование действий**: Автоматическое ведение журнала действий администраторов для аудита и прозрачности.

--

## Установка и настройка

### Шаг 1. Конфигурация
Откройте файл `config.py` и укажите данные для работы:
```markdown
# config.py
BOT_TOKEN = 'your_telegram_bot_token'  # Токен бота Telegram
ADMIN_IDS = [123456789, 987654321]  # Список Telegram ID администраторов
WORKER_ID = '1122334455'  # Telegram ID воркера для уведомлений

ADMIN_USERNAME = 'adminusername'  # Username администратора для ссылок
CAPTCHA_TIMEOUT = 5  # Время действия капчи в минутах
COMMISSION_RATE = 2.5  # Комиссия по умолчанию в процентах
```

### Шаг 2. Инициализация базы данных

- После завершения всех настроек запустите файл `init_db.py`
- Он инициализирует базу данных гарантируя её чистоту

```python
python init_db.py
```

--

**Контакты**  
Telegram: @multi_coder 
