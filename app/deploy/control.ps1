<#
.SYNOPSIS
  DiscordForge Control Panel
  Start / stop / restart Flask, tail logs, rate-limit burst test.
  Run from anywhere -- paths are resolved from the script location.
#>

# ---- Config -----------------------------------------------------------------
$AppDir  = Split-Path $PSScriptRoot -Parent     # .../DiscordForge/app
$LogFile = Join-Path $AppDir 'flask.log'
$PidFile = Join-Path $AppDir '.flask.pid'
$PubUrl  = 'http://193.74.155.90:5000'
$LocUrl  = 'http://127.0.0.1:5000'

# DuckDNS — fill in to enable automatic DNS update when IP changes
# Token: https://www.duckdns.org  (your account token)
$DuckDnsToken  = ''                    # e.g. 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
$DuckDnsDomain = 'discordforge'       # subdomain only, no .duckdns.org

# ---- IP helpers -------------------------------------------------------------
function Get-PublicIp {
    $providers = @(
        'https://api.ipify.org',
        'https://checkip.amazonaws.com',
        'https://ipinfo.io/ip'
    )
    foreach ($url in $providers) {
        try {
            $ip = (Invoke-WebRequest -Uri $url -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop).Content.Trim()
            if ($ip -match '^\d{1,3}(\.\d{1,3}){3}$') { return $ip }
        } catch { }
    }
    return $null
}

function Update-PublicIp {
    Write-Host '  Checking public IP...' -ForegroundColor Cyan
    $currentIp = Get-PublicIp
    if (-not $currentIp) {
        Write-Host '  Could not fetch public IP (no internet?).' -ForegroundColor Red
        return
    }

    # Extract configured IP from $PubUrl
    $knownIp = if ($script:PubUrl -match '//(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})') { $Matches[1] } else { $null }

    $knownIpDisplay = if ($knownIp) { $knownIp } else { 'unknown' }
    Write-Host "  Current public IP : $currentIp" -ForegroundColor White
    Write-Host "  Configured IP     : $knownIpDisplay" -ForegroundColor DarkGray

    if ($currentIp -eq $knownIp) {
        Write-Host '  IP is up to date -- no changes needed.' -ForegroundColor Green
        return
    }

    Write-Host "  IP changed: $knownIp -> $currentIp" -ForegroundColor Yellow
    $confirm = Read-Host '  Update control.ps1 and .env now? [Y/N]'
    if ($confirm -notmatch '^[Yy]') { Write-Host '  Skipped.' -ForegroundColor DarkGray; return }

    # Patch $PubUrl for this session
    $script:PubUrl = $script:PubUrl -replace [regex]::Escape($knownIp), $currentIp

    # Patch control.ps1 on disk
    $selfPath = $PSCommandPath
    if ($selfPath -and (Test-Path $selfPath)) {
        (Get-Content $selfPath -Raw) -replace [regex]::Escape($knownIp), $currentIp |
            Set-Content $selfPath -Encoding UTF8 -NoNewline
        Write-Host '  Updated control.ps1' -ForegroundColor Green
    }

    # Patch .env
    $envPath = Join-Path $AppDir '.env'
    if (Test-Path $envPath) {
        (Get-Content $envPath -Raw) -replace [regex]::Escape($knownIp), $currentIp |
            Set-Content $envPath -Encoding UTF8 -NoNewline
        Write-Host '  Updated .env' -ForegroundColor Green
    }

    # Push to DuckDNS if token is configured
    if ($DuckDnsToken -and $DuckDnsDomain) {
        try {
            $dnsUrl = "https://www.duckdns.org/update?domains=$DuckDnsDomain&token=$DuckDnsToken&ip=$currentIp"
            $resp = (Invoke-WebRequest -Uri $dnsUrl -TimeoutSec 8 -UseBasicParsing -ErrorAction Stop).Content.Trim()
            if ($resp -eq 'OK') {
                Write-Host "  DuckDNS updated ($DuckDnsDomain.duckdns.org -> $currentIp)" -ForegroundColor Green
            } else {
                Write-Host "  DuckDNS returned: $resp" -ForegroundColor Yellow
            }
        } catch {
            Write-Host '  DuckDNS update failed (check token/domain).' -ForegroundColor Red
        }
    }

    Write-Host '  Done. Restart Flask for .env changes to take effect.' -ForegroundColor Cyan
}

