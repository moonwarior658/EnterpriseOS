# EnterpriseOS Print Agent

Локальный Windows-сервис без бизнес-логики. Он принимает только PDF от EOS,
проверяет service token, точное имя разрешённой Windows queue, `copies=2` и
durable idempotency key, после чего передаёт файл Windows print subsystem.

## Printing backend

Production backend использует **SumatraPDF 3.5.2** и его silent CLI. Версию
нужно установить и зафиксировать на Windows-хосте Print Agent; executable по
умолчанию: `C:\Program Files\SumatraPDF\SumatraPDF.exe`. Вызов выполняется без
shell и GUI через `-print-to`, с точным queue name и `-print-settings 2x`.
Успешный exit status означает принятую backend-команду передачи в Windows
printing subsystem; физический выход бумаги в текущем scope не отслеживается.

## Configuration

Обязательные production values:

```text
PRINT_AGENT_SERVICE_TOKEN=<secret>
PRINT_AGENT_DEFAULT_PRINTER=HP LaserJet Pro MFP M125rnw
PRINT_AGENT_ALLOWED_PRINTERS=HP LaserJet Pro MFP M125rnw
PRINT_AGENT_DEFAULT_COPIES=2
PRINT_AGENT_REGISTRY_PATH=C:\ProgramData\EnterpriseOS\print-agent.sqlite3
PRINT_AGENT_SUMATRA_PATH=C:\Program Files\SumatraPDF\SumatraPDF.exe
```

Queue использует установленный Windows driver
`HP LaserJet Pro MFP M125-M126 PCLmS` и существующий WSD port
`WSD-8c4720e8-beaa-4019-9e81-5a2ccddfce79`. IP `192.168.0.14` — только
operational reference; агент не печатает напрямую на IP.

`POST /print` принимает raw `application/pdf` и headers
`X-Print-Job-Id`, `Idempotency-Key`, `X-Printer-Name`, `X-Copies`.
