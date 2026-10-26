param(

    [string]$Subscription = $env:AZURE_SUBSCRIPTION_ID,

    [string]$ResourceGroup = 'rg-dns-crossregion-failover-poc',

    [string]$DeploymentName = 'dns-crossregion-poc',

    [string]$EastSize = 'Standard_B2s',

    [string]$WestSize = 'Standard_B2s'

)

$ErrorActionPreference = 'Stop'

function Invoke-Az {

    param([string[]]$Arguments)

    $scopeArguments = if ($Subscription) { @('--subscription', $Subscription) } else { @() }

    $result = & az @Arguments @scopeArguments --only-show-errors

    if ($LASTEXITCODE -ne 0) { throw "Azure CLI failed: $($Arguments[0..1] -join ' ')" }

    return $result

}

$account = Invoke-Az @('account', 'show', '-o', 'json') | ConvertFrom-Json

if (-not $account.id) { throw 'Azure CLI did not return a subscription. Run az login first.' }

$Subscription = $account.id

Write-Output "Deploying to subscription $Subscription, resource group $ResourceGroup"

$null = Invoke-Az @('group', 'create', '--name', $ResourceGroup, '--location', 'eastus', '--tags', 'purpose=dns-failover-poc', 'owner=dnstest', 'cleanup=manual', '-o', 'json')

$bytes = New-Object byte[] 32

[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)

$env:DNSPOC_PASSWORD = 'Aa1!' + [Convert]::ToBase64String($bytes)

try {

    # Keep the credential out of source and CLI argument strings.

    $template = Join-Path $PSScriptRoot 'infra\main.bicep'

    $parameters = @{ adminPassword = @{ value = $env:DNSPOC_PASSWORD }; eastSize = @{ value = $EastSize }; westSize = @{ value = $WestSize } }

    $parameterFile = Join-Path ([IO.Path]::GetTempPath()) ("dnspoc-" + [guid]::NewGuid() + '.json')

    $parameters | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $parameterFile

    $null = Invoke-Az @('deployment', 'group', 'create', '--resource-group', $ResourceGroup, '--name', $DeploymentName, '--template-file', $template, '--parameters', "@$parameterFile", '-o', 'json')

    $outputs = Invoke-Az @('deployment', 'group', 'show', '-g', $ResourceGroup, '-n', $DeploymentName, '--query', 'properties.outputs', '-o', 'json')

    $outputs | Set-Content (Join-Path $PSScriptRoot 'deployment-outputs.json')

    Write-Output "Deployment ready: $ResourceGroup"

} finally {

    Remove-Item Env:\DNSPOC_PASSWORD -ErrorAction SilentlyContinue

    if ($parameterFile -and (Test-Path -LiteralPath $parameterFile)) { Remove-Item -LiteralPath $parameterFile }

}

