# 验证 100.64.0.0/10 网段方案：找出同一网段里开着 CarWithin 的 iPhone，并请求 /tesla。
#
#   .\check_cgnat.ps1                      # 扫 100.96.0.0/24
#   .\check_cgnat.ps1 -Subnet 100.64.1     # 指定前三个字节
#   .\check_cgnat.ps1 -Port 9888

param(
    [string]$Subnet = '100.96.0',
    [int]$Port = 9888,
    [int]$From = 1,
    [int]$To = 254
)

$ErrorActionPreference = 'SilentlyContinue'
Write-Host "== 扫描 $Subnet.$From-$To :$Port ==" -ForegroundColor Cyan

$candidates = @()
foreach ($i in $From..$To) {
    $ip = "$Subnet.$i"
    $client = [System.Net.Sockets.TcpClient]::new()
    $task = $client.ConnectAsync($ip, $Port)
    if ($task.Wait(120) -and $client.Connected) {
        $candidates += $ip
        Write-Host "  找到：$ip`:$Port 开放" -ForegroundColor Green
    }
    $client.Dispose()
}

if (-not $candidates) {
    Write-Host "  没有设备在该网段开 $Port" -ForegroundColor Yellow
    Write-Host "  检查：1) 本机是否在该网段  2) iPhone 的 CarWithin 是否已启动局域网接收页" -ForegroundColor Yellow
    exit 1
}

foreach ($ip in $candidates) {
    foreach ($path in '/tesla', '/') {
        $url = "http://${ip}:$Port$path"
        try {
            $resp = Invoke-WebRequest -Uri $url -TimeoutSec 6 -UseBasicParsing
            $title = if ($resp.Content -match 'CarWithin') { 'CarWithin 页面' } else { '其它页面' }
            Write-Host "  $url -> HTTP $($resp.StatusCode) ($title, $($resp.RawContentLength) 字节)" -ForegroundColor Green
            if ($title -eq 'CarWithin 页面' -and $path -eq '/tesla') {
                Write-Host ""
                Write-Host "  车机浏览器请打开： http://${ip}:$Port/tesla" -ForegroundColor Cyan
            }
        } catch {
            Write-Host "  $url -> 失败：$($_.Exception.Message)" -ForegroundColor DarkGray
        }
    }
}

Write-Host ""
Write-Host "提示：/tesla 是 MJPEG 车机页；若返回 404，说明装的是官方原版（没有这个页面）。" -ForegroundColor DarkGray
