# Functional Requirements / Функциональные требования

This document lists only functionality implemented in the current alpha release. It is the bilingual baseline for product behavior; planned work is tracked separately in `TODO.md`.

Этот документ описывает только функциональность, реализованную в текущей alpha-версии. Это двуязычная базовая спецификация поведения продукта; запланированная работа ведется отдельно в `TODO.md`.

## Scope / Область применения

- **FR-01.** The system collects activity from Ubuntu Desktop with X11 and from Windows 10 or 11, then creates a normalized activity timeline and candidate user-task episodes.
- **FR-01.** Система собирает активность в Ubuntu Desktop с X11 и в Windows 10 или 11, затем формирует нормализованную временную шкалу и предполагаемые эпизоды пользовательских задач.

- **FR-02.** Collection runs locally in an interactive desktop session. It does not require an agent on a remote RDP machine.
- **FR-02.** Сбор выполняется локально в интерактивной desktop-сессии. Агент на удаленной RDP-машине не требуется.

## Windows Capture / Сбор в Windows

- **FR-03.** `scripts/start_windows_collectors.cmd` starts the Windows desktop, browser, waiting RDP, and waiting CyberArk collectors in the background without PowerShell. `scripts/stop_windows_collectors.cmd` stops that set of collectors.
- **FR-03.** `scripts/start_windows_collectors.cmd` запускает коллекторы Windows desktop, браузера, ожидающий RDP- и ожидающий CyberArk-коллекторы в фоновом режиме без PowerShell. `scripts/stop_windows_collectors.cmd` останавливает этот набор коллекторов.

- **FR-04.** The CMD launcher must detach collector standard streams from its caller and return immediately, so an OpenCode session that starts collectors is not blocked.
- **FR-04.** CMD-лаунчер должен отсоединять стандартные потоки коллекторов от вызвавшего процесса и завершаться сразу, чтобы сессия OpenCode, запускающая коллекторы, не блокировалась.

- **FR-05.** The Windows desktop collector writes foreground-window changes to `events.jsonl`, including application name, executable path, PID, window class, title, and window ID.
- **FR-05.** Windows desktop-коллектор записывает изменения активного окна в `events.jsonl`: имя приложения, путь к исполняемому файлу, PID, класс, заголовок и ID окна.

- **FR-06.** The browser launcher starts or connects to a local CDP-enabled Chrome, Chromium, or Edge instance and writes browser activity to `browser-events.jsonl`.
- **FR-06.** Браузерный лаунчер запускает или подключается к локальному Chrome, Chromium или Edge с включенным CDP и записывает активность браузера в `browser-events.jsonl`.

## RDP Capture And Replay / Сбор и воспроизведение RDP

- **FR-07.** Manual RDP recording requires a substring of the target `mstsc.exe` window title and records input only while that window is foreground.
- **FR-07.** Ручная запись RDP требует подстроку заголовка целевого окна `mstsc.exe` и записывает ввод только пока это окно находится на переднем плане.

- **FR-08.** The unified Windows launcher starts an RDP recorder in waiting mode. It selects the first `mstsc.exe` window made active and remains bound to that window for the rest of the recording.
- **FR-08.** Единый Windows-лаунчер запускает RDP-рекордер в режиме ожидания. Он выбирает первое активированное окно `mstsc.exe` и остается привязанным к нему до завершения записи.

- **FR-09.** One RDP recorder captures one selected RDP window. It does not switch to or combine events from other RDP windows.
- **FR-09.** Один RDP-рекордер собирает данные одного выбранного RDP-окна. Он не переключается на другие RDP-окна и не смешивает их события.

- **FR-10.** RDP keyboard and mouse hooks observe physical input, log only input for the selected foreground RDP window, and forward input to Windows so normal operating-system interaction is preserved.
- **FR-10.** RDP-hooks клавиатуры и мыши наблюдают физический ввод, логируют только ввод для выбранного активного RDP-окна и передают ввод Windows, сохраняя обычное управление операционной системой.

- **FR-11.** `Ctrl+Shift+F12` pauses or resumes RDP recording; `Ctrl+Shift+F11` stops it.
- **FR-11.** `Ctrl+Shift+F12` приостанавливает или возобновляет запись RDP; `Ctrl+Shift+F11` останавливает ее.

- **FR-12.** RDP replay is dry-run by default. Sending input requires the explicit `--execute` option, a focused target window, and a matching recorded client size unless explicitly overridden.
- **FR-12.** Воспроизведение RDP по умолчанию работает в dry-run режиме. Отправка ввода требует явной опции `--execute`, активного целевого окна и совпадения записанного размера клиентской области, если это не переопределено явно.

## Data Handling And Analysis / Обработка данных и анализ

- **FR-13.** Browser, desktop, and RDP JSONL logs can be normalized into a shared timeline and candidate task episodes. Analysis accepts at least one desktop or browser log.
- **FR-13.** JSONL-логи браузера, desktop и RDP могут быть нормализованы в общую временную шкалу и предполагаемые эпизоды задач. Анализ принимает как минимум один desktop- или browser-лог.

- **FR-14.** Browser password fields and fields identified by common sensitive-data metadata are marked for redaction in analysis output. In the derived RDP `rdp.command_submitted` event, commands containing common secret markers are redacted.
- **FR-14.** Поля пароля браузера и поля, определенные метаданными как содержащие распространенные чувствительные данные, помечаются для редактирования в результате анализа. В производном RDP-событии `rdp.command_submitted` команды с распространенными маркерами секретов редактируются.