# ---- Helpers ----------------------------------------------------------------
function Get-FlaskProc {
    # Match python.exe, python3.exe, AND py.exe (Windows Python Launcher)
    # Looks for server.py (eventlet/SocketIO entry point)
    Get-WmiObject Win32_Process |
        Where-Object { ($_.Name -like 'python*' -or $_.Name -eq 'py.exe') -and $_.CommandLine -like '*server.py*' }
}

function Wait-Enter ([string]$msg = '  Press Enter to continue') {
    Write-Host ''
    Read-Host $msg | Out-Null
}

function Write-Header {
    Clear-Host
    Write-Host ''
    Write-Host '  +------------------------------------------+' -ForegroundColor DarkCyan
    Write-Host '  |     DiscordForge  Control Panel          |' -ForegroundColor Cyan
    Write-Host '  +------------------------------------------+' -ForegroundColor DarkCyan
    Write-Host '  |  [1] Start app                           |'
    Write-Host '  |  [2] Stop app                            |'
    Write-Host '  |  [3] Restart app                         |'
    Write-Host '  |  [4] Status check                        |'
    Write-Host '  |  [5] View logs  (tail flask.log)         |'
    Write-Host '  |  [6] Rate-limit burst test               |'
    Write-Host '  |  [7] Open stress tests in browser        |'
    Write-Host '  |  [8] Check / update public IP            |'
    Write-Host '  |  [Q] Quit                                |'
    Write-Host '  +------------------------------------------+' -ForegroundColor DarkCyan
    Write-Host ''
}

function Show-Status {
    $proc = Get-FlaskProc

    if ($proc) {
        Write-Host "  Flask  running  PID $($proc.ProcessId)  " -NoNewline -ForegroundColor Green
        try {
            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            $r  = Invoke-WebRequest -Uri "$LocUrl/login" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
            $sw.Stop()
            Write-Host "HTTP $($r.StatusCode)  $($sw.ElapsedMilliseconds)ms" -ForegroundColor Green
        } catch {
            $sw.Stop()
            Write-Host 'not responding yet' -ForegroundColor Yellow
        }
    } else {
        Write-Host '  Hello! DiscordForge is not running yet -- press [1] to start it.' -ForegroundColor Yellow
    }

    # Show public IP and warn if it no longer matches the configured one
    $currentIp = Get-PublicIp
    if ($currentIp) {
        $knownIp = if ($script:PubUrl -match '//(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})') { $Matches[1] } else { $null }
        if ($knownIp -and $currentIp -ne $knownIp) {
            Write-Host "  ⚠  IP mismatch!  public=$currentIp  configured=$knownIp  → press [8] to update" -ForegroundColor Yellow
        } else {
            Write-Host "  Public IP: $currentIp" -ForegroundColor DarkGray
        }
    }

    Write-Host ''
}

