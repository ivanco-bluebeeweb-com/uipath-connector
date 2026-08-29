# UiPath Connector — идеальный первый запуск

Источник: `ONBOARDING_FIRST_LAUNCH_STANDARD.md`. Целевой пользователь: RPA-разработчик/
оператор роботизированных процессов на UiPath Orchestrator.

## 1. Credential type
OAuth client-credentials (External Application: Client ID + Client Secret) + вероятно
tenant/organization identifiers далее в схеме (Automation Cloud многоуровневая
иерархия: Organization → Tenant → Folder).

## 2. Идеальный флоу
1. **Первое открытие** — `Empty` со ссылкой на создание External Application в
   Automation Cloud admin + явное объяснение иерархии Organization/Tenant, т.к. без
   этого понимания дальнейший выбор Folder будет непонятен.
2. **Форма** — client_id + client_secret с лейблами.
3. **Tenant/Folder selector** — после аутентификации — явный выбор Tenant, затем
   Folder (Orchestrator organizational unit) — двухуровневая иерархия ДО показа
   роботов/очередей, аналогично MuleSoft Business Group/Environment паттерну.
4. **После выбора Folder** — сводка флота роботов (онлайн/офлайн) и очередей
   (pending/failed) сразу — actionable для RPA-оператора.
5. **Failed job drill-down** — упавшие задания должны быть кликабельны на прямую
   ссылку в лог выполнения, не просто статус.
6. **Ошибка "folder access denied"** — если External Application не имеет прав на
   конкретную Folder — конкретное сообщение, не общая 403.

## 3. Разница с реализацией сейчас
См. `UI_COMPONENT_PLAN.md` §0.
