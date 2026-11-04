# 공문양식(.hwp)을 HWPML(.hml)로 내보낸다. 한글(HWP)이 설치된 PC에서 실행.
#   powershell -File tools\export_hml.ps1 -Src "..\공문양식" -Out "build\hml"
param(
  [string]$Src = (Join-Path $PSScriptRoot "..\..\공문양식"),
  [string]$Out = (Join-Path $PSScriptRoot "..\build\hml")
)
New-Item -ItemType Directory -Force $Out | Out-Null
$h = New-Object -ComObject HWPFrame.HwpObject
$n = 0
try {
  Get-ChildItem $Src -Filter *.hwp | ForEach-Object {
    [void]$h.Open($_.FullName, "HWP", "forceopen:true")
    [void]$h.SaveAs((Join-Path $Out ($_.BaseName + ".hml")), "HWPML2X", "")
    [void]$h.Clear(1)
    $n++
  }
} finally { $h.Quit() }
"exported $n -> $Out"
