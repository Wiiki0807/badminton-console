#Requires -Version 5.1
<#
Post-deploy smoke test: checks anonymous access, ETag caching, and that admin-only
endpoints reject unauthenticated callers.

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

function Send([string]$Path, [string]$Method = 'GET', $Body = $null, $Headers = @{}) {
    $params = @{
        Uri             = "$BaseUrl$Path"
        Method          = $Method
        Headers         = $Headers
        UseBasicParsing = $true
    }
    if ($null -ne $Body) {
        $params.Body = ([System.Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Compress)))
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
        [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            Content    = $reader.ReadToEnd()
            Headers    = $response.Headers
        }
    }
}

"--- static content ---"
Check 'GET /live.html' 200 (Send '/live.html').StatusCode
Check 'GET /index.html' 200 (Send '/index.html').StatusCode
Check 'GET /server.py is blocked' 404 (Send '/server.py').StatusCode
Check 'GET /tools/smoke_test.ps1 is blocked' 404 (Send '/tools/smoke_test.ps1').StatusCode

"`n--- anonymous api ---"
$bundle = Send '/api/live-bundle'
Check 'GET /api/live-bundle' 200 $bundle.StatusCode
$etag = $bundle.Headers.ETag
if ($etag -is [array]) { $etag = $etag[0] }
Check 'GET /api/live-bundle with If-None-Match' 304 (Send '/api/live-bundle' 'GET' $null @{ 'If-None-Match' = $etag }).StatusCode

# Built from code points so the file stays ASCII while still proving UTF-8 round-trips.
$chineseName = [char]0x7403 + [string][char]0x53CB
$comment = Send '/api/comments' 'POST' @{ name = $chineseName; message = 'smoke test'; matchId = ''; matchLabel = '' }
Check 'POST /api/comments (anonymous)' 201 $comment.StatusCode
$created = $comment.Content | ConvertFrom-Json
$commentId = $created.id
Check 'comment name survives UTF-8 round-trip' $chineseName $created.name

# Windows PowerShell 5.1 has no `u{...} escape, so build the emoji from its code point.
$badminton = [char]::ConvertFromUtf32(0x1F3F8)
$unsupported = [char]::ConvertFromUtf32(0x1F4A9)
Check 'POST /api/reactions (anonymous)' 200 (Send '/api/reactions' 'POST' @{ id = $commentId; emoji = $badminton }).StatusCode
Check 'POST /api/reactions rejects bad emoji' 400 (Send '/api/reactions' 'POST' @{ id = $commentId; emoji = $unsupported }).StatusCode
Check 'POST /api/comments rejects empty body' 400 (Send '/api/comments' 'POST' @{ name = ''; message = '' }).StatusCode

$wish = Send '/api/wishes' 'POST' @{ playerName = 'smoke-test'; type = 'boss'; target = '' }
Check 'POST /api/wishes (anonymous)' 201 $wish.StatusCode
$wishId = ($wish.Content | ConvertFrom-Json).id

"`n--- admin gate ---"
Check 'POST /api/live-state without token' 401 (Send '/api/live-state' 'POST' @{ courts = @() }).StatusCode
Check 'POST /api/wishes/action without token' 401 (Send '/api/wishes/action' 'POST' @{ id = $wishId; status = 'fulfilled' }).StatusCode
Check 'GET /api/auth/me without token' 200 (Send '/api/auth/me').StatusCode
$me = (Send '/api/auth/me').Content | ConvertFrom-Json
Check 'auth/me reports signed out' 0 ([int][bool]$me.authenticated)
Check 'POST /api/live-state with forged token' 401 (Send '/api/live-state' 'POST' @{ courts = @() } @{ Authorization = 'Bearer forged.token' }).StatusCode

"`n--- new comment invalidates the ETag ---"
Check 'GET /api/live-bundle after write' 200 (Send '/api/live-bundle' 'GET' $null @{ 'If-None-Match' = $etag }).StatusCode

"`n{0} check(s) failed." -f $failures
exit $failures