# ---- Actions ----------------------------------------------------------------
function Start-App {
    if (Get-FlaskProc) {
        Write-Host '  Flask is already running. Use [3] Restart to reload it.' -ForegroundColor Yellow
        return
    }

    Write-Host '  Starting Flask...' -ForegroundColor Cyan

    # Build the command, then Base64-encode it for -EncodedCommand.
    # This bypasses Windows API argument-quoting which strips embedded double quotes,
    # which is what broke cmd /c "..." 2>&1 -- the quotes were silently dropped.
    # With proper quotes, cmd.exe handles 2>&1 at the OS level so PowerShell never
    # sees Python's stderr and no NativeCommandError is generated.
    $cmd = '$env:PYTHONIOENCODING=''utf-8''; ' +
           "Set-Location '$AppDir'; " +
           "Write-Host 'DiscordForge starting (gevent + WebSocket)...' -ForegroundColor Cyan; " +
           "cmd /c ""py server.py 2>&1"" | Tee-Object -FilePath '$LogFile'; " +
           "Write-Host ''; Write-Host 'Flask has stopped.' -ForegroundColor Yellow; " +
           "Read-Host 'Press Enter to close this window'"
    $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))
    $win = Start-Process powershell -ArgumentList @('-NoExit', '-EncodedCommand', $enc) -PassThru
    $win.Id | Set-Content $PidFile

    Start-Sleep -Seconds 2
    if (Get-FlaskProc) {
        Write-Host '  Flask started.' -ForegroundColor Green
        Write-Host "  Local:  $LocUrl" -ForegroundColor DarkGray
        Write-Host "  Public: $PubUrl" -ForegroundColor DarkGray
    } else {
        Write-Host '  Flask may have crashed -- check the terminal window.' -ForegroundColor Red
        if (Test-Path $LogFile) {
            Write-Host '  Last log lines:' -ForegroundColor DarkGray
            Get-Content $LogFile -Tail 10
        }
    }
}

function Stop-App {
    $killed = $false

    if (Test-Path $PidFile) {
        $wid = [int](Get-Content $PidFile -ErrorAction SilentlyContinue)
        if ($wid -and (Get-Process -Id $wid -ErrorAction SilentlyContinue)) {
            Stop-Process -Id $wid -Force -ErrorAction SilentlyContinue
            $killed = $true
        }
        Remove-Item $PidFile -ErrorAction SilentlyContinue
    }

    $procs = Get-FlaskProc
    if ($procs) {
        $procs | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
        $killed = $true
    }

    if ($killed) {
        Write-Host '  Flask stopped.' -ForegroundColor Green
    } else {
        Write-Host '  Flask was not running.' -ForegroundColor DarkGray
    }
}

function Restart-App {
    Write-Host '  Restarting Flask...' -ForegroundColor Cyan
    Stop-App
    Start-Sleep -Milliseconds 1200
    Start-App
}

