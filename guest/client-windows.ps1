$ErrorActionPreference = 'Stop'

$phase = $env:DNS_LAB_PHASE

$primary = if ($phase -eq 'fast-servfail-control') { '10.10.2.4' } else { '168.63.129.16' }

$root = "C:\dnslab\$phase"

$null = New-Item -ItemType Directory -Force -Path $root

Set-Content -LiteralPath "$root\queries.jsonl" -Value ''

$adapter = Get-NetAdapter | Where-Object Status -eq 'Up' | Where-Object { $_.HardwareInterface } | Select-Object -First 1

if (-not $adapter) { throw 'No active physical network adapter found' }

Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ServerAddresses @($primary)

Clear-DnsClientCache

Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ServerAddresses @($primary, '10.30.0.4')

Get-DnsClientServerAddress | Format-List * | Out-File "$root\configuration.txt"

Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber | Format-List | Out-File "$root\configuration.txt" -Append

function Record($data) {

    $data.utc = [DateTime]::UtcNow.ToString('o')

    $data | ConvertTo-Json -Depth 8 -Compress | Add-Content "$root\queries.jsonl"

}

function Query($index, $stage) {

    $name = "$phase-$stage-$index-$([guid]::NewGuid().ToString('N').Substring(0,10)).lab.failover.test"

    $start = [DateTime]::UtcNow.ToString('o')

    $timer = [Diagnostics.Stopwatch]::StartNew()

    $result = @{kind='native'; phase=$phase; stage=$stage; index=$index; name=$name; startedUtc=$start; primary=$primary}

    try {

        $addresses = @([Net.Dns]::GetHostAddresses($name) | ForEach-Object IPAddressToString)

        $result.success = $true

        $result.answers = $addresses

    } catch [System.Net.Sockets.SocketException] {

        $result.success = $false

        $result.answers = @()

        $result.error = $_.Exception.Message

        $result.errorCode = $_.Exception.NativeErrorCode

    }

    $result.elapsedMs = $timer.Elapsed.TotalMilliseconds

    Record $result

    Start-Sleep -Milliseconds 500

}

& pktmon filter remove | Out-Null

& pktmon filter add LabDNS -p 53 | Out-Null

if ($LASTEXITCODE) { throw 'pktmon filter failed' }

& pktmon start --capture --comp nics --pkt-size 0 --file-name "$root\dns.etl" | Out-Null

if ($LASTEXITCODE) { throw 'pktmon start failed' }

$blocked = $false

try {

    if ($phase -eq 'primary-timeout') {

        0..2 | ForEach-Object { Query $_ 'before' }

        $action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument '-NoProfile -Command "Get-NetFirewallRule -DisplayName DNSLabPrimaryTimeout* | Remove-NetFirewallRule"'

        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(8)

        $null = Register-ScheduledTask -TaskName DNSLabRollback -Action $action -Trigger $trigger -User SYSTEM -RunLevel Highest -Force

        foreach ($protocol in @('UDP','TCP')) {

            $null = New-NetFirewallRule -DisplayName "DNSLabPrimaryTimeout$protocol" -Direction Outbound -Action Block -Protocol $protocol -RemotePort 53 -RemoteAddress '168.63.129.16'

        }

        $blocked = $true

        Record @{kind='fault-applied'; phase=$phase; rules=@(Get-NetFirewallRule -DisplayName DNSLabPrimaryTimeout* | Select-Object DisplayName,Enabled,Direction,Action)}

    }

    $stage = if ($phase -in @('baseline','recovery')) { 'healthy' } else { 'fault' }

    0..14 | ForEach-Object { Query $_ $stage }

    $servers = @($primary,'10.30.0.4')

    if ($phase -eq 'no-east-peering') { $servers += '10.10.0.4' }

    foreach ($server in $servers) {

        $name = "diag-$([guid]::NewGuid().ToString('N').Substring(0,10)).lab.failover.test"

        try {

            $answer = Resolve-DnsName -Name $name -Server $server -Type A -DnsOnly -NoHostsFile -QuickTimeout -ErrorAction Stop

            Record @{kind='direct'; server=$server; success=$true; records=@($answer | Select-Object Name,Type,IPAddress)}

        } catch [System.ComponentModel.Win32Exception] {

            Record @{kind='direct'; server=$server; success=$false; error=$_.Exception.Message; errorCode=$_.Exception.NativeErrorCode}

        }

    }

} finally {

    if ($phase -eq 'fast-servfail-control') {

        Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ServerAddresses @('168.63.129.16','10.30.0.4')

        Clear-DnsClientCache

    }

    if ($blocked) {

        Get-NetFirewallRule -DisplayName DNSLabPrimaryTimeout* | Remove-NetFirewallRule

        Unregister-ScheduledTask -TaskName DNSLabRollback -Confirm:$false

        Record @{kind='fault-restored'; phase=$phase}

        0..2 | ForEach-Object { Query $_ 'after' }

    }

    & pktmon stop | Out-File "$root\capture-stop.txt"

    if ($LASTEXITCODE) { throw 'pktmon stop failed' }

}

& pktmon etl2pcap "$root\dns.etl" --out "$root\dns.pcapng" | Out-Null

if ($LASTEXITCODE) { throw 'pktmon pcap conversion failed' }

& pktmon etl2txt "$root\dns.etl" --out "$root\packets.txt" | Out-Null

if ($LASTEXITCODE) { throw 'pktmon text conversion failed' }

Write-Output (@{phase=$phase; evidence=$root; complete=$true} | ConvertTo-Json -Compress)

