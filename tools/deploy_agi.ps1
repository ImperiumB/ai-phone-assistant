# Выкладка наших AGI-скриптов на станцию Asterisk с проверкой бита исполнения.
#
# Зачем отдельный скрипт, а не scp руками: 06.11.2026 патч через «записать .new
# и переименовать» сбросил права обоих наших AGI на 644, и Asterisk начал рвать
# каждый звонок сразу со строкой «Failed to execute ...: Permission denied».
# Файл лежал на месте, в логе сервиса было пусто, и на поиск причины ушёл
# тестовый звонок и полчаса. Бит исполнения теряется тихо, поэтому его проверка
# должна быть частью выкладки, а не памяткой в голове.
#
# Трогаем ТОЛЬКО свои два файла. Классический астербот (recosintsite_V2.py,
# agi_last_will.py) и общий конфиг Asterisk этот скрипт не касается: они живут
# на живых звонках второго проекта.
#
# Запуск (пароль станции не хранится в репозитории, он передаётся файлом):
#   py -3.12 ...  нет, это PowerShell:
#   .\tools\deploy_agi.ps1 -PwFile C:\...\scratchpad\station.pw
#   .\tools\deploy_agi.ps1 -PwFile ... -Files ai_assistant/agi/ai_assistant.py
#   .\tools\deploy_agi.ps1 -PwFile ... -DryRun
#
# Требуется plink и pscp из комплекта PuTTY в PATH.

[CmdletBinding()]
param(
    # Файл с паролем root станции. Класть в папку сессии и удалять после
    # выкладки, в репозиторий и в память не писать.
    [Parameter(Mandatory = $true)][string]$PwFile,
    [string]$StationHost = '10.20.0.11',
    [string]$User = 'root',
    [string]$RemoteDir = '/var/lib/asterisk/agi-bin',
    [string[]]$Files = @('ai_assistant/agi/ai_assistant.py', 'ai_assistant/agi/ai_assistant_last_will.py'),
    # Показать, что будет сделано, и ничего не менять.
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$script:stamp = ''

function Fail([string]$message) {
    Write-Host "ОТКАЗ: $message" -ForegroundColor Red
    if ($script:stamp) {
        Write-Host "Откат на станции: cp -p <файл>.bak_$script:stamp <файл> && chmod 755 <файл>" -ForegroundColor Cyan
    }
    exit 1
}

if (-not (Test-Path $PwFile)) { Fail "файла с паролем нет: $PwFile" }
foreach ($tool in 'plink', 'pscp') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { Fail "$tool не найден в PATH (нужен комплект PuTTY)" }
}

$repo = (& git rev-parse --show-toplevel).Trim()
if (-not $repo) { Fail 'не удалось определить корень репозитория' }

# 1. Синтаксис под Python 3.9: на станции стоит он, а локально 3.12.
#    Проверяем разбором исходника той версией, что есть, плюс запрет
#    конструкций, которых в 3.9 нет. Полную проверку делает сама станция
#    шагом 4, здесь мы ловим очевидное до копирования.
$local = @()
foreach ($rel in $Files) {
    $path = Join-Path $repo $rel
    if (-not (Test-Path $path)) { Fail "нет локального файла: $rel" }
    $text = Get-Content -Raw -Encoding UTF8 $path
    if ($text -match "`r`n") { Fail "$rel хранится с CRLF, на Linux это ломает шебанг (см. .gitattributes)" }
    if ($text -match '(?m)^\s*match\s+\w+\s*:') { Fail "$rel использует match, в Python 3.9 его нет" }
    if ($text -match ':=') { Write-Host "ВНИМАНИЕ: в $rel есть оператор :=, в 3.9 он есть, но проверьте намерение" -ForegroundColor Yellow }
    & py -3.12 -c "import ast,io,sys; ast.parse(io.open(sys.argv[1],encoding='utf-8').read())" $path
    if ($LASTEXITCODE -ne 0) { Fail "$rel не разбирается как Python" }
    $local += [pscustomobject]@{ Rel = $rel; Path = $path; Name = Split-Path $rel -Leaf }
}
Write-Host ("Локальная проверка пройдена: " + ($local.Name -join ', ')) -ForegroundColor Green

