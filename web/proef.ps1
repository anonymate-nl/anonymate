# Proef van de webversie met een echte populatie, buiten VS Code, met tijden en geheugen.
#
#   powershell -ExecutionPolicy Bypass -File web\proef.ps1
#   powershell -ExecutionPolicy Bypass -File web\proef.ps1 -Populatie D:\pad\populatie.parquet
#
# Wat het doet:
#   1. zet de populatie (Parquet) in web\dist (harde koppeling, anders een kopie) en bouwt dist
#      eerst als die er nog niet is;
#   2. start een testserver op 127.0.0.1 (als er op de poort nog geen draait);
#   3. opent Edge met een eigen proefprofiel (%LOCALAPPDATA%\anonymate\edge-proef) op de pagina
#      met ?populatie=...&tijden=1: rechtsonder verschijnt een vak met de duur van elke lange
#      stap, met een knop "Tijden kopieren";
#   4. logt elke 5 seconden het geheugen (vrij RAM, commit, swappen, het grootste Edge-proces)
#      naar een CSV in %TEMP%, tot je hier op q drukt; daarna een samenvatting.
#
# Het proefprofiel houdt de gekoppelde EP-online-labels vast (opslag van de browser), zodat een
# volgende proef in dezelfde maand ze meteen gebruikt. -Schoon begint met een leeg profiel, zoals
# InPrivate: dan moet het totaalbestand opnieuw gekoppeld worden.
#
# Sleep zelf het EP-online-totaalbestand (v..._csv.zip) in de kaart "Energielabels toevoegen".
# Voor een eerlijke meting: sluit vooraf VS Code en andere zware programma's.

