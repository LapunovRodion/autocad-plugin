# Окружение разработки

Как поднять и погасить рабочее окружение. Ничего из перечисленного не стартует само:
контейнер Oracle и виртуальная машина запускаются вручную — на ноутбуке с 14 ГБ ОЗУ
держать их постоянно смысла нет.

## Выключение

Перед выключением компьютера погасить гостевую Windows штатно, а не обрывать питание:

```fish
virsh -c qemu:///system shutdown win10-autocad
podman stop task-oracle
```

`shutdown` отправляет ACPI-сигнал, гость завершается сам. Если Windows зависла —
`virsh destroy win10-autocad`, это эквивалент выдёргивания шнура.

## Запуск после перезагрузки

### Oracle

```fish
podman start task-oracle
podman ps                     # дождаться статуса (healthy), обычно меньше минуты
```

Данные при этом сохраняются: они лежат в файловой системе самого контейнера, а `stop` её
не трогает. Проверить, что всё на месте:

```fish
cd ~/projects/Task
nix develop --command ./infra/load-dumps.py --check
```

**Осторожно с `podman compose down`** — эта команда удаляет контейнер вместе с данными.
Постоянного хранилища у базы намеренно нет (см. `infra/compose.yaml`), поэтому для
повседневной работы используйте `stop`/`start`.

Если контейнер всё же был удалён — пересоздать и залить заново, это около минуты:

```fish
cd ~/projects/Task
podman compose -f infra/compose.yaml up -d
nix develop --command ./infra/load-dumps.py
```

### Виртуальная машина

```fish
virsh -c qemu:///system start win10-autocad
virt-manager                  # консоль — двойной клик по машине
```

Или отдельным клиентом, без всего интерфейса:

```fish
virt-viewer --connect qemu:///system win10-autocad
```

Сеть `default` (192.168.122.0/24) поднимается автоматически — у неё включён autostart.
Из гостя хост виден как `192.168.122.1`, то есть Oracle доступен по
`192.168.122.1:1521/XEPDB1`.

При старте ВМ несколько секунд висит «Press any key to boot from CD or DVD» — приводы
с установочными образами всё ещё подключены. Ничего нажимать не нужно, таймер истечёт
и загрузка пойдёт с диска. Приводы можно отключить в virt-manager, когда перестанут быть
нужны драйверы с `virtio-win.iso`.

## Параметры машины

| Параметр | Значение |
|---|---|
| Имя | `win10-autocad` |
| Гость | Windows 10 Pro 22H2 x64 |
| Память / vCPU | 8 ГБ / 6 |
| Чипсет, прошивка | q35, UEFI (OVMF) **без Secure Boot** |
| Диск | 100 ГБ qcow2, шина virtio |
| Сеть | virtio, сеть `default` |

Secure Boot отключён намеренно. С ним прошивка требует подписанный загрузчик, но ключей
Microsoft в переменных нет (`enrolled-keys=no`), поэтому отвергается в том числе штатный
загрузчик Windows — установка падала с «No bootable option or device was found».

## Файлы в /var/lib/libvirt/images

| Файл | Назначение |
|---|---|
| `win10-autocad.qcow2` | диск виртуальной машины |
| `win10-22h2-x64.iso` | установочный образ, собран из ESD |
| `virtio-win.iso` | драйверы virtio, собран из пакета `pkgs.virtio-win` |

Оба ISO — самосборные. `pkgs.virtio-win` в nixpkgs распакован каталогом, а не образом,
поэтому ISO для привода собирается через `xorriso`. Установочный образ Windows собран из
полного ESD: распакован `Windows Setup Media`, склеен `boot.wim` из WinPE и Setup, редакция
Pro пересжата в `install.esd`, всё упаковано с двумя записями El Torito (BIOS и UEFI).

## Что ещё нужно настроить в госте

- `virtio-win-guest-tools.exe` с привода `virtio-win` — драйверы дисплея, balloon и агент.
- **OpenSSH Server** (Settings → Optional features) — на нём держится цикл сборки
  `Task.Plugin`: код собирается командой с Linux, а не руками в госте.
