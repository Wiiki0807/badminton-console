#Requires -Version 5.1
<#
Verifies the admin path end to end: sign in, exercise an admin-only write, then
confirm the same write is refused without the token. The password is typed at the
prompt and never stored.

Kept ASCII-only: Windows PowerShell 5.1 decodes BOM-less script files as ANSI.
#>
param(
    [string]$BaseUrl = "https://mango-bay-0083f4c00.7.azurestaticapps.net"
)

$ErrorActionPreference = 'Stop'
$failures = 0

function Check([string]$Label, $Expected, $Actual) {
    $ok = "$Expected" -eq "$Actual"
    if (-not $ok) { $script:failures++ }
    $mark = if ($ok) { 'PASS' } else { 'FAIL' }
    "{0}  {1,-44} expected {2}, got {3}" -f $mark, $Label, $Expected, $Actual
}

function Send([string]$Path, [string]$Method = 'GET', $Body = $null, [string]$Token = '') {
    $params = @{
        Uri             = "$BaseUrl$Path"
        Method          = $Method
        UseBasicParsing = $true
        Headers         = @{}
    }
    if ($Token) { $params.Headers['X-Admin-Token'] = $Token }
    if ($null -ne $Body) {
        $params.Body = [System.Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Compress))
        $params.ContentType = 'application/json'
    }
    # Windows PowerShell 5.1 throws on 4xx/5xx, so unwrap the response instead of failing.
    try {
        Invoke-WebRequest @params
    }
    catch [System.Net.WebException] {
        $response = $_.Exception.Response
        if ($null -eq $response) { throw }
        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        [pscustomobject]@{ StatusCode = [int]$response.StatusCode; Content = $reader.ReadToEnd() }
    }
}

$username = Read-Host 'admin username'
$secure = Read-Host 'admin password' -AsSecureString
$password = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))

"--- wrong credentials are rejected ---"
Check 'POST /api/auth/login (wrong password)' 401 (Send '/api/auth/login' 'POST' @{ username = $username; password = 'definitely-not-the-password' }).StatusCode
Check 'POST /api/auth/login (wrong username)' 401 (Send '/api/auth/login' 'POST' @{ username = "$username-nope"; password = $password }).StatusCode

"`n--- sign in ---"
$login = Send '/api/auth/login' 'POST' @{ username = $username; password = $password }
$password = $null
Check 'POST /api/auth/login' 200 $login.StatusCode
$session = $login.Content | ConvertFrom-Json
$token = $session.token
Check 'login returns a token' $true ([bool]$token)
Check 'login reports the username' $username $session.user

$me = (Send '/api/auth/me' 'GET' $null $token).Content | ConvertFrom-Json
Check 'auth/me reports signed in' $true $me.authenticated
Check 'auth/me returns the username' $username $me.user

"`n--- a tampered token is refused ---"
$forged = $token.Substring(0, $token.Length - 4) + 'AAAA'
Check 'auth/me with tampered token' $false ((Send '/api/auth/me' 'GET' $null $forged).Content | ConvertFrom-Json).authenticated
Check 'POST /api/live-state with tampered token' 401 (Send '/api/live-state' 'POST' @{ courts = @() } $forged).StatusCode

"`n--- admin-only writes ---"
$snapshot = @{ updatedAt = 0; courts = @(); recent = @(); stats = @() }
Check 'POST /api/live-state without token' 401 (Send '/api/live-state' 'POST' $snapshot).StatusCode
Check 'POST /api/live-state with token' 200 (Send '/api/live-state' 'POST' $snapshot $token).StatusCode

$wishId = ((Send '/api/wishes' 'POST' @{ playerName = 'smoke-admin'; type = 'boss'; target = '' }).Content | ConvertFrom-Json).id
Check 'POST /api/wishes/action without token' 401 (Send '/api/wishes/action' 'POST' @{ id = $wishId; status = 'fulfilled' }).StatusCode
Check 'POST /api/wishes/action with token' 200 (Send '/api/wishes/action' 'POST' @{ id = $wishId; status = 'fulfilled' } $token).StatusCode
Check 'POST /api/wishes/action rejects bad status' 400 (Send '/api/wishes/action' 'POST' @{ id = $wishId; status = 'whatever' } $token).StatusCode

"`n--- sign out ---"
Check 'POST /api/auth/logout' 200 (Send '/api/auth/logout' 'POST' @{} $token).StatusCode

"`n{0} check(s) failed." -f $failures
exit $failures