param(
    [string]$Populatie = "$env:LOCALAPPDATA\anonymate\populatie-zonder-labels.parquet",
    [int]$Poort = 8765,
    [int]$Interval = 5,
    [switch]$Schoon
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $repo "web\dist"
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

if (-not (Test-Path $Populatie)) {
    Write-Host "Populatie niet gevonden: $Populatie" -ForegroundColor Red
    Write-Host "Geef er een op met -Populatie <pad naar .parquet>."
    exit 1
}
if (-not (Test-Path (Join-Path $dist "index.html"))) {
    Write-Host "web\dist ontbreekt; nu bouwen (python web\maak.py)..."
    & $python (Join-Path $repo "web\maak.py")
}

# 1. de populatie naast de pagina (zelfde herkomst)
$naam = "proef-" + [IO.Path]::GetFileName($Populatie)
$doel = Join-Path $dist $naam
if (-not (Test-Path $doel)) {
    try { New-Item -ItemType HardLink -Path $doel -Target $Populatie | Out-Null }
    catch { Write-Host "Harde koppeling lukt niet (ander station?); kopieren..."; Copy-Item $Populatie $doel }
}

# 2. de testserver
$server = $null
$bezet = Get-NetTCPConnection -LocalPort $Poort -State Listen -ErrorAction SilentlyContinue
if (-not $bezet) {
    $server = Start-Process $python -ArgumentList "-m", "http.server", "-b", "127.0.0.1", "-d", "`"$dist`"", "$Poort" `
        -WindowStyle Minimized -PassThru
    Start-Sleep 2
    Write-Host "Testserver gestart op poort $Poort (proces $($server.Id))."
} else {
    Write-Host "Op poort $Poort draait al een server; die gebruik ik."
}

# 3. de browser
$url = "http://127.0.0.1:$Poort/?populatie=$naam&tijden=1"
$profiel = Join-Path $env:LOCALAPPDATA "anonymate\edge-proef"
if ($Schoon -and (Test-Path $profiel)) {
    Write-Host "Leeg proefprofiel: $profiel wissen..."
    Remove-Item -Recurse -Force $profiel
}
Start-Process "msedge" -ArgumentList "--user-data-dir=`"$profiel`"", "--no-first-run", $url
Write-Host "Oude versie van de pagina? Druk in Edge op Ctrl+F5."
Write-Host ""
Write-Host "Geopend: $url"
Write-Host "Sleep het totaalbestand in de kaart 'Energielabels toevoegen'; daarna eventueel een"
Write-Host "eigen dataset toetsen. Druk hier op q als je klaar bent."
Write-Host ""

# 4. geheugen loggen
$csv = Join-Path $env:TEMP ("anonymate-proef-{0:yyyyMMdd-HHmmss}.csv" -f (Get-Date))
"tijd,ram_vrij_gb,commit_gb,paginas_per_s,edge_grootste_mb,edge_totaal_mb" | Set-Content -Encoding ascii $csv
$start = Get-Date
$rijen = @()
function Meet {
    $os = Get-CimInstance Win32_OperatingSystem
    $edge = Get-Process msedge -ErrorAction SilentlyContinue
    $pps = $null
    try { $pps = [math]::Round((Get-Counter '\Memory\Pages/sec' -ErrorAction Stop).CounterSamples[0].CookedValue) } catch {}
    [pscustomobject]@{
        tijd = (Get-Date).ToString("HH:mm:ss")
        ram_vrij_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
        commit_gb = [math]::Round(($os.TotalVirtualMemorySize - $os.FreeVirtualMemory) / 1MB, 2)
        paginas_per_s = $pps
        edge_grootste_mb = [math]::Round((($edge | Measure-Object PrivateMemorySize64 -Maximum).Maximum) / 1MB)
        edge_totaal_mb = [math]::Round((($edge | Measure-Object PrivateMemorySize64 -Sum).Sum) / 1MB)
    }
}
while ($true) {
    $r = Meet
    $rijen += $r
    # met een punt als decimaalteken, ook bij Nederlandse landinstellingen (anders breekt de komma de kolommen)
    [string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0},{1},{2},{3},{4},{5}",
        $r.tijd, $r.ram_vrij_gb, $r.commit_gb, $r.paginas_per_s, $r.edge_grootste_mb, $r.edge_totaal_mb) |
        Add-Content -Encoding ascii $csv
    Write-Host ("`r{0}  RAM vrij {1,5:N1} GB  commit {2,5:N1} GB  swappen {3,6}/s  Edge grootste {4,5} MB   " -f `
        $r.tijd, $r.ram_vrij_gb, $r.commit_gb, $r.paginas_per_s, $r.edge_grootste_mb) -NoNewline
    $tot = (Get-Date).AddSeconds($Interval)
    $stop = $false
    while ((Get-Date) -lt $tot) {
        if ([Console]::KeyAvailable -and ([Console]::ReadKey($true).KeyChar -eq 'q')) { $stop = $true; break }
        Start-Sleep -Milliseconds 200
    }
    if ($stop) { break }
}

# samenvatting
$duur = (Get-Date) - $start
Write-Host ""
Write-Host ""
Write-Host "=== Samenvatting ==="
Write-Host ("Duur van de meting:        {0:hh\:mm\:ss}" -f $duur)
Write-Host ("Edge, grootste proces:     max {0} MB" -f ($rijen | Measure-Object edge_grootste_mb -Maximum).Maximum)
Write-Host ("RAM vrij:                  min {0} GB" -f ($rijen | Measure-Object ram_vrij_gb -Minimum).Minimum)
Write-Host ("Commit:                    max {0} GB (RAM: {1:N1} GB)" -f ($rijen | Measure-Object commit_gb -Maximum).Maximum, `
    ((Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize / 1MB))
$p = $rijen | Where-Object { $_.paginas_per_s -ne $null }
if ($p) {
    $zwaar = @($p | Where-Object { $_.paginas_per_s -gt 1000 }).Count
    Write-Host ("Swappen:                   max {0}/s; {1} van {2} metingen boven 1000/s" -f `
        ($p | Measure-Object paginas_per_s -Maximum).Maximum, $zwaar, $p.Count)
}
Write-Host "Geheugenlog:               $csv"
Write-Host ""
Write-Host "Klik in de pagina op 'Tijden kopieren' en plak de tijden samen met deze samenvatting in de chat."

if ($server) {
    Stop-Process -Id $server.Id -ErrorAction SilentlyContinue
    Write-Host "Testserver gestopt."
}