if ($DryRun) {
    Write-Host "Пробный прогон, ничего не меняю. Было бы скопировано в ${User}@${StationHost}:$RemoteDir" -ForegroundColor Cyan
    exit 0
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$script:stamp = $stamp

function Remote([string]$command) {
    $out = & plink -batch -ssh -pwfile $PwFile "$User@$StationHost" $command 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "команда на станции не прошла: $command`n$out" }
    return $out
}

# 2. Бэкап текущих файлов на станции рядом, с отметкой времени. Проверяется
#    отдельной командой: `test -f A && cp A B || echo` возвращает ноль и когда
#    cp упал (нет места), и скрипт печатал «бэкапы есть», когда их не было.
foreach ($f in $local) {
    $remote = "$RemoteDir/$($f.Name)"
    $exists = (Remote "test -f $remote && echo yes || echo no") -join ''
    if ($exists -match 'yes') {
        Remote "cp -p $remote $remote.bak_$stamp" | Out-Null
        $saved = (Remote "test -f $remote.bak_$stamp && echo yes || echo no") -join ''
        if ($saved -notmatch 'yes') { Fail "бэкап $($f.Name) не создался, дальше не идём" }
        Write-Host "Бэкап: $($f.Name).bak_$stamp" -ForegroundColor Green
    } else {
        Write-Host "На станции не было $($f.Name), бэкап не нужен" -ForegroundColor Yellow
    }
}

# 3. Копирование ВО ВРЕМЕННОЕ имя. Боевой файл не трогаем, пока его замену не
#    проверил питон самой станции: единственная настоящая проверка на 3.9
#    выполнялась после подмены, и ошибка синтаксиса оставляла станцию с AGI,
#    который её питон не компилирует. Asterisk запускает его на каждом входящем,
#    скрипт умирает мгновенно, и аварийного перевода нет, потому что он живёт
#    внутри этого же скрипта: рвался бы каждый звонок.
foreach ($f in $local) {
    & pscp -batch -pwfile $PwFile $f.Path "$User@${StationHost}:$RemoteDir/$($f.Name).new"
    if ($LASTEXITCODE -ne 0) { Fail "не удалось скопировать $($f.Rel)" }
}

# 4. Проверка питоном станции по временному файлу, потом подмена одним mv.
foreach ($f in $local) {
    $remote = "$RemoteDir/$($f.Name)"
    $staged = "$remote.new"
    Remote "chmod 755 $staged" | Out-Null
    $compiled = (Remote "python3 -m py_compile $staged && echo ok || echo fail") -join ''
    if ($compiled -notmatch 'ok') {
        Remote "rm -f $staged" | Out-Null
        Fail "$($f.Name) не компилируется питоном станции (3.9). Боевой файл НЕ тронут, временный удалён"
    }
    Remote "mv $staged $remote && chmod 755 $remote" | Out-Null
    $mode = (Remote "stat -c %a $remote") -join ''
    if ($mode.Trim() -ne '755') { Fail "$($f.Name) на станции с правами $mode вместо 755, звонки будут рваться" }
    Write-Host "$($f.Name): скомпилирован питоном станции, подменён, права 755" -ForegroundColor Green
}

Write-Host 'Выложено. AGI подхватывается на следующем звонке, reload Asterisk не нужен.' -ForegroundColor Green
Write-Host 'Проверьте контрольным звонком и посмотрите /var/log/asterisk/full.log на строки Permission denied.' -ForegroundColor Cyan
Write-Host "Откат: на станции cp -p <файл>.bak_$stamp <файл> && chmod 755 <файл>" -ForegroundColor Cyan
