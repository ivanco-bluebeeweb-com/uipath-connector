# UiPath Connector — UI component plan

Источники: `Docs/session-notes/UI_COMPONENT_VOCABULARY.md`, `UI_INTERFACE_STANDARD.md`,
`concepts/panels.md`. Основано на функционале `uipath-connector`.

## 1. Компоненты

| Экран | Примитивы | Почему именно эти |
|---|---|---|
| Sidebar (left) | `ui.Column`(align="start") + `ui.Text`(org/tenant) + `ui.Divider` + navigation `ui.ListItem`(Folders/Jobs/Queues/Robots) + `ui.Button`("App settings") | Без карточек по стандарту. |
| Folder/Process List (center, `center_overlay=True`) | `ui.Stats`(Running jobs/Failed today/Robots online) + `ui.DataTable`(process name, version, folder; sortable) | `DataTable` — стандартный способ обзора доступных процессов (Releases) в папке. |
| Job List | `ui.Select`(param_name="status_filter") + `ui.DataTable`(process, robot, status Badge running/successful/faulted, start time; sortable) | Табличная история/поток запусков процессов. |
| Job Detail | Back-button + `ui.KeyValue`(process/robot/machine/duration) + `ui.Alert`(variant="error", если есть error info) + `ui.Row`(Button "Stop (Kill)", "Stop (SoftStop)") | `Alert` для явного показа ошибки джобы, если она провалилась. |
| Queue Manager | `ui.DataTable`(queue name, pending/in-progress/successful/failed counts) → клик → Queue Item List | Обзор очередей с ключевыми счётчиками сразу в таблице. |
| Queue Item List | `ui.DataTable`(reference, status Badge New/InProgress/Successful/Failed, retry count; sortable) + `ui.Button`("Добавить transaction item") | Управление элементами очереди — прямое использование DataTable. |
| Robot/Machine List | `ui.DataTable`(name, machine, status Badge available/busy/disconnected; sortable) | Обзор состояния роботов-исполнителей. |
| Asset Manager | `ui.DataTable`(name, type) + `ui.Dialog`(форма: `ui.Input`(name) + `ui.Password`(value, если credential-тип)) | `Password` для credential-ассетов — секрет никогда не читается обратно. |
| Storage Bucket Browser | `ui.List`(files с subtitle=directory path) + `ui.Link`(signed download URL) | `Link` — прямой способ дать доступ к подписанному URL файла. |
| App Settings | `ui.Accordion`([Connections+Disconnect, Default Folder Select, Webhooks CRUD]) | Централизованные настройки по стандарту. |

## 2. User flow (валидно по panel lifecycle)

1. **SESSION INIT** → `__panel__uipath_sidebar` рендерит org/tenant + разделы,
   `auto_action` открывает Folder/Process List для папки по умолчанию.
2. Process List: клик на процесс → `ui.Dialog`(запуск: `ui.Select`(robots) +
   `ui.Button`("Start Job")) — запуск джобы не деструктивен, но требует явного
   выбора robots, поэтому Dialog оправдан как форма подтверждения параметров.
3. Job List: клик на строку → Job Detail (тот же center handler, параметризован
   `job_id`) → "Stop" — прямой Call (действие обратимо влияет только на текущий
   запуск, не на данные).
4. Queue Manager → клик на очередь → Queue Item List (тот же handler, параметр
   `queue_id`) → `set_queue_item_status` доступен как Button на строке.
5. Asset Manager: создание credential-ассета — `Dialog` с `Password`; значение
   никогда не возвращается назад при последующих чтениях (`get_asset` не
   раскрывает секрет — это ограничение самого UiPath API, отражено в UI явным
   текстом "Значение скрыто" вместо поля).
6. App Settings — единственная точка входа через кнопку в сайдбаре.

## 3. Экраны (конкретно, по файлам `panels.py`)

1. `uipath_sidebar` (`slot="left"`) — навигация, App settings button, Folder
   Select если несколько папок (`ui.Select` прямо в сайдбаре).
2. `uipath_center` (`slot="center"`, `center_overlay=True`) — параметризован `view`
   (processes/jobs/job_detail/queues/queue_items/robots/assets/buckets).
3. `uipath_settings` (`slot="center"`, `panels_settings.py`) — Accordion с
   Connections/Default Folder/Webhooks.
