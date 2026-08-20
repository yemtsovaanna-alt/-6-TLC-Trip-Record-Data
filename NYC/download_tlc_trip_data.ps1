<#
.SYNOPSIS
    Downloads the NYC TLC Trip Record Data archive (Yellow, Green, FHV, FHVHV) from 2019 to present.

.DESCRIPTION
    Source page: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
    Files live on this CDN: https://d37ci6vzurychx.cloudfront.net/trip-data/{type}_tripdata_{yyyy-MM}.parquet

    Heads up on size: this is a LOT of data. Yellow/Green/FHV/FHVHV, one file per month from 2019-01
    through the latest published month (TLC usually publishes with a ~2 month delay) is around 350 files.
    FHVHV files are especially large (often 300-800 MB each). Budget for roughly 60-120+ GB of free disk
    space in total. The script supports resuming, so it is safe to stop it (Ctrl+C) and re-run later.

.PARAMETER Types
    Which data types to download. Default is all four: yellow, green, fhv, fhvhv.

.PARAMETER StartYear
    Start year (default 2019).

.PARAMETER EndDate
    Last month to attempt to download, format "yyyy-MM" (default: 2 months before today, since TLC
    publishes with a delay).

.PARAMETER OutDir
    Where to save files (default: a "TLC_Trip_Data" subfolder next to this script).

.PARAMETER DryRun
    Just show what would be downloaded (list of URLs and paths) without actually downloading.

.EXAMPLE
    .\download_tlc_trip_data.ps1
    Downloads everything (yellow, green, fhv, fhvhv) from 2019-01 through the latest available month.

.EXAMPLE
    .\download_tlc_trip_data.ps1 -Types yellow,green -StartYear 2022
    Downloads only yellow and green, starting from 2022.

.EXAMPLE
    .\download_tlc_trip_data.ps1 -DryRun
    Just shows the file list and size estimate, downloads nothing.
#>

param(
    [string[]]$Types = @("yellow", "green", "fhv", "fhvhv"),
    [int]$StartYear = 2019,
    [string]$EndDate = (Get-Date).AddMonths(-2).ToString("yyyy-MM"),
    [string]$OutDir = (Join-Path $PSScriptRoot "TLC_Trip_Data"),
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# High Volume FHV (fhvhv) only exists starting February 2019
$FhvhvMinDate = Get-Date "2019-02-01"

$startDate = Get-Date "$StartYear-01-01"
$endDate = Get-Date "$EndDate-01"

if ($endDate -lt $startDate) {
    Write-Error "EndDate ($EndDate) is before StartYear ($StartYear). Check your parameters."
    exit 1
}

# curl.exe ships built into Windows 10 1803+ / Windows 11
$curl = Get-Command curl.exe -ErrorAction SilentlyContinue
if (-not $curl) {
    Write-Error "curl.exe not found in PATH. It should be built into modern Windows. Install curl manually or run this on an up-to-date Windows version."
    exit 1
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
foreach ($t in $Types) {
    New-Item -ItemType Directory -Force -Path (Join-Path $OutDir $t) | Out-Null
}

$baseUrl = "https://d37ci6vzurychx.cloudfront.net/trip-data"

# Build the full list of files to download
$jobs = @()
$cursor = $startDate
while ($cursor -le $endDate) {
    $ym = $cursor.ToString("yyyy-MM")
    foreach ($t in $Types) {
        if ($t -eq "fhvhv" -and $cursor -lt $FhvhvMinDate) {
            continue  # fhvhv does not exist before 2019-02
        }
        $fileName = "${t}_tripdata_${ym}.parquet"
        $jobs += [PSCustomObject]@{
            Type = $t
            Url  = "$baseUrl/$fileName"
            Out  = Join-Path (Join-Path $OutDir $t) $fileName
        }
    }
    $cursor = $cursor.AddMonths(1)
}

Write-Host "Total files to download: $($jobs.Count)" -ForegroundColor Cyan
Write-Host "Period: $($startDate.ToString('yyyy-MM')) .. $($endDate.ToString('yyyy-MM'))"
Write-Host "Types: $($Types -join ', ')"
Write-Host "Destination folder: $OutDir"
Write-Host "Size estimate: typically 60-120+ GB total (mostly due to fhvhv). Check your free disk space." -ForegroundColor Yellow
Write-Host ""

if ($DryRun) {
    $jobs | Select-Object Type, Url, Out | Format-Table -AutoSize
    Write-Host "This was a DryRun -- nothing was downloaded." -ForegroundColor Yellow
    exit 0
}

$ok = 0
$failed = @()
$i = 0

foreach ($job in $jobs) {
    $i++
    Write-Host "[$i/$($jobs.Count)] $($job.Type) $($job.Url)" -ForegroundColor Cyan

    if (Test-Path $job.Out) {
        Write-Host "  Already exists, resuming/verifying via -C -" -ForegroundColor DarkGray
    }

    # -C - : resume a partial download
    # -f   : fail (no output file) on HTTP errors like 404
    # --retry 5 --retry-delay 5 : retry on transient network errors
    & curl.exe -f -L -C - --retry 5 --retry-delay 5 -o $job.Out $job.Url

    if ($LASTEXITCODE -eq 0) {
        $ok++
    } else {
        Write-Host "  FAILED (exit code $LASTEXITCODE) -- this month's file may not be published yet" -ForegroundColor Red
        $failed += $job.Url
    }
}

Write-Host ""
Write-Host "Done. Succeeded: $ok / $($jobs.Count)." -ForegroundColor Green
if ($failed.Count -gt 0) {
    Write-Host "Failed to download ($($failed.Count)):" -ForegroundColor Red
    $failed | ForEach-Object { Write-Host "  $_" }
    Write-Host "These are likely the most recent months that TLC hasn't published yet. Re-run the script later -- already downloaded files won't be re-fetched." -ForegroundColor Yellow
}