function View-Logs {
    if (-not (Test-Path $LogFile)) {
        Write-Host '  flask.log not found -- start the app first.' -ForegroundColor Yellow
        return
    }
    Write-Host "  Tailing $LogFile -- Ctrl+C to return to menu" -ForegroundColor DarkGray
    Write-Host ''
    try { Get-Content $LogFile -Wait -Tail 50 } catch { <# Ctrl+C #> }
}

function Test-RateLimit {
    Write-Host ''
    Write-Host '  Rate-limit burst test' -ForegroundColor Cyan
    Write-Host '  -----------------------------------------------'
    Write-Host '  Endpoint:'
    Write-Host '    [1] GET  /login'
    Write-Host '    [2] POST /login  (form submission)'
    Write-Host '    [3] GET  /register'
    Write-Host '    [4] GET  /api/servers/list'
    Write-Host '    [5] GET  /  (home)'
    Write-Host ''
    $ep = Read-Host '  Endpoint [1-5, default 1]'
    if ($ep -notmatch '^[1-5]$') { $ep = '1' }

    $n = Read-Host '  Number of requests [default 30]'
    if ($n -notmatch '^\d+$') { $n = 30 } else { $n = [int]$n }

    $delay = Read-Host '  Delay between requests ms [default 0 = max speed]'
    if ($delay -notmatch '^\d+$') { $delay = 0 } else { $delay = [int]$delay }

    $method = 'GET'
    $body   = $null
    $url    = switch ($ep) {
        '1' { "$LocUrl/login" }
        '2' { $method = 'POST'; $body = 'username=testuser&password=hunter2&remember=on'; "$LocUrl/login" }
        '3' { "$LocUrl/register" }
        '4' { "$LocUrl/api/servers/list" }
        '5' { "$LocUrl/" }
    }

    Write-Host ''
    Write-Host "  Firing $n x $method $url" -ForegroundColor Yellow
    if ($ep -eq '2') {
        Write-Host '  (POST without valid CSRF token -- expect 400/302, not 429 unless rate-limit fires first)' -ForegroundColor DarkGray
    }
    Write-Host '  -----------------------------------------------'
    Write-Host '  #      Code    Time' -ForegroundColor DarkGray

    $pass    = 0
    $blocked = 0
    $errs    = 0
    $times   = [System.Collections.Generic.List[long]]::new()

    for ($i = 1; $i -le $n; $i++) {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        try {
            $p = @{
                Uri                = $url
                Method             = $method
                TimeoutSec         = 5
                UseBasicParsing    = $true
                MaximumRedirection = 0
                ErrorAction        = 'Stop'
            }
            if ($body) { $p.Body = $body; $p.ContentType = 'application/x-www-form-urlencoded' }
            $r    = Invoke-WebRequest @p
            $sw.Stop(); $ms = $sw.ElapsedMilliseconds; $times.Add($ms)
            $code = $r.StatusCode
        } catch {
            $sw.Stop(); $ms = $sw.ElapsedMilliseconds; $times.Add($ms)
            $code = 0
            if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        }

        if ($code -eq 429)                 { $color = 'Red';    $blocked++ }
        elseif ($code -in 200,301,302,303) { $color = 'Green';  $pass++    }
        elseif ($code -gt 0)               { $color = 'Yellow'; $pass++    }
        else                               { $color = 'Red';    $errs++    }

        $label = if ($code) { $code } else { 'ERR' }
        Write-Host ("  {0,-7}{1,-8}{2}ms" -f $i, $label, $ms) -ForegroundColor $color

        if ($delay -gt 0) { Start-Sleep -Milliseconds $delay }
    }

    $avg = if ($times.Count) { [int](($times | Measure-Object -Sum).Sum / $times.Count) } else { 0 }
    $min = if ($times.Count) { ($times | Measure-Object -Minimum).Minimum } else { 0 }
    $max = if ($times.Count) { ($times | Measure-Object -Maximum).Maximum } else { 0 }

    Write-Host ''
    Write-Host '  -----------------------------------------------'
    Write-Host "  OK/redir: $pass   Blocked (429): $blocked   Errors: $errs"
    Write-Host "  Latency : avg ${avg}ms   min ${min}ms   max ${max}ms"
    if ($blocked -eq 0) {
        Write-Host '  No 429s -- rate limiting not yet applied on this endpoint.' -ForegroundColor Yellow
        Write-Host '  Add @limiter.limit("X per Y") to the route in app.py to enable.' -ForegroundColor DarkGray
    } else {
        Write-Host "  Rate limiting active: $blocked / $n requests blocked." -ForegroundColor Green
    }
    Write-Host ''
}

# ---- Main loop --------------------------------------------------------------
while ($true) {
    Write-Header
    Show-Status

    $c = Read-Host '  Choice'
    switch ($c.Trim().ToLower()) {
        '1' { Start-App;       Wait-Enter }
        '2' { Stop-App;        Wait-Enter }
        '3' { Restart-App;     Wait-Enter }
        '4' { Show-Status;     Wait-Enter }
        '5' { View-Logs }
        '6' { Test-RateLimit;  Wait-Enter }
        '7' { Start-Process "$LocUrl/stress-tests/index.html" }
        '8' { Update-PublicIp; Wait-Enter }
        'q' { Write-Host '  Bye!'; exit }
        default { Write-Host '  Unknown option.' -ForegroundColor Red; Start-Sleep -Seconds 1 }
    }
}
