param(
    [Parameter(Mandatory = $true)]
    [string]$Codes,

    [string]$Task = "$(Get-Date -Format 'yyyyMMdd')-nightly-research",
    [string]$Start = "2022-01-01",
    [string]$End = "",
    [string]$Objective = "",
    [string]$Name = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$argsList = @(
    "run",
    "python",
    "scripts\prepare_nightly_research.py",
    "--task",
    $Task,
    "--codes",
    $Codes,
    "--start",
    $Start
)

if ($End -ne "") {
    $argsList += @("--end", $End)
}

if ($Objective -ne "") {
    $argsList += @("--objective", $Objective)
}

if ($Name -ne "") {
    $argsList += @("--name", $Name)
}

if ($Force) {
    $argsList += "--force"
}

& uv @argsList