- **FR-15.** Clipboard contents, remote screen contents, remote command output, and remote source code are not collected by the local RDP recorder. A paste is recorded only as a marker.
- **FR-15.** Содержимое буфера обмена, экран удаленной машины, вывод удаленных команд и исходный код на удаленной машине локальный RDP-рекордер не собирает. Вставка записывается только как маркер.

## Operational Boundaries / Эксплуатационные ограничения

- **FR-16.** RDP recording must be started only after RDP authentication and stopped before entering passwords, tokens, or other secrets, because the local collector cannot distinguish a remote password prompt from a terminal.
- **FR-16.** Запись RDP необходимо запускать только после аутентификации в RDP и останавливать до ввода паролей, токенов или других секретов, так как локальный коллектор не отличает удаленный парольный запрос от терминала.

- **FR-17.** Multi-session RDP capture, with a separate recorder for every RDP window, is not implemented.
- **FR-17.** Многосессионный RDP-сбор с отдельным рекордером для каждого RDP-окна не реализован.

- **FR-18.** By default, RDP capture records mouse coordinates only for button-down events and omits mouse-move events. `--record-mouse-moves` restores full mouse movement and coordinate logging.
- **FR-18.** По умолчанию RDP-сбор записывает координаты мыши только для событий нажатия кнопки и не записывает движения мыши. `--record-mouse-moves` возвращает полное логирование движений и координат мыши.

- **FR-19.** Injected keyboard events are ignored by default. `--record-injected-key-events` enables their logging for diagnostics without reading clipboard contents.
- **FR-19.** Инъецированные события клавиатуры по умолчанию игнорируются. `--record-injected-key-events` включает их логирование для диагностики без чтения содержимого буфера обмена.

- **FR-20.** The Windows launchers start a waiting CyberArk collector. It selects one active configured CyberArk PSM client window, records its input to `cyberark-events.jsonl`, and accepts injected keyboard events for diagnostics by default.
- **FR-20.** Windows-лаунчеры запускают ожидающий CyberArk-коллектор. Он выбирает одно активное настроенное окно клиента CyberArk PSM, записывает его ввод в `cyberark-events.jsonl` и по умолчанию принимает injected-события клавиатуры для диагностики.

- **FR-21.** The CyberArk collector receives physical keyboard events through Windows Raw Input and writes them only while its selected PSM client window is foreground.
- **FR-21.** CyberArk-коллектор получает физические события клавиатуры через Windows Raw Input и записывает их только пока выбранное окно PSM-клиента находится на переднем плане.

- **FR-22.** An optional PowerShell audit script can run in an explicitly authorized remote session and write submitted PowerShell commands to a remote JSONL file. It does not collect terminal output, screen contents, or clipboard data, and does not transfer the file automatically.
- **FR-22.** Необязательный PowerShell audit-скрипт может выполняться в явно авторизованной удаленной сессии и записывать отправленные PowerShell-команды в удаленный JSONL-файл. Он не собирает вывод терминала, содержимое экрана или буфера обмена и не передает файл автоматически.

- **FR-23.** Opt-in browser capture can create `cyberark.command_submitted` events for an explicitly configured CyberArk HTML5 terminal URL pattern and terminal CSS selector. It is disabled unless both values are provided.

- **FR-24.** Browser launchers start a visible, non-headless Chrome, Chromium, or Edge window. Collector processes may run in the background, but the browser window remains available for interactive work.
- **FR-24.** Browser-лаунчеры запускают видимое, не-headless окно Chrome, Chromium или Edge. Процессы коллекторов могут работать в фоне, но окно браузера остается доступным для интерактивной работы.
- **FR-25.** Collector events and Windows collector-manager logs use UTC ISO 8601 timestamps with millisecond precision, so events from separate logs can be correlated.
- **FR-25.** События коллекторов и журнал Windows collector-manager используют UTC ISO 8601 timestamp с точностью до миллисекунд, чтобы сопоставлять события из разных логов.

- **FR-26.** The local Windows keyboard collector aggregates decoded key-down text into `keyboard.phrase_submitted` events in `keyboard-events.jsonl`, with `text`, whitespace-separated `words`, and UTC `phrase_start`. Spaces and punctuation are preserved in the phrase; Backspace removes the last buffered character. Key releases do not duplicate text. A phrase ends on an idle timeout (500 ms by default, configurable with `--phrase-timeout`, checked every 50 ms), Enter, Tab, Escape, navigation/editing keys, keyboard shortcuts, foreground-window change, or graceful shutdown. Ctrl/Alt/Win shortcuts do not contribute text; AltGr text remains supported. Per-key events remain available. Aggregation represents observed typing, not reconstruction of edited document contents; forced process termination can lose the pending phrase.
- **FR-26.** Локальный Windows keyboard-коллектор агрегирует декодированный текст нажатий в события `keyboard.phrase_submitted` в `keyboard-events.jsonl` с полями `text`, списком `words` (разделение по пробельным символам) и UTC `phrase_start`. Пробелы и пунктуация сохраняются во фразе; Backspace удаляет последний символ буфера. Отпускания клавиш не дублируют текст. Фраза завершается по паузе (по умолчанию 500 мс, настройка `--phrase-timeout`, проверка каждые 50 мс), Enter, Tab, Escape, клавишам навигации/редактирования, сочетаниям клавиш, смене активного окна или штатной остановке. Сочетания Ctrl/Alt/Win не добавляют текст; текстовый ввод AltGr поддерживается. События отдельных нажатий сохраняются. Агрегация отражает наблюдаемый ввод, а не полное содержимое редактируемого документа; принудительное завершение процесса может потерять незавершённую фразу.
- **FR-23.** Opt-in browser-сбор может создавать события `cyberark.command_submitted` для явно настроенных URL-pattern и CSS selector терминала CyberArk HTML5. Он выключен, пока не переданы оба значения.
