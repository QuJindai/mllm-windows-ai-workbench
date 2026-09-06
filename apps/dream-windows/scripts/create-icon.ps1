Add-Type -AssemblyName System.Drawing

$iconDirectory = Join-Path $PSScriptRoot "..\src-tauri\icons"
$iconPath = Join-Path $iconDirectory "icon.ico"
New-Item -ItemType Directory -Force -Path $iconDirectory | Out-Null

$bitmap = [System.Drawing.Bitmap]::new(256, 256)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.Clear([System.Drawing.Color]::FromArgb(7, 18, 27))
$graphics.FillRectangle([System.Drawing.Brushes]::DarkSlateGray, 12, 12, 232, 232)
$graphics.DrawRectangle([System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(50, 199, 255), 7), 12, 12, 232, 232)
$font = [System.Drawing.Font]::new("Segoe UI", 132, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$format = [System.Drawing.StringFormat]::new()
$format.Alignment = [System.Drawing.StringAlignment]::Center
$format.LineAlignment = [System.Drawing.StringAlignment]::Center
$graphics.DrawString("D", $font, [System.Drawing.Brushes]::Aqua, [System.Drawing.RectangleF]::new(20, 10, 216, 230), $format)
$graphics.Dispose()
$font.Dispose()
$format.Dispose()
$icon = [System.Drawing.Icon]::FromHandle($bitmap.GetHicon())
$stream = [System.IO.File]::Create($iconPath)
$icon.Save($stream)
$stream.Dispose()
$icon.Dispose()
$bitmap.Dispose()
Write-Output "Created $iconPath"
