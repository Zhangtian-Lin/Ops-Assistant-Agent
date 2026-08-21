param(
    [string]$Owner = 'Zhangtian-Lin',
    [string]$Repository = 'Agent-building-practice',
    [string]$Branch = 'main'
)

$ErrorActionPreference = 'Stop'

if (-not $env:GH_TOKEN) {
    throw 'Set GH_TOKEN in this PowerShell first. It must have repository Administration: write permission. Never store it in this script or Git.'
}

$token = $env:GH_TOKEN.Trim()
if (-not $token) {
    throw 'GH_TOKEN is empty after trimming whitespace.'
}
if ($token -match '[\x00-\x1F\x7F]') {
    throw 'GH_TOKEN contains an internal control character. Copy only the token value, without quotes or line breaks.'
}

$headers = @{
    Accept = 'application/vnd.github+json'
    Authorization = "Bearer $token"
    'X-GitHub-Api-Version' = '2022-11-28'
}

$body = @{
    required_status_checks = @{
        strict = $true
        contexts = @('Required verification')
    }
    enforce_admins = $true
    required_pull_request_reviews = @{
        dismiss_stale_reviews = $true
        require_code_owner_reviews = $false
        required_approving_review_count = 0
        require_last_push_approval = $false
    }
    restrictions = $null
    required_conversation_resolution = $true
    allow_force_pushes = $false
    allow_deletions = $false
    block_creations = $false
    required_linear_history = $false
    lock_branch = $false
    allow_fork_syncing = $true
} | ConvertTo-Json -Depth 8

$uri = "https://api.github.com/repos/$Owner/$Repository/branches/$Branch/protection"
Invoke-RestMethod -Method Put -Uri $uri -Headers $headers -ContentType 'application/json' -Body $body | Out-Null
Write-Host "Branch protection enabled for $Owner/$Repository on $Branch. Required check: Required verification"
