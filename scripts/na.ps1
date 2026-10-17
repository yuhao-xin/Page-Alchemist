# notion-alchemist wrapper (Windows) — run the CLI straight from a git
# checkout, no installation required.
#
# Usage (PowerShell):
#   .\scripts\na.ps1 demo -o output
#   .\scripts\na.ps1 run "https://www.notion.so/..." --parent "https://..."
#
# If your python is not on PATH (e.g. a venv or the WorkBuddy managed
# interpreter), point at it explicitly first:
#   $env:NOTION_ALCHEMIST_PYTHON = "C:\path\to\python.exe"
#   .\scripts\na.ps1 demo
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $PSScriptRoot

function Test-PythonWorks([string]$Candidate) {
  try {
    $null = & $Candidate -c "import sys" 2>$null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

$Py = $env:NOTION_ALCHEMIST_PYTHON
if ($Py -and -not (Test-PythonWorks $Py)) {
  Write-Error "NOTION_ALCHEMIST_PYTHON='$Py' does not run. Fix the path."
  exit 1
}
if (-not $Py) {
  # NOTE: on many Windows machines `python` on PATH is the Microsoft Store
  # *app-execution alias* stub, which prints an error and exits non-zero.
  # Validate every candidate before accepting it.
  foreach ($c in @("python", "python3", "py")) {
    if (Get-Command $c -ErrorAction SilentlyContinue) {
      if (Test-PythonWorks $c) { $Py = $c; break }
    }
  }
}
if (-not $Py) {
  Write-Error "no working python found on PATH. Set `$env:NOTION_ALCHEMIST_PYTHON to a real interpreter."
  exit 1
}

$env:PYTHONPATH = "$Here\src" + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })
& $Py -m notion_alchemist.cli @Args
exit $LASTEXITCODE
